import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models import Booking, BookingStatus, Payment, PaymentStatus


def _booking_status(db, booking_id):
    db.expire_all()
    return db.get(Booking, booking_id).status


def test_successful_payment_confirms_the_booking(book, pay, user_headers, db):
    booking = book(user_headers).json()

    response = pay(user_headers, booking["id"], "SUCCESS")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["amount"] == booking["amount"] == "500.00"
    assert body["provider_reference"].startswith("pay_")
    assert _booking_status(db, booking["id"]) == BookingStatus.CONFIRMED
    assert db.query(Payment).count() == 1


def test_failed_payment_marks_the_booking_failed(book, pay, user_headers, db):
    booking = book(user_headers).json()

    response = pay(user_headers, booking["id"], "FAILED")

    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"
    assert _booking_status(db, booking["id"]) == BookingStatus.FAILED


def test_failed_payment_can_be_retried_with_a_new_attempt(book, pay, user_headers, db):
    booking_id = book(user_headers).json()["id"]
    pay(user_headers, booking_id, "FAILED")

    retry = pay(user_headers, booking_id, "SUCCESS")

    assert retry.status_code == 201
    assert _booking_status(db, booking_id) == BookingStatus.CONFIRMED
    assert [p.status for p in db.query(Payment).order_by(Payment.id)] == [PaymentStatus.FAILED, PaymentStatus.SUCCESS]


def test_random_outcome_follows_the_configured_success_rate(book, pay, user_headers, monkeypatch):
    booking_id = book(user_headers).json()["id"]

    monkeypatch.setattr(settings, "payment_success_rate", 0.0)
    assert pay(user_headers, booking_id, outcome=None).json()["status"] == "FAILED"

    monkeypatch.setattr(settings, "payment_success_rate", 1.0)
    assert pay(user_headers, booking_id, outcome=None).json()["status"] == "SUCCESS"


def test_pending_payment_keeps_booking_pending_and_blocks_a_second_payment(book, pay, user_headers, db):
    booking_id = book(user_headers).json()["id"]

    first = pay(user_headers, booking_id, "PENDING")
    second = pay(user_headers, booking_id, "SUCCESS")

    assert first.status_code == 201 and first.json()["status"] == "PENDING"
    assert _booking_status(db, booking_id) == BookingStatus.PENDING
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "payment_in_progress"


def test_double_payment_returns_409_and_creates_no_second_payment(book, pay, user_headers, db):
    booking_id = book(user_headers).json()["id"]
    pay(user_headers, booking_id, "SUCCESS")

    response = pay(user_headers, booking_id, "SUCCESS")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "booking_not_payable"
    assert db.query(Payment).count() == 1


def test_paying_a_cancelled_booking_returns_409(client, book, pay, user_headers, db):
    booking_id = book(user_headers).json()["id"]
    client.post(f"/bookings/{booking_id}/cancel", headers=user_headers)

    response = pay(user_headers, booking_id, "SUCCESS")

    assert response.status_code == 409
    assert db.query(Payment).count() == 0


def test_cannot_pay_someone_elses_booking(book, pay, user_headers, other_user_headers, db):
    booking_id = book(user_headers).json()["id"]

    response = pay(other_user_headers, booking_id)

    assert response.status_code == 404
    assert db.query(Payment).count() == 0
    assert _booking_status(db, booking_id) == BookingStatus.PENDING


def test_paying_a_nonexistent_or_invalid_booking(pay, user_headers):
    assert pay(user_headers, 9999).status_code == 404
    assert pay(user_headers, 0).status_code == 422
    assert pay(user_headers, 99999999999).status_code == 422


def test_malformed_payment_requests_return_422(client, user_headers):
    for body in [{}, {"booking_id": "abc"}, {"booking_id": 1, "simulate_outcome": "MAYBE"}]:
        assert client.post("/payments/", json=body, headers=user_headers).status_code == 422


def test_payment_requires_authentication(client):
    assert client.post("/payments/", json={"booking_id": 1}).status_code == 401


def test_client_cannot_choose_the_payment_amount(book, pay, user_headers):
    booking_id = book(user_headers).json()["id"]

    response = pay(user_headers, booking_id, amount="0.01")

    assert response.json()["amount"] == "500.00"


def test_same_idempotency_key_returns_the_original_payment(book, pay, user_headers, db):
    booking_id = book(user_headers).json()["id"]

    first = pay(user_headers, booking_id, "SUCCESS", key="attempt-1")
    second = pay(user_headers, booking_id, "SUCCESS", key="attempt-1")

    assert first.status_code == second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert "idempotent-replayed" not in first.headers
    assert second.headers["Idempotent-Replayed"] == "true"
    assert db.query(Payment).count() == 1


def test_replaying_a_failed_payment_does_not_retry_it(book, pay, user_headers, db):
    booking_id = book(user_headers).json()["id"]
    pay(user_headers, booking_id, "FAILED", key="attempt-1")

    replay = pay(user_headers, booking_id, "SUCCESS", key="attempt-1")

    assert replay.json()["status"] == "FAILED"
    assert db.query(Payment).count() == 1
    assert _booking_status(db, booking_id) == BookingStatus.FAILED


def test_idempotency_key_cannot_be_reused_for_another_booking(book, pay, user_headers, db):
    first_id = book(user_headers).json()["id"]
    second_id = book(user_headers).json()["id"]
    pay(user_headers, first_id, "SUCCESS", key="same-key")

    response = pay(user_headers, second_id, "SUCCESS", key="same-key")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_reused"
    assert db.query(Payment).count() == 1


def test_idempotency_keys_are_scoped_per_user(book, pay, user_headers, other_user_headers, db):
    mine = book(user_headers).json()["id"]
    theirs = book(other_user_headers).json()["id"]

    first = pay(user_headers, mine, "SUCCESS", key="shared-key")
    second = pay(other_user_headers, theirs, "SUCCESS", key="shared-key")

    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]
    assert db.query(Payment).count() == 2


def test_empty_idempotency_key_header_is_rejected(book, pay, user_headers):
    booking_id = book(user_headers).json()["id"]

    assert pay(user_headers, booking_id, "SUCCESS", key="").status_code == 422


def _run_concurrently(n, fn):
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        return fn(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))


def test_concurrent_requests_with_the_same_idempotency_key_create_one_payment(book, user_headers, db):
    booking_id = book(user_headers).json()["id"]

    def attempt(_):
        return TestClient(app).post(
            "/payments/",
            json={"booking_id": booking_id, "simulate_outcome": "SUCCESS"},
            headers={**user_headers, "Idempotency-Key": "race-key"},
        )

    responses = _run_concurrently(6, attempt)

    assert [r.status_code for r in responses] == [201] * 6
    assert len({r.json()["id"] for r in responses}) == 1
    assert db.query(Payment).count() == 1


def test_concurrent_payments_with_different_keys_charge_the_booking_once(book, user_headers, db):
    booking_id = book(user_headers).json()["id"]

    def attempt(i):
        return TestClient(app).post(
            "/payments/",
            json={"booking_id": booking_id, "simulate_outcome": "SUCCESS"},
            headers={**user_headers, "Idempotency-Key": f"key-{i}"},
        )

    responses = _run_concurrently(6, attempt)

    assert sorted(r.status_code for r in responses) == [201, 409, 409, 409, 409, 409]
    assert db.query(Payment).count() == 1
    assert _booking_status(db, booking_id) == BookingStatus.CONFIRMED
