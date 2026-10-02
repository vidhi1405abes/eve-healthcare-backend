from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models import Booking, BookingStatus, Payment, PaymentStatus, WebhookEvent, WebhookFailure
from app.schemas.webhook import WebhookPayload
from app.services import webhook_failure_service, webhook_service
from app.worker import retry_webhook
from tests.helpers import signed_headers, webhook_body

URL = "/payments/webhook/"


@pytest.fixture
def pending(book, pay, user_headers):
    booking_id = book(user_headers).json()["id"]
    payment = pay(user_headers, booking_id, "PENDING").json()
    return {"booking_id": booking_id, "payment_id": payment["id"], "reference": payment["provider_reference"]}


@pytest.fixture
def send(client):
    def _send(event_id, reference, status="SUCCESS"):
        body = webhook_body(event_id, reference, status)
        return client.post(URL, content=body, headers=signed_headers(body))

    return _send


def _payload(event_id, reference, status="SUCCESS"):
    return WebhookPayload(
        event_id=event_id, provider_reference=reference, status=status, timestamp=datetime.now(timezone.utc)
    )


def test_unknown_payment_is_stored_for_retry_and_still_returns_404(send, db, scheduled_retries):
    response = send("evt-1", "pay_late")

    assert response.status_code == 404
    failure = db.query(WebhookFailure).one()
    assert (failure.event_id, failure.provider_reference, failure.reason) == ("evt-1", "pay_late", "payment_not_found")
    assert failure.attempts == 0 and failure.resolved_at is None
    assert scheduled_retries == [failure.id]


def test_the_same_failing_event_is_stored_and_scheduled_once(send, db, scheduled_retries):
    for _ in range(3):
        assert send("evt-1", "pay_late").status_code == 404

    assert db.query(WebhookFailure).count() == 1
    assert len(scheduled_retries) == 1


def test_unexpected_errors_are_stored_for_retry(monkeypatch, pending, db, scheduled_retries):
    def boom(*args, **kwargs):
        raise RuntimeError("database blinked")

    monkeypatch.setattr(webhook_service, "process_webhook", boom)
    body = webhook_body("evt-1", pending["reference"])

    response = TestClient(app, raise_server_exceptions=False).post(URL, content=body, headers=signed_headers(body))

    assert response.status_code == 500
    failure = db.query(WebhookFailure).one()
    assert failure.reason == "processing_error"
    assert "database blinked" in failure.error
    assert scheduled_retries == [failure.id]


def test_invalid_signature_and_bad_payload_are_not_stored(client, pending, db):
    client.post(URL, content=webhook_body("evt-1", pending["reference"]), headers={"X-Signature": "bad"})
    raw = b'{"event_id": "x"}'
    client.post(URL, content=raw, headers=signed_headers(raw))

    assert db.query(WebhookFailure).count() == 0


def test_retry_applies_the_event_once_the_payment_exists(send, pending, db):
    assert send("evt-1", "pay_late").status_code == 404
    failure = db.query(WebhookFailure).one()
    db.query(Payment).filter_by(id=pending["payment_id"]).update({"provider_reference": "pay_late"})
    db.commit()

    finished = webhook_failure_service.retry_failure(db, failure.id)

    assert finished is True
    db.expire_all()
    assert db.get(Payment, pending["payment_id"]).status == PaymentStatus.SUCCESS
    assert db.get(Booking, pending["booking_id"]).status == BookingStatus.CONFIRMED
    failure = db.get(WebhookFailure, failure.id)
    assert failure.resolved_at is not None and failure.attempts == 1
    assert db.query(WebhookEvent).count() == 1


def test_retry_that_still_fails_counts_the_attempt(send, db):
    send("evt-1", "pay_late")
    failure_id = db.query(WebhookFailure).one().id

    assert webhook_failure_service.retry_failure(db, failure_id) is False
    assert webhook_failure_service.retry_failure(db, failure_id) is False

    db.expire_all()
    failure = db.get(WebhookFailure, failure_id)
    assert failure.attempts == 2 and failure.resolved_at is None and failure.last_attempt_at is not None


def test_retrying_a_resolved_failure_does_nothing(send, pending, db):
    send("evt-1", "pay_late")
    failure_id = db.query(WebhookFailure).one().id
    db.query(Payment).filter_by(id=pending["payment_id"]).update({"provider_reference": "pay_late"})
    db.commit()
    webhook_failure_service.retry_failure(db, failure_id)

    assert webhook_failure_service.retry_failure(db, failure_id) is True

    db.expire_all()
    assert db.get(WebhookFailure, failure_id).attempts == 1
    assert db.query(WebhookEvent).count() == 1


def test_retry_after_the_provider_already_redelivered_is_safe(send, pending, db):
    send("evt-1", "pay_late")
    failure_id = db.query(WebhookFailure).one().id
    db.query(Payment).filter_by(id=pending["payment_id"]).update({"provider_reference": "pay_late"})
    db.commit()
    assert send("evt-1", "pay_late").json()["status"] == "processed"

    assert webhook_failure_service.retry_failure(db, failure_id) is True

    assert db.query(WebhookEvent).count() == 1
    db.expire_all()
    assert db.get(Booking, pending["booking_id"]).status == BookingStatus.CONFIRMED


def test_celery_task_resolves_a_failure_when_it_can(send, pending, db):
    send("evt-1", "pay_late")
    failure_id = db.query(WebhookFailure).one().id
    db.query(Payment).filter_by(id=pending["payment_id"]).update({"provider_reference": "pay_late"})
    db.commit()

    result = retry_webhook.apply(args=[failure_id])

    assert result.successful()
    db.expire_all()
    assert db.get(WebhookFailure, failure_id).resolved_at is not None


def test_celery_task_gives_up_after_the_maximum_number_of_retries(send, db):
    send("evt-1", "pay_late")
    failure_id = db.query(WebhookFailure).one().id

    result = retry_webhook.apply(args=[failure_id])

    assert result.failed()
    db.expire_all()
    failure = db.get(WebhookFailure, failure_id)
    assert failure.attempts == settings.webhook_retry_max_attempts + 1
    assert failure.resolved_at is None


def test_record_failure_reuses_the_open_row_but_not_a_resolved_one(db):
    first_id, created = webhook_failure_service.record_failure(_payload("evt-1", "pay_x"), "payment_not_found", None)
    again_id, created_again = webhook_failure_service.record_failure(_payload("evt-1", "pay_x"), "payment_not_found", None)

    assert (created, created_again, again_id) == (True, False, first_id)

    db.query(WebhookFailure).update({"resolved_at": datetime.now(timezone.utc)})
    db.commit()
    third_id, created_third = webhook_failure_service.record_failure(_payload("evt-1", "pay_x"), "payment_not_found", None)
    assert created_third is True and third_id != first_id
