from app.models import Booking, BookingStatus, DiagnosticTest
from tests.helpers import future_iso, past_iso


def test_create_booking_uses_server_side_price_and_starts_pending(book, user_headers, catalog):
    response = book(user_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["amount"] == "500.00"
    assert (body["centre_id"], body["test_id"]) == (catalog.centre_id, catalog.test_id)


def test_client_supplied_amount_is_ignored(book, user_headers):
    response = book(user_headers, amount="1.00")

    assert response.status_code == 201
    assert response.json()["amount"] == "500.00"


def test_price_change_after_booking_does_not_change_the_booking(client, book, user_headers, admin_headers, catalog):
    booking_id = book(user_headers).json()["id"]

    client.put(
        f"/centres/{catalog.centre_id}/tests/{catalog.test_id}", json={"price": "999.00"}, headers=admin_headers
    )

    assert client.get(f"/bookings/{booking_id}", headers=user_headers).json()["amount"] == "500.00"
    assert book(user_headers).json()["amount"] == "999.00"


def test_booking_requires_authentication(client, catalog):
    response = client.post(
        "/bookings/",
        json={"centre_id": catalog.centre_id, "test_id": catalog.test_id, "appointment_datetime": future_iso()},
    )

    assert response.status_code == 401


def test_booking_in_the_past_returns_400(book, user_headers):
    response = book(user_headers, appointment_datetime=past_iso())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "appointment_in_past"


def test_booking_with_a_naive_datetime_returns_422(book, user_headers):
    response = book(user_headers, appointment_datetime="2030-01-15T09:30:00")

    assert response.status_code == 422


def test_centre_that_does_not_offer_the_test_returns_400(book, user_headers, db):
    other_test = DiagnosticTest(name="Thyroid Profile")
    db.add(other_test)
    db.commit()

    response = book(user_headers, test_id=other_test.id)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "test_not_offered"


def test_unknown_centre_or_test_returns_404(book, user_headers):
    assert book(user_headers, centre_id=9999).json()["error"]["code"] == "centre_not_found"
    assert book(user_headers, test_id=9999).json()["error"]["code"] == "test_not_found"


def test_malformed_booking_requests_return_422(client, user_headers):
    for payload in [{}, {"centre_id": "abc", "test_id": 1, "appointment_datetime": future_iso()},
                    {"centre_id": 0, "test_id": 1, "appointment_datetime": future_iso()},
                    {"centre_id": 1, "test_id": 1, "appointment_datetime": "tomorrow"}]:
        assert client.post("/bookings/", json=payload, headers=user_headers).status_code == 422


def test_list_returns_only_my_bookings_newest_first_with_pagination(client, book, user_headers, other_user_headers):
    ids = [book(user_headers).json()["id"] for _ in range(3)]
    book(other_user_headers)

    body = client.get("/bookings/", params={"limit": 2}, headers=user_headers).json()

    assert body["total"] == 3
    assert [b["id"] for b in body["items"]] == [ids[2], ids[1]]


def test_list_can_filter_by_status(client, book, user_headers):
    first = book(user_headers).json()["id"]
    book(user_headers)
    client.post(f"/bookings/{first}/cancel", headers=user_headers)

    body = client.get("/bookings/", params={"status": "CANCELLED"}, headers=user_headers).json()

    assert body["total"] == 1 and body["items"][0]["id"] == first
    assert client.get("/bookings/", params={"status": "NOPE"}, headers=user_headers).status_code == 422


def test_get_booking_returns_404_for_someone_elses_booking(client, book, user_headers, other_user_headers):
    booking_id = book(user_headers).json()["id"]

    response = client.get(f"/bookings/{booking_id}", headers=other_user_headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "booking_not_found"


def test_get_nonexistent_and_invalid_booking_ids(client, user_headers):
    assert client.get("/bookings/9999", headers=user_headers).status_code == 404
    for bad_id in ["abc", "0", "-5", "99999999999999"]:
        assert client.get(f"/bookings/{bad_id}", headers=user_headers).status_code == 422


def test_bookings_endpoints_require_authentication(client):
    assert client.get("/bookings/").status_code == 401
    assert client.get("/bookings/1").status_code == 401
    assert client.post("/bookings/1/cancel").status_code == 401


def test_cancel_pending_booking(client, book, user_headers):
    booking_id = book(user_headers).json()["id"]

    response = client.post(f"/bookings/{booking_id}/cancel", headers=user_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_cancelling_twice_returns_409(client, book, user_headers):
    booking_id = book(user_headers).json()["id"]
    client.post(f"/bookings/{booking_id}/cancel", headers=user_headers)

    response = client.post(f"/bookings/{booking_id}/cancel", headers=user_headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state_transition"


def test_cancelling_a_confirmed_booking_returns_409(client, book, user_headers, db):
    booking_id = book(user_headers).json()["id"]
    db.query(Booking).update({"status": BookingStatus.CONFIRMED})
    db.commit()

    response = client.post(f"/bookings/{booking_id}/cancel", headers=user_headers)

    assert response.status_code == 409
    db.expire_all()
    assert db.get(Booking, booking_id).status == BookingStatus.CONFIRMED


def test_cannot_cancel_someone_elses_booking(client, book, user_headers, other_user_headers, db):
    booking_id = book(user_headers).json()["id"]

    response = client.post(f"/bookings/{booking_id}/cancel", headers=other_user_headers)

    assert response.status_code == 404
    db.expire_all()
    assert db.get(Booking, booking_id).status == BookingStatus.PENDING


def test_cancel_nonexistent_booking_returns_404(client, user_headers):
    assert client.post("/bookings/9999/cancel", headers=user_headers).status_code == 404
