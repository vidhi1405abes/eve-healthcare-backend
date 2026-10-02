import os
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg2://eve:eve@localhost:5432/eve_test"
)

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

_url = make_url(TEST_DATABASE_URL)
assert _url.database and _url.database.endswith("_test"), (
    f"Refusing to run tests: database name must end with '_test' (got {_url.database!r})"
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-test-jwt-secret-0123456789"
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["PAYMENT_PENDING_TIMEOUT_MINUTES"] = "30"
os.environ["WEBHOOK_RETRY_BASE_SECONDS"] = "30"
os.environ["WEBHOOK_RETRY_MAX_ATTEMPTS"] = "5"
os.environ["CACHE_TTL_SECONDS"] = "60"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
os.environ["LOG_LEVEL"] = "WARNING"

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.cache import cache
from app.core.rate_limit import auth_limiter
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import Centre, CentreTest, DiagnosticTest, User
from app.services import webhook_failure_service
from tests.helpers import auth, future_iso

from decimal import Decimal


def _create_test_database_if_missing() -> None:
    admin_engine = create_engine(_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": _url.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{_url.database}"'))
    admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    _create_test_database_if_missing()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_database(_schema):
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE webhook_failures, webhook_events, payments, bookings, centre_tests, centres, "
                "diagnostic_tests, users RESTART IDENTITY CASCADE"
            )
        )
    auth_limiter.reset()
    try:
        cache.client.flushdb()
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def scheduled_retries(monkeypatch) -> list[int]:
    scheduled: list[int] = []
    monkeypatch.setattr(webhook_failure_service, "schedule_retry", scheduled.append)
    return scheduled


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _signup_and_login(client: TestClient, email: str, password: str = "password123") -> dict[str, str]:
    assert client.post("/auth/signup", json={"email": email, "password": password}).status_code == 201
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return auth(token)


@pytest.fixture
def user_headers(client) -> dict[str, str]:
    return _signup_and_login(client, "user@example.com")


@pytest.fixture
def other_user_headers(client) -> dict[str, str]:
    return _signup_and_login(client, "other@example.com")


@pytest.fixture
def admin_headers(client, db) -> dict[str, str]:
    headers = _signup_and_login(client, "admin@example.com")
    db.query(User).filter(User.email == "admin@example.com").update({"is_admin": True})
    db.commit()
    return headers


@pytest.fixture
def catalog(db) -> SimpleNamespace:
    centre = Centre(name="Apollo Diagnostics", location="Delhi")
    test = DiagnosticTest(name="Complete Blood Count", description="CBC")
    db.add_all([centre, test])
    db.flush()
    db.add(CentreTest(centre_id=centre.id, test_id=test.id, price=Decimal("500.00")))
    db.commit()
    return SimpleNamespace(centre_id=centre.id, test_id=test.id, price=Decimal("500.00"))


@pytest.fixture
def book(client, catalog):
    def _book(headers, **overrides):
        payload = {
            "centre_id": catalog.centre_id,
            "test_id": catalog.test_id,
            "appointment_datetime": future_iso(),
            **overrides,
        }
        return client.post("/bookings/", json=payload, headers=headers)

    return _book


@pytest.fixture
def pay(client):
    def _pay(headers, booking_id, outcome="SUCCESS", key=None, **extra):
        body = {"booking_id": booking_id, **extra}
        if outcome is not None:
            body["simulate_outcome"] = outcome
        request_headers = dict(headers)
        if key is not None:
            request_headers["Idempotency-Key"] = key
        return client.post("/payments/", json=body, headers=request_headers)

    return _pay
