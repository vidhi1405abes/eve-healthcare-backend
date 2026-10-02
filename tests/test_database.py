from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Booking, BookingStatus, Centre, CentreTest, DiagnosticTest, Payment, PaymentStatus, User


def _expect_integrity_error(db, *objects):
    db.add_all(objects)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_centre_test_pair_is_unique(db, catalog):
    _expect_integrity_error(db, CentreTest(centre_id=catalog.centre_id, test_id=catalog.test_id, price=Decimal("1.00")))


def test_negative_prices_are_rejected_by_a_check_constraint(db):
    centre, test = Centre(name="C", location="L"), DiagnosticTest(name="T")
    db.add_all([centre, test])
    db.flush()
    _expect_integrity_error(db, CentreTest(centre_id=centre.id, test_id=test.id, price=Decimal("-1.00")))


def test_foreign_keys_are_enforced(db):
    _expect_integrity_error(db, CentreTest(centre_id=9999, test_id=9999, price=Decimal("1.00")))


def test_email_is_unique(db):
    db.add(User(email="a@example.com", hashed_password="x"))
    db.commit()
    _expect_integrity_error(db, User(email="a@example.com", hashed_password="y"))


def test_booking_amount_cannot_be_negative(db, catalog):
    user = User(email="a@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    _expect_integrity_error(
        db,
        Booking(
            user_id=user.id,
            centre_id=catalog.centre_id,
            test_id=catalog.test_id,
            appointment_datetime=datetime.now(timezone.utc) + timedelta(days=1),
            amount=Decimal("-5.00"),
            status=BookingStatus.PENDING,
        ),
    )


def test_provider_reference_and_per_user_idempotency_key_are_unique(db, catalog):
    user = User(email="a@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    booking = Booking(
        user_id=user.id,
        centre_id=catalog.centre_id,
        test_id=catalog.test_id,
        appointment_datetime=datetime.now(timezone.utc) + timedelta(days=1),
        amount=Decimal("5.00"),
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    db.flush()

    def payment(reference, key):
        return Payment(
            booking_id=booking.id, user_id=user.id, amount=Decimal("5.00"),
            status=PaymentStatus.PENDING, provider_reference=reference, idempotency_key=key,
        )

    db.add(payment("ref-1", "key-1"))
    db.commit()
    _expect_integrity_error(db, payment("ref-1", None))
    _expect_integrity_error(db, payment("ref-2", "key-1"))
    db.add_all([payment("ref-3", None), payment("ref-4", None)])
    db.commit()
