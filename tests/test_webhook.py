import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.core.security import sign_webhook_body, verify_webhook_signature
from app.main import app
from app.models import Booking, BookingStatus, Payment, PaymentStatus, WebhookEvent, WebhookOutcome
from tests.helpers import signed_headers, webhook_body

URL = "/payments/webhook/"


@pytest.fixture
def pending(book, pay, user_headers):
    booking_id = book(user_headers).json()["id"]
    payment = pay(user_headers, booking_id, "PENDING").json()
    return {"booking_id": booking_id, "payment_id": payment["id"], "reference": payment["provider_reference"]}


@pytest.fixture
def send(client):
    def _send(event_id, reference, status="SUCCESS", **overrides):
        body = webhook_body(event_id, reference, status, **overrides)
        return client.post(URL, content=body, headers=signed_headers(body))

    return _send


def _states(db, booking_id, payment_id):
    db.expire_all()
    return db.get(Booking, booking_id).status, db.get(Payment, payment_id).status


def _counts(db):
    return db.query(Booking).count(), db.query(Payment).count(), db.query(WebhookEvent).count()


def test_success_event_confirms_booking_and_payment(send, pending, db):
    response = send("evt-1", pending["reference"], "SUCCESS")

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert _states(db, pending["booking_id"], pending["payment_id"]) == (BookingStatus.CONFIRMED, PaymentStatus.SUCCESS)
    event = db.query(WebhookEvent).one()
    assert (event.event_id, event.outcome, event.payment_id) == ("evt-1", WebhookOutcome.APPLIED, pending["payment_id"])


def test_failed_event_fails_booking_and_payment(send, pending, db):
    response = send("evt-1", pending["reference"], "FAILED")

    assert response.json()["status"] == "processed"
    assert _states(db, pending["booking_id"], pending["payment_id"]) == (BookingStatus.FAILED, PaymentStatus.FAILED)


def test_failed_booking_can_be_retried_after_a_failed_webhook(send, pay, pending, user_headers, db):
    send("evt-1", pending["reference"], "FAILED")

    retry = pay(user_headers, pending["booking_id"], "SUCCESS")

    assert retry.status_code == 201
    assert _states(db, pending["booking_id"], retry.json()["id"]) == (BookingStatus.CONFIRMED, PaymentStatus.SUCCESS)


def test_duplicate_delivery_changes_state_exactly_once(send, pending, db, caplog):
    before = _counts(db)

    with caplog.at_level(logging.INFO):
        responses = [send("evt-dup", pending["reference"], "SUCCESS") for _ in range(3)]

    assert [r.status_code for r in responses] == [200, 200, 200]
    assert responses[0].json()["status"] == "processed"
    assert responses[1].json() == responses[2].json() == {"status": "already_processed"}
    assert _counts(db) == (before[0], before[1], before[2] + 1)
    changes = [r for r in caplog.records if r.message == "booking_status_changed" and r.reason == "webhook"]
    assert len(changes) == 1
    assert _states(db, pending["booking_id"], pending["payment_id"]) == (BookingStatus.CONFIRMED, PaymentStatus.SUCCESS)


def test_duplicate_event_id_is_ignored_even_if_the_second_copy_says_something_else(send, pending, db):
    send("evt-same-id", pending["reference"], "SUCCESS")

    response = send("evt-same-id", pending["reference"], "FAILED")

    assert response.json() == {"status": "already_processed"}
    assert _states(db, pending["booking_id"], pending["payment_id"]) == (BookingStatus.CONFIRMED, PaymentStatus.SUCCESS)


