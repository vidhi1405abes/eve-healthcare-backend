from datetime import timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.rate_limit import auth_limiter
from app.core.security import create_access_token
from app.models import User
from tests.helpers import auth

CREDS = {"email": "patient@example.com", "password": "correct-horse-battery"}


def test_signup_creates_user_without_exposing_password(client, db):
    response = client.post("/auth/signup", json=CREDS)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == CREDS["email"]
    assert body["is_admin"] is False
    assert "password" not in response.text and "hashed_password" not in response.text

    stored = db.query(User).one()
    assert stored.hashed_password != CREDS["password"]
    assert stored.hashed_password.startswith("$2")


def test_signup_duplicate_email_returns_409(client):
    client.post("/auth/signup", json=CREDS)
    response = client.post("/auth/signup", json=CREDS)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"


def test_signup_duplicate_email_is_case_insensitive(client):
    client.post("/auth/signup", json=CREDS)
    response = client.post("/auth/signup", json={**CREDS, "email": "PATIENT@Example.com"})

    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "long-enough-pw"},
        {"email": "a@example.com", "password": "short"},
        {"email": "a@example.com", "password": "x" * 73},
        {"email": "a@example.com"},
        {},
    ],
)
def test_signup_validation_errors_return_422(client, payload):
    response = client.post("/auth/signup", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_validation_error_does_not_echo_the_submitted_password(client):
    response = client.post("/auth/signup", json={"email": "a@example.com", "password": "abc123"})

    assert response.status_code == 422
    assert "abc123" not in response.text


def test_login_returns_a_working_token(client):
    client.post("/auth/signup", json=CREDS)
    response = client.post("/auth/login", json=CREDS)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_expire_minutes * 60

    me = client.get("/auth/me", headers=auth(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == CREDS["email"]


def test_login_wrong_password_returns_401(client):
    client.post("/auth/signup", json=CREDS)
    response = client.post("/auth/login", json={**CREDS, "password": "wrong-password"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_login_unknown_email_returns_the_same_401(client):
    response = client.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_missing_token_returns_401(client):
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_malformed_token_returns_401(client):
    response = client.get("/auth/me", headers=auth("this.is.not-a-jwt"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_expired_token_returns_401(client, db):
    client.post("/auth/signup", json=CREDS)
    user = db.query(User).one()
    expired = create_access_token(user.id, expires_delta=timedelta(seconds=-10))

    response = client.get("/auth/me", headers=auth(expired))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def test_token_signed_with_another_secret_returns_401(client):
    forged = jwt.encode({"sub": "1", "exp": 9999999999}, "some-other-secret-some-other-secret", algorithm="HS256")

    response = client.get("/auth/me", headers=auth(forged))

    assert response.status_code == 401


def test_token_for_a_user_that_does_not_exist_returns_401(client):
    response = client.get("/auth/me", headers=auth(create_access_token(424242)))

    assert response.status_code == 401


def test_auth_endpoints_are_rate_limited(client):
    auth_limiter.enabled, auth_limiter.limit = True, 3
    try:
        statuses = [client.post("/auth/login", json=CREDS).status_code for _ in range(4)]
    finally:
        auth_limiter.enabled, auth_limiter.limit = False, settings.rate_limit_auth_per_minute
        auth_limiter.reset()

    assert statuses == [401, 401, 401, 429]


def test_rate_limited_response_has_retry_after_header(client):
    auth_limiter.enabled, auth_limiter.limit = True, 1
    try:
        client.post("/auth/login", json=CREDS)
        response = client.post("/auth/login", json=CREDS)
    finally:
        auth_limiter.enabled, auth_limiter.limit = False, settings.rate_limit_auth_per_minute
        auth_limiter.reset()

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1
    assert response.json()["error"]["code"] == "rate_limited"
