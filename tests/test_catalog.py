from decimal import Decimal

from app.models import Centre, CentreTest, DiagnosticTest


def _make_centres(db, specs):
    for name, location in specs:
        db.add(Centre(name=name, location=location))
    db.commit()


def test_list_centres_is_public_and_paginated(client, db):
    _make_centres(db, [(f"Centre {i}", "Delhi") for i in range(5)])

    response = client.get("/centres/", params={"limit": 2, "offset": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5 and body["limit"] == 2 and body["offset"] == 2
    assert [c["name"] for c in body["items"]] == ["Centre 2", "Centre 3"]


def test_list_centres_location_filter_is_case_insensitive_contains(client, db):
    _make_centres(db, [("A", "New Delhi"), ("B", "Mumbai"), ("C", "delhi cantt")])

    body = client.get("/centres/", params={"location": "DELHI"}).json()

    assert body["total"] == 2
    assert {c["name"] for c in body["items"]} == {"A", "C"}


def test_location_filter_treats_percent_as_literal_text(client, db):
    _make_centres(db, [("A", "Delhi"), ("B", "Mumbai")])

    assert client.get("/centres/", params={"location": "%"}).json()["total"] == 0


def test_list_centres_rejects_bad_pagination(client):
    assert client.get("/centres/", params={"limit": 0}).status_code == 422
    assert client.get("/centres/", params={"limit": 1000}).status_code == 422
    assert client.get("/centres/", params={"offset": -1}).status_code == 422


def test_get_centre_returns_tests_with_decimal_prices(client, catalog):
    response = client.get(f"/centres/{catalog.centre_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Apollo Diagnostics"
    assert body["tests"] == [
        {"test_id": catalog.test_id, "name": "Complete Blood Count", "description": "CBC", "price": "500.00"}
    ]


def test_get_unknown_centre_returns_404(client):
    response = client.get("/centres/9999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "centre_not_found"


def test_invalid_centre_ids_return_422_not_500(client):
    for bad_id in ["abc", "0", "-1", "99999999999999"]:
        assert client.get(f"/centres/{bad_id}").status_code == 422


def test_list_tests_is_public_and_paginated(client, db):
    db.add_all([DiagnosticTest(name=f"Test {i}") for i in range(3)])
    db.commit()

    body = client.get("/tests/", params={"limit": 2}).json()

    assert body["total"] == 3 and len(body["items"]) == 2


def test_admin_can_create_and_update_a_centre(client, admin_headers):
    created = client.post("/centres/", json={"name": " Lal Path ", "location": "Meerut"}, headers=admin_headers)
    assert created.status_code == 201
    assert created.json()["name"] == "Lal Path"

    updated = client.patch(f"/centres/{created.json()['id']}", json={"location": "Noida"}, headers=admin_headers)
    assert updated.status_code == 200
    assert updated.json() == {"id": created.json()["id"], "name": "Lal Path", "location": "Noida"}


def test_duplicate_centre_returns_409(client, admin_headers):
    payload = {"name": "Lal Path", "location": "Meerut"}
    client.post("/centres/", json=payload, headers=admin_headers)

    assert client.post("/centres/", json=payload, headers=admin_headers).status_code == 409


def test_non_admin_gets_403_on_every_admin_endpoint(client, user_headers, catalog):
    calls = [
        client.post("/centres/", json={"name": "X", "location": "Y"}, headers=user_headers),
        client.patch(f"/centres/{catalog.centre_id}", json={"name": "Z"}, headers=user_headers),
        client.put(f"/centres/{catalog.centre_id}/tests/{catalog.test_id}", json={"price": "1.00"}, headers=user_headers),
        client.post("/tests/", json={"name": "X"}, headers=user_headers),
        client.patch(f"/tests/{catalog.test_id}", json={"name": "Z"}, headers=user_headers),
    ]

    assert [r.status_code for r in calls] == [403] * 5
    assert calls[0].json()["error"]["code"] == "admin_required"


def test_unauthenticated_gets_401_on_admin_endpoints(client):
    assert client.post("/centres/", json={"name": "X", "location": "Y"}).status_code == 401
    assert client.post("/tests/", json={"name": "X"}).status_code == 401


def test_admin_update_of_unknown_centre_returns_404(client, admin_headers):
    assert client.patch("/centres/9999", json={"name": "X"}, headers=admin_headers).status_code == 404


def test_admin_can_create_and_update_a_test(client, admin_headers):
    created = client.post("/tests/", json={"name": "Lipid Profile", "description": "Cholesterol"}, headers=admin_headers)
    assert created.status_code == 201

    updated = client.patch(f"/tests/{created.json()['id']}", json={"description": "Updated"}, headers=admin_headers)
    assert updated.json()["description"] == "Updated"

    assert client.post("/tests/", json={"name": "Lipid Profile"}, headers=admin_headers).status_code == 409


def test_admin_sets_price_creating_then_updating_the_link(client, admin_headers, db):
    centre = Centre(name="C", location="L")
    test = DiagnosticTest(name="T")
    db.add_all([centre, test])
    db.commit()
    url = f"/centres/{centre.id}/tests/{test.id}"

    first = client.put(url, json={"price": "499.99"}, headers=admin_headers)
    second = client.put(url, json={"price": "550.00"}, headers=admin_headers)

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["price"] == "550.00"
    assert db.query(CentreTest).count() == 1


def test_price_is_stored_exactly_as_decimal(client, admin_headers, db):
    centre, test = Centre(name="C", location="L"), DiagnosticTest(name="T")
    db.add_all([centre, test])
    db.commit()

    client.put(f"/centres/{centre.id}/tests/{test.id}", json={"price": "0.10"}, headers=admin_headers)

    db.expire_all()
    assert db.query(CentreTest).one().price == Decimal("0.10")


def test_invalid_prices_return_422(client, admin_headers, catalog):
    url = f"/centres/{catalog.centre_id}/tests/{catalog.test_id}"
    for bad in ["-1", "10.555", "abc", "99999999999.00", None]:
        assert client.put(url, json={"price": bad}, headers=admin_headers).status_code == 422


def test_price_for_unknown_centre_or_test_returns_404(client, admin_headers, catalog):
    assert client.put(f"/centres/9999/tests/{catalog.test_id}", json={"price": "1"}, headers=admin_headers).status_code == 404
    assert client.put(f"/centres/{catalog.centre_id}/tests/9999", json={"price": "1"}, headers=admin_headers).status_code == 404