def test_database_itself_rejects_a_second_event_with_the_same_id(db, pending):
    from sqlalchemy.exc import IntegrityError
    from datetime import datetime, timezone

    row = dict(event_id="evt-x", payment_id=pending["payment_id"], status="SUCCESS", event_timestamp=datetime.now(timezone.utc))
    db.add(WebhookEvent(**row))
    db.commit()
    db.add(WebhookEvent(**row))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_concurrent_duplicate_deliveries_apply_the_event_once(pending, db, caplog):
    body = webhook_body("evt-race", pending["reference"], "SUCCESS")
    barrier = threading.Barrier(8)

    def deliver(_):
        barrier.wait()
        return TestClient(app).post(URL, content=body, headers=signed_headers(body))

    with caplog.at_level(logging.INFO):
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(deliver, range(8)))

    assert all(r.status_code == 200 for r in responses)
    statuses = sorted(r.json()["status"] for r in responses)
    assert statuses == ["already_processed"] * 7 + ["processed"]
    assert db.query(WebhookEvent).count() == 1
    assert db.query(Payment).count() == 1
    assert _states(db, pending["booking_id"], pending["payment_id"]) == (BookingStatus.CONFIRMED, PaymentStatus.SUCCESS)
    assert len([r for r in caplog.records if r.message == "booking_status_changed" and r.reason == "webhook"]) == 1


def test_concurrent_conflicting_events_leave_a_consistent_state(pending, db):
    barrier = threading.Barrier(8)

    def deliver(i):
        status = "SUCCESS" if i % 2 == 0 else "FAILED"
        body = webhook_body(f"evt-{i}", pending["reference"], status)
        barrier.wait()
        return TestClient(app).post(URL, content=body, headers=signed_headers(body))

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(deliver, range(8)))

    assert all(r.status_code == 200 for r in responses)
    assert sorted(r.json()["status"] for r in responses).count("processed") == 1
    booking_status, payment_status = _states(db, pending["booking_id"], pending["payment_id"])
    assert (booking_status, payment_status) in [
        (BookingStatus.CONFIRMED, PaymentStatus.SUCCESS),
        (BookingStatus.FAILED, PaymentStatus.FAILED),
    ]
    assert db.query(WebhookEvent).filter_by(outcome=WebhookOutcome.APPLIED).count() == 1
    assert db.query(WebhookEvent).filter_by(outcome=WebhookOutcome.IGNORED).count() == 7


def test_late_failed_event_does_not_overwrite_a_confirmed_booking(send, pending, db):
    send("evt-1", pending["reference"], "SUCCESS")

    response = send("evt-2", pending["reference"], "FAILED")

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert _states(db, pending["booking_id"], pending["payment_id"]) == (BookingStatus.CONFIRMED, PaymentStatus.SUCCESS)
    assert db.query(WebhookEvent).filter_by(event_id="evt-2").one().outcome == WebhookOutcome.IGNORED


def test_failed_event_after_a_synchronous_success_is_ignored(book, pay, send, user_headers, db):
    booking_id = book(user_headers).json()["id"]
    payment = pay(user_headers, booking_id, "SUCCESS").json()

    response = send("evt-1", payment["provider_reference"], "FAILED")

    assert response.json()["status"] == "ignored"
    assert _states(db, booking_id, payment["id"]) == (BookingStatus.CONFIRMED, PaymentStatus.SUCCESS)


def test_same_status_event_for_an_already_resolved_payment_is_a_no_op(book, pay, send, user_headers, db, caplog):
    booking_id = book(user_headers).json()["id"]
    payment = pay(user_headers, booking_id, "SUCCESS").json()

    with caplog.at_level(logging.INFO):
        response = send("evt-1", payment["provider_reference"], "SUCCESS")

    assert response.json()["status"] == "ignored"
    assert not [r for r in caplog.records if r.message == "booking_status_changed" and r.reason == "webhook"]


def test_webhook_for_a_failed_payment_cannot_resurrect_it(book, pay, send, user_headers, db):
    booking_id = book(user_headers).json()["id"]
    payment = pay(user_headers, booking_id, "FAILED").json()

    response = send("evt-1", payment["provider_reference"], "SUCCESS")

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert _states(db, booking_id, payment["id"]) == (BookingStatus.FAILED, PaymentStatus.FAILED)


