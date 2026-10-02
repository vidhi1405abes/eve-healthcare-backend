import pytest
import redis

from app.core.cache import Cache, cache
from app.models import Centre


@pytest.fixture(autouse=True)
def redis_required():
    try:
        cache.client.ping()
    except Exception:
        pytest.skip("Redis is not available")


def _make_centre(db, name="Alpha", location="Delhi"):
    centre = Centre(name=name, location=location)
    db.add(centre)
    db.commit()
    return centre


def test_second_list_request_is_served_from_the_cache(client, db):
    _make_centre(db)

    first = client.get("/centres/")
    second = client.get("/centres/")

    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json() == second.json()


def test_cache_entries_are_separate_per_filter_and_page(client, db):
    _make_centre(db, "Alpha", "Delhi")
    _make_centre(db, "Beta", "Mumbai")

    client.get("/centres/?location=delhi")
    other_filter = client.get("/centres/?location=mumbai")
    other_page = client.get("/centres/?location=delhi&limit=5")

    assert other_filter.headers["X-Cache"] == "MISS"
    assert other_filter.json()["items"][0]["name"] == "Beta"
    assert other_page.headers["X-Cache"] == "MISS"
    assert client.get("/centres/?location=DELHI").headers["X-Cache"] == "HIT"


def test_cached_entries_expire(client, db):
    _make_centre(db)
    client.get("/centres/")

    keys = cache.client.keys("catalog:v*:list:*")

    assert len(keys) == 1
    assert 0 < cache.client.ttl(keys[0]) <= cache.ttl_seconds


def test_creating_a_centre_invalidates_the_list(client, db, admin_headers):
    _make_centre(db)
    client.get("/centres/")
    assert client.get("/centres/").headers["X-Cache"] == "HIT"

    client.post("/centres/", json={"name": "Gamma", "location": "Noida"}, headers=admin_headers)

    after = client.get("/centres/")
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["total"] == 2


def test_changing_a_price_invalidates_the_centre_detail(client, catalog, admin_headers):
    url = f"/centres/{catalog.centre_id}"
    assert client.get(url).headers["X-Cache"] == "MISS"
    assert client.get(url).headers["X-Cache"] == "HIT"

    client.put(f"{url}/tests/{catalog.test_id}", json={"price": "650.00"}, headers=admin_headers)

    after = client.get(url)
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["tests"][0]["price"] == "650.00"


def test_renaming_a_test_invalidates_the_centre_detail(client, catalog, admin_headers):
    url = f"/centres/{catalog.centre_id}"
    client.get(url)

    client.patch(f"/tests/{catalog.test_id}", json={"name": "CBC Renamed"}, headers=admin_headers)

    assert client.get(url).json()["tests"][0]["name"] == "CBC Renamed"


def test_not_found_responses_are_not_cached(client, db, admin_headers):
    assert client.get("/centres/1").status_code == 404

    created = client.post("/centres/", json={"name": "Alpha", "location": "Delhi"}, headers=admin_headers)

    assert created.json()["id"] == 1
    assert client.get("/centres/1").status_code == 200


def test_api_keeps_working_when_redis_is_down(client, db, monkeypatch):
    _make_centre(db)
    monkeypatch.setattr(cache, "client", redis.Redis(port=1, socket_connect_timeout=0.1, decode_responses=True))

    response = client.get("/centres/")

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert response.json()["total"] == 1


def test_cache_is_disabled_without_a_redis_url():
    disabled = Cache(None, 60)

    assert disabled.key("list") is None
    assert disabled.get("anything") is None
    disabled.set("anything", "value")
    disabled.invalidate_catalog()
