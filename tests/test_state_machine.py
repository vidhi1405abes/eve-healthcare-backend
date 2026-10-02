import itertools
import logging
from types import SimpleNamespace

import pytest

from app.core.exceptions import InvalidStateTransition
from app.models import BookingStatus as S
from app.services.booking_state import ALLOWED_TRANSITIONS, change_status, validate_transition

ALLOWED = [
    (S.PENDING, S.CONFIRMED),
    (S.PENDING, S.FAILED),
    (S.PENDING, S.CANCELLED),
    (S.FAILED, S.PENDING),
    (S.FAILED, S.CANCELLED),
]
FORBIDDEN = [pair for pair in itertools.product(S, S) if pair not in ALLOWED]


@pytest.mark.parametrize("current,target", ALLOWED)
def test_allowed_transitions_pass(current, target):
    validate_transition(current, target)


@pytest.mark.parametrize("current,target", FORBIDDEN)
def test_every_other_transition_is_rejected(current, target):
    with pytest.raises(InvalidStateTransition):
        validate_transition(current, target)


def test_confirmed_and_cancelled_are_terminal():
    assert ALLOWED_TRANSITIONS[S.CONFIRMED] == set()
    assert ALLOWED_TRANSITIONS[S.CANCELLED] == set()


def test_every_status_has_an_entry_in_the_transition_table():
    assert set(ALLOWED_TRANSITIONS) == set(S)


def test_change_status_updates_booking_and_logs_the_transition(caplog):
    booking = SimpleNamespace(id=7, status=S.PENDING)

    with caplog.at_level(logging.INFO, logger="app.booking"):
        change_status(booking, S.CONFIRMED, reason="test")

    assert booking.status == S.CONFIRMED
    record = next(r for r in caplog.records if r.message == "booking_status_changed")
    assert (record.booking_id, record.from_status, record.to_status) == (7, "PENDING", "CONFIRMED")


def test_change_status_leaves_booking_untouched_when_rejected():
    booking = SimpleNamespace(id=7, status=S.CONFIRMED)

    with pytest.raises(InvalidStateTransition):
        change_status(booking, S.CANCELLED, reason="test")

    assert booking.status == S.CONFIRMED
