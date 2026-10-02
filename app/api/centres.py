from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import IdPath, Pagination, pagination, require_admin
from app.api.docs import error_responses
from app.core.cache import cache
from app.db.session import get_db
from app.models import Centre
from app.schemas.catalog import (
    CentreCreate,
    CentreDetailOut,
    CentreOut,
    CentrePriceOut,
    CentreTestOut,
    CentreUpdate,
    PriceSet,
)
from app.schemas.common import Page
from app.services import catalog_service

router = APIRouter(prefix="/centres", tags=["centres"])


def _to_detail(centre: Centre) -> CentreDetailOut:
    offerings = sorted(centre.offerings, key=lambda o: o.test.name)
    return CentreDetailOut(
        id=centre.id,
        name=centre.name,
        location=centre.location,
        tests=[
            CentreTestOut(test_id=o.test_id, name=o.test.name, description=o.test.description, price=o.price)
            for o in offerings
        ],
    )


def _cached(key: str | None, build: Callable[[], BaseModel]) -> Response:
    cached = cache.get(key)
    if cached is not None:
        return Response(cached, media_type="application/json", headers={"X-Cache": "HIT"})
    body = build().model_dump_json()
    cache.set(key, body)
    return Response(body, media_type="application/json", headers={"X-Cache": "MISS"})


@router.get(
    "/",
    response_model=Page[CentreOut],
    summary="List centres (public)",
    description="Paginated. `location` does a case-insensitive 'contains' match, e.g. `del` matches `Delhi`. "
    "Cached in Redis (header `X-Cache: HIT` or `MISS`); admin writes invalidate the cache.",
    responses=error_responses(422),
)
def list_centres(
    location: str | None = Query(None, max_length=120, description="Filter by location", examples=["Delhi"]),
    page: Pagination = Depends(pagination),
    db: Session = Depends(get_db),
) -> Response:
    def build() -> Page[CentreOut]:
        items, total = catalog_service.list_centres(db, page.limit, page.offset, location)
        return Page(
            items=[CentreOut.model_validate(centre) for centre in items],
            total=total,
            limit=page.limit,
            offset=page.offset,
        )

    return _cached(cache.key("list", (location or "").lower(), page.limit, page.offset), build)


@router.get(
    "/{centre_id}",
    response_model=CentreDetailOut,
    summary="Get a centre with the tests it offers and their prices (public)",
    responses=error_responses(404, 422),
)
def get_centre(centre_id: IdPath, db: Session = Depends(get_db)) -> Response:
    return _cached(
        cache.key("detail", centre_id),
        lambda: _to_detail(catalog_service.get_centre_with_tests(db, centre_id)),
    )


@router.post(
    "/",
    response_model=CentreOut,
    status_code=201,
    summary="Create a centre (admin)",
    dependencies=[Depends(require_admin)],
    responses=error_responses(401, 403, 409, 422),
)
def create_centre(payload: CentreCreate, db: Session = Depends(get_db)) -> Centre:
    return catalog_service.create_centre(db, payload.name, payload.location)


@router.patch(
    "/{centre_id}",
    response_model=CentreOut,
    summary="Update a centre (admin)",
    dependencies=[Depends(require_admin)],
    responses=error_responses(401, 403, 404, 409, 422),
)
def update_centre(centre_id: IdPath, payload: CentreUpdate, db: Session = Depends(get_db)) -> Centre:
    return catalog_service.update_centre(db, centre_id, payload.model_dump(exclude_none=True))


@router.put(
    "/{centre_id}/tests/{test_id}",
    response_model=CentrePriceOut,
    summary="Offer a test at a centre / change its price (admin)",
    description="Creates the centre-test link with this price (201) or updates the price of an existing link (200). "
    "Changing a price does not affect bookings that already exist: they keep the amount they were created with.",
    dependencies=[Depends(require_admin)],
    responses=error_responses(401, 403, 404, 409, 422),
)
def set_test_price(
    centre_id: IdPath, test_id: IdPath, payload: PriceSet, response: Response, db: Session = Depends(get_db)
) -> CentrePriceOut:
    offering, created = catalog_service.set_price(db, centre_id, test_id, payload.price)
    response.status_code = 201 if created else 200
    return CentrePriceOut(centre_id=offering.centre_id, test_id=offering.test_id, price=offering.price)