def test_success_event_for_a_cancelled_booking_is_ignored(client, send, pending, user_headers, db):
    client.post(f"/bookings/{pending['booking_id']}/cancel", headers=user_headers)

    response = send("evt-1", pending["reference"], "SUCCESS")

    assert response.json()["status"] == "ignored"
    assert _states(db, pending["booking_id"], pending["payment_id"]) == (BookingStatus.CANCELLED, PaymentStatus.PENDING)


def test_webhooks_never_create_payments_or_bookings(send, pending, db):
    bookings, payments, _ = _counts(db)

    send("evt-1", pending["reference"], "SUCCESS")
    send("evt-1", pending["reference"], "SUCCESS")
    send("evt-2", pending["reference"], "FAILED")
    send("evt-3", "pay_does_not_exist", "SUCCESS")

    assert (db.query(Booking).count(), db.query(Payment).count()) == (bookings, payments)


def test_missing_signature_returns_401(client, pending, db):
    body = webhook_body("evt-1", pending["reference"])

    response = client.post(URL, content=body)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_signature"
    assert db.query(WebhookEvent).count() == 0


def test_wrong_signature_returns_401_and_changes_nothing(client, pending, db):
    body = webhook_body("evt-1", pending["reference"])

    response = client.post(URL, content=body, headers={"X-Signature": "0" * 64})

    assert response.status_code == 401
    assert db.query(WebhookEvent).count() == 0
    assert _states(db, pending["booking_id"], pending["payment_id"]) == (BookingStatus.PENDING, PaymentStatus.PENDING)


def test_signature_for_a_different_body_is_rejected(client, pending):
    original = webhook_body("evt-1", pending["reference"], "FAILED")
    tampered = webhook_body("evt-1", pending["reference"], "SUCCESS")

    response = client.post(URL, content=tampered, headers={"X-Signature": sign_webhook_body(original)})

    assert response.status_code == 401


def test_signature_check_does_not_crash_on_garbage(client, pending):
    body = webhook_body("evt-1", pending["reference"])

    for signature in ["", "zzzz", "a" * 10_000, ("é" * 64).encode()]:
        response = client.post(URL, content=body, headers={"X-Signature": signature})
        assert response.status_code == 401


def test_verify_webhook_signature_unit():
    body = b'{"a": 1}'
    good = sign_webhook_body(body)

    assert verify_webhook_signature(body, good)
    assert not verify_webhook_signature(body + b" ", good)
    assert not verify_webhook_signature(body, None)
    assert not verify_webhook_signature(body, good[:-1])


def test_unknown_payment_reference_returns_404_and_records_nothing(send, db):
    response = send("evt-1", "pay_does_not_exist", "SUCCESS")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "payment_not_found"
    assert db.query(WebhookEvent).count() == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "PENDING"},
        {"status": "REFUNDED"},
        {"event_id": ""},
        {"timestamp": "2030-01-01T00:00:00"},
        {"timestamp": "not-a-date"},
    ],
)
def test_invalid_payload_returns_422(client, pending, overrides):
    payload = {
        "event_id": "evt-1",
        "provider_reference": pending["reference"],
        "status": "SUCCESS",
        "timestamp": "2030-01-01T00:00:00+00:00",
        **overrides,
    }
    body = json.dumps(payload).encode()

    response = client.post(URL, content=body, headers=signed_headers(body))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_missing_fields_and_broken_json_return_422(client):
    for raw in [b"{}", b'{"event_id": "x"}', b"not json at all", b"[]", b""]:
        assert client.post(URL, content=raw, headers=signed_headers(raw)).status_code == 422


def test_signature_is_checked_before_the_payload_is_validated(client):
    assert client.post(URL, content=b"not json", headers={"X-Signature": "bad"}).status_code == 401
