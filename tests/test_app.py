import io
import json
import logging

from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter, request_id_ctx
from app.main import app
from app.services import auth_service


def test_health_checks_the_database(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_request_id_is_generated_and_echoed(client):
    generated = client.get("/health").headers["X-Request-ID"]
    echoed = client.get("/health", headers={"X-Request-ID": "my-trace-123"}).headers["X-Request-ID"]

    assert len(generated) == 32
    assert echoed == "my-trace-123"


def test_errors_use_one_format_and_include_the_request_id(client):
    response = client.get("/bookings/1", headers={"X-Request-ID": "abc"})

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "not_authenticated", "message": "Not authenticated", "request_id": "abc"}
    }


def test_unknown_route_and_wrong_method_use_the_same_error_format(client):
    not_found = client.get("/nope")
    wrong_method = client.delete("/auth/login")

    assert not_found.status_code == 404 and not_found.json()["error"]["code"] == "not_found"
    assert wrong_method.status_code == 405 and wrong_method.json()["error"]["code"] == "method_not_allowed"


def test_unexpected_errors_return_a_generic_500_without_leaking_details(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(auth_service, "signup", boom)

    response = TestClient(app, raise_server_exceptions=False).post(
        "/auth/signup", json={"email": "a@example.com", "password": "long-enough-pw"}
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in response.text


def test_state_changes_are_logged_as_structured_records(client, book, pay, user_headers, caplog):
    with caplog.at_level(logging.INFO):
        booking_id = book(user_headers).json()["id"]
        pay(user_headers, booking_id, "SUCCESS")

    messages = {r.message for r in caplog.records}
    assert {"booking_created", "booking_status_changed", "payment_created", "request_completed"} <= messages


def test_logs_never_contain_passwords_or_tokens(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post("/auth/signup", json={"email": "a@example.com", "password": "super-secret-pw-123"})
        token = client.post("/auth/login", json={"email": "a@example.com", "password": "super-secret-pw-123"}).json()[
            "access_token"
        ]
        client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    logged = " ".join(str(r.__dict__) for r in caplog.records)
    assert "super-secret-pw-123" not in logged
    assert token not in logged


def test_openapi_schema_documents_every_endpoint(client):
    schema = client.get("/openapi.json").json()

    expected = {
        "/auth/signup", "/auth/login", "/auth/me", "/centres/", "/centres/{centre_id}",
        "/centres/{centre_id}/tests/{test_id}", "/tests/", "/tests/{test_id}", "/bookings/",
        "/bookings/{booking_id}", "/bookings/{booking_id}/cancel", "/payments/", "/payments/webhook/", "/health",
    }
    assert expected <= set(schema["paths"])
    webhook_body = schema["paths"]["/payments/webhook/"]["post"]["requestBody"]["content"]["application/json"]
    assert webhook_body["example"]["status"] == "SUCCESS"
    assert client.get("/docs").status_code == 200


def test_json_formatter_emits_one_json_object_with_request_id_and_extras():
    token = request_id_ctx.set("req-1")
    try:
        record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "something_happened", (), None)
        record.booking_id = 5
        data = json.loads(JsonFormatter().format(record))
    finally:
        request_id_ctx.reset(token)

    assert data["message"] == "something_happened"
    assert (data["level"], data["request_id"], data["booking_id"]) == ("INFO", "req-1", 5)


def test_logs_written_inside_services_carry_the_request_id(client, catalog, user_headers):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("app.booking")
    logger.addHandler(handler)
    previous_level, _ = logger.level, logger.setLevel(logging.INFO)
    try:
        client.post(
            "/bookings/",
            json={"centre_id": catalog.centre_id, "test_id": catalog.test_id,
                  "appointment_datetime": "2999-01-01T10:00:00+00:00"},
            headers={**user_headers, "X-Request-ID": "trace-42"},
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert any(line["message"] == "booking_created" and line["request_id"] == "trace-42" for line in lines)
