from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import IdPath, Pagination, pagination, require_admin
from app.api.docs import error_responses
from app.db.session import get_db
from app.models import DiagnosticTest
from app.schemas.catalog import DiagnosticTestCreate, DiagnosticTestOut, DiagnosticTestUpdate
from app.schemas.common import Page
from app.services import catalog_service

router = APIRouter(prefix="/tests", tags=["tests"])


@router.get("/", response_model=Page[DiagnosticTestOut], summary="List diagnostic tests (public)", responses=error_responses(422))
def list_tests(page: Pagination = Depends(pagination), db: Session = Depends(get_db)) -> Page[DiagnosticTestOut]:
    items, total = catalog_service.list_tests(db, page.limit, page.offset)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/",
    response_model=DiagnosticTestOut,
    status_code=201,
    summary="Create a diagnostic test (admin)",
    dependencies=[Depends(require_admin)],
    responses=error_responses(401, 403, 409, 422),
)
def create_test(payload: DiagnosticTestCreate, db: Session = Depends(get_db)) -> DiagnosticTest:
    return catalog_service.create_test(db, payload.name, payload.description)


@router.patch(
    "/{test_id}",
    response_model=DiagnosticTestOut,
    summary="Update a diagnostic test (admin)",
    dependencies=[Depends(require_admin)],
    responses=error_responses(401, 403, 404, 409, 422),
)
def update_test(test_id: IdPath, payload: DiagnosticTestUpdate, db: Session = Depends(get_db)) -> DiagnosticTest:
    return catalog_service.update_test(db, test_id, payload.model_dump(exclude_none=True))
