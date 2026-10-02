from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import auth, centres, tests
from app.core.config import settings
from app.core.exceptions import ServiceUnavailableError, register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import request_context_middleware
from app.db.session import get_db

configure_logging(settings.log_level)

DESCRIPTION = """
Backend for diagnostic test bookings with a **simulated** payment provider.

**Quick start:** `POST /auth/signup` -> `POST /auth/login` -> click **Authorize** and paste the token.

Errors always look like `{"error": {"code", "message", "request_id"}}`.
Prices and amounts are decimal strings (e.g. `"499.00"`), never floats.
"""

app = FastAPI(title="EVE Healthcare - Diagnostic Bookings API", version="1.0.0", description=DESCRIPTION)
app.middleware("http")(request_context_middleware)
register_exception_handlers(app)

app.include_router(auth.router)
app.include_router(centres.router)
app.include_router(tests.router)


@app.get("/health", tags=["health"], summary="Liveness/readiness check (also pings the database)")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise ServiceUnavailableError("Database is not reachable")
    return {"status": "ok"}
