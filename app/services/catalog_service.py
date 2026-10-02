from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Centre, CentreTest, DiagnosticTest


def _contains_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_centres(db: Session, limit: int, offset: int, location: str | None) -> tuple[list[Centre], int]:
    stmt = select(Centre)
    if location:
        stmt = stmt.where(Centre.location.ilike(_contains_pattern(location), escape="\\"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Centre.id).limit(limit).offset(offset)).all()
    return list(items), total


def get_centre(db: Session, centre_id: int) -> Centre:
    centre = db.get(Centre, centre_id)
    if centre is None:
        raise NotFoundError("Centre not found", code="centre_not_found")
    return centre


def get_centre_with_tests(db: Session, centre_id: int) -> Centre:
    stmt = (
        select(Centre)
        .where(Centre.id == centre_id)
        .options(selectinload(Centre.offerings).joinedload(CentreTest.test))
    )
    centre = db.scalars(stmt).first()
    if centre is None:
        raise NotFoundError("Centre not found", code="centre_not_found")
    return centre


def create_centre(db: Session, name: str, location: str) -> Centre:
    centre = Centre(name=name, location=location)
    db.add(centre)
    _commit_or_conflict(db, "A centre with this name and location already exists")
    return centre


def update_centre(db: Session, centre_id: int, changes: dict) -> Centre:
    centre = get_centre(db, centre_id)
    for field, value in changes.items():
        setattr(centre, field, value)
    _commit_or_conflict(db, "A centre with this name and location already exists")
    return centre


def list_tests(db: Session, limit: int, offset: int) -> tuple[list[DiagnosticTest], int]:
    total = db.scalar(select(func.count()).select_from(DiagnosticTest)) or 0
    items = db.scalars(select(DiagnosticTest).order_by(DiagnosticTest.id).limit(limit).offset(offset)).all()
    return list(items), total


def get_test(db: Session, test_id: int) -> DiagnosticTest:
    test = db.get(DiagnosticTest, test_id)
    if test is None:
        raise NotFoundError("Test not found", code="test_not_found")
    return test


def create_test(db: Session, name: str, description: str | None) -> DiagnosticTest:
    test = DiagnosticTest(name=name, description=description)
    db.add(test)
    _commit_or_conflict(db, "A test with this name already exists")
    return test


def update_test(db: Session, test_id: int, changes: dict) -> DiagnosticTest:
    test = get_test(db, test_id)
    for field, value in changes.items():
        setattr(test, field, value)
    _commit_or_conflict(db, "A test with this name already exists")
    return test


def set_price(db: Session, centre_id: int, test_id: int, price: Decimal) -> tuple[CentreTest, bool]:
    get_centre(db, centre_id)
    get_test(db, test_id)
    offering = db.scalar(select(CentreTest).where(CentreTest.centre_id == centre_id, CentreTest.test_id == test_id))
    created = offering is None
    if offering is None:
        offering = CentreTest(centre_id=centre_id, test_id=test_id, price=price)
        db.add(offering)
    else:
        offering.price = price
    _commit_or_conflict(db, "This test is already offered by the centre; retry to update its price")
    return offering, created


def _commit_or_conflict(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError(message)
