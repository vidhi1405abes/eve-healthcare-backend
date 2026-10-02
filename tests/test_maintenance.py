from datetime import datetime, timedelta, timezone

import pytest

from app.models import Booking, BookingStatus, Payment, PaymentStatus
from app.services.maintenance_service import expire_stale_pending_payments
from app.worker import celery_app, expire_stale_payments
from tests.helpers import signed_headers, webhook_body


@pytest.fixture
def stale_payment(book, pay, user_headers, db):
    booking_id = book(user_headers).json()["id"]
    payment = pay(user_headers, booking_id, "PENDING").json()
    db.query(Payment).update({"created_at": datetime.now(timezone.utc) - timedelta(hours=2)})
    db.commit()
    return {"booking_id": booking_id, "payment_id": payment["id"], "reference": payment["provider_reference"]}


def _states(db, stale):
    db.expire_all()
    return db.get(Booking, stale["booking_id"]).status, db.get(Payment, stale["payment_id"]).status


def test_stale_pending_payment_is_failed_and_the_booking_can_be_paid_again(stale_payment, pay, user_headers, db):
    assert expire_stale_pending_payments(db) == 1

    assert _states(db, stale_payment) == (BookingStatus.FAILED, PaymentStatus.FAILED)
    assert pay(user_headers, stale_payment["booking_id"], "SUCCESS").status_code == 201
    db.expire_all()
    assert db.get(Booking, stale_payment["booking_id"]).status == BookingStatus.CONFIRMED


def test_recent_pending_payments_are_left_alone(book, pay, user_headers, db):
    booking_id = book(user_headers).json()["id"]
    pay(user_headers, booking_id, "PENDING")

    assert expire_stale_pending_payments(db) == 0
    assert db.query(Payment).one().status == PaymentStatus.PENDING


def test_resolved_payments_are_never_expired(book, pay, user_headers, db):
    booking_id = book(user_headers).json()["id"]
    pay(user_headers, booking_id, "SUCCESS")
    db.query(Payment).update({"created_at": datetime.now(timezone.utc) - timedelta(days=3)})
    db.commit()

    assert expire_stale_pending_payments(db) == 0
    assert db.query(Booking).one().status == BookingStatus.CONFIRMED


def test_expiring_twice_does_nothing_the_second_time(stale_payment, db):
    assert expire_stale_pending_payments(db) == 1
    assert expire_stale_pending_payments(db) == 0


def test_cancelled_booking_stays_cancelled_when_its_payment_expires(client, stale_payment, user_headers, db):
    client.post(f"/bookings/{stale_payment['booking_id']}/cancel", headers=user_headers)

    assert expire_stale_pending_payments(db) == 1

    assert _states(db, stale_payment) == (BookingStatus.CANCELLED, PaymentStatus.FAILED)


def test_late_success_webhook_after_expiry_is_ignored(client, stale_payment, db):
    expire_stale_pending_payments(db)
    body = webhook_body("evt-late", stale_payment["reference"], "SUCCESS")

    response = client.post("/payments/webhook/", content=body, headers=signed_headers(body))

    assert response.json()["status"] == "ignored"
    assert _states(db, stale_payment) == (BookingStatus.FAILED, PaymentStatus.FAILED)


def test_celery_task_runs_the_cleanup(stale_payment, db):
    assert expire_stale_payments.apply().get() == 1
    assert _states(db, stale_payment) == (BookingStatus.FAILED, PaymentStatus.FAILED)


def test_cleanup_is_scheduled_by_celery_beat():
    schedule = celery_app.conf.beat_schedule

    assert schedule["expire-stale-pending-payments"]["task"] == "app.worker.expire_stale_payments"
    assert "app.worker.expire_stale_payments" in celery_app.tasks
    assert "app.worker.retry_webhook" in celery_app.tasks
