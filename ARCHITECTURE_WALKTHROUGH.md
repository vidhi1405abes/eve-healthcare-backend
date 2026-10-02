# Architecture walkthrough (interview prep)

Plain-language tour of the code: where each requirement lives, what every file does, likely interview questions,
and small live changes with the exact files to edit.

## The one-minute picture

```
HTTP request
   |
   v
app/main.py  -- middleware (request id, request log line) -- error handlers
   |
   v
app/api/*.py        ROUTER: reads the request, checks who you are, calls ONE service function, returns the result
   |
   v
app/services/*.py   BUSINESS RULES: validation, state machine, locking, commits
   |
   v
app/models/*.py     TABLES (SQLAlchemy)  ->  PostgreSQL  (schema created by alembic/)
```

Rules I followed everywhere (say these in the interview):
1. **Routers are thin.** If you see an `if` about business rules in a router, it is in the wrong place.
2. **Every status change goes through `booking_state.change_status()`**, which calls the one `validate_transition()`.
3. **Services commit.** A request that raises an error never commits, so nothing is half-saved.
4. **Errors are exceptions** (`app/core/exceptions.py`) turned into one JSON shape in one place.
5. **Money is `Decimal` / `NUMERIC`**, never float. **The server decides amounts**, never the client.

---

## Where each requirement lives

| Requirement | Code | Tests |
|---|---|---|
| Signup / login / JWT / validation | `api/auth.py`, `services/auth_service.py`, `core/security.py`, `schemas/auth.py` | `tests/test_auth.py` |
| Current-user dependency, admin check | `api/deps.py` (`get_current_user`, `require_admin`) | `test_auth.py`, `test_catalog.py` (403 tests) |
| Centres, tests, prices (admin writes) | `models/centre.py`, `services/catalog_service.py`, `api/centres.py`, `api/tests.py` | `tests/test_catalog.py`, `test_database.py` |
| Pagination + location filter | `api/deps.py` (`pagination`), `schemas/common.py` (`Page`), `catalog_service.list_centres` | `test_catalog.py` |
| Booking + price snapshot | `services/booking_service.py`, `api/bookings.py`, `models/booking.py` | `tests/test_bookings.py` |
| State machine | `services/booking_state.py` | `tests/test_state_machine.py` |
| 404 for other users' bookings | `booking_service.get_booking` (query filters by `user_id`) | `test_bookings.py`, `test_payments.py` |
| Simulated payment + Idempotency-Key | `services/payment_service.py`, `api/payments.py`, `models/payment.py` | `tests/test_payments.py` |
| Webhook (signature, idempotency, locks) | `services/webhook_service.py`, `api/payments.py` (`payment_webhook`), `core/security.py`, `models/webhook_event.py` | `tests/test_webhook.py` |
| Webhook signing helper | `scripts/sign_webhook.py` | `tests/test_scripts.py` |
| Admin creation + seed data | `scripts/seed.py` | `tests/test_scripts.py` |
| Error format | `core/exceptions.py` | `tests/test_app.py` |
| JSON logs + request id | `core/logging.py`, `core/middleware.py` | `tests/test_app.py` |
| Rate limiting | `core/rate_limit.py`, used in `api/auth.py` | `test_auth.py` |
| Migrations | `alembic/versions/0001_initial_schema.py`, `alembic/env.py` | `tests/test_migrations.py` |
| Docker | `Dockerfile`, `docker-compose.yml` | (not run in the build environment) |

---

## File by file

### `app/main.py`
Creates the FastAPI app, adds the request-id middleware, registers the error handlers and the five routers, and defines
`GET /health` (does `SELECT 1`; returns 503 if the database is down). Logging is configured here at start-up.

### `app/core/`
* **`config.py`** - reads environment variables (and `.env`) into one `settings` object. `database_url`, `jwt_secret_key` and `webhook_secret` have no default, so the app will not start without them.
* **`security.py`** - `hash_password` / `verify_password` (bcrypt), `create_access_token` / `decode_access_token` (JWT with `exp`), `sign_webhook_body` / `verify_webhook_signature` (HMAC-SHA256, `hmac.compare_digest`). No database code.
* **`exceptions.py`** - `AppError` and subclasses (`NotFoundError` 404, `ConflictError` 409, ...). `register_exception_handlers` converts them to `{"error": {...}}`. It also strips the submitted `input` from 422 errors so a rejected password is never echoed back.
* **`logging.py`** - JSON formatter; every line includes the request id (from a context variable) and any `extra={...}` fields.
* **`middleware.py`** - gives each request an id (or uses the incoming `X-Request-ID`), logs one `request_completed` line, returns the id in a response header.
* **`rate_limit.py`** - small in-memory sliding-window limiter used as a dependency on signup/login.

### `app/db/`
* **`base.py`** - SQLAlchemy `Base` with a naming convention so constraint names are predictable in migrations.
* **`session.py`** - the engine and `get_db()`, which gives one session per request and closes it afterwards (closing an uncommitted session rolls it back).

### `app/models/`
`user.py`, `centre.py` (`Centre`, `DiagnosticTest`, `CentreTest`), `booking.py`, `payment.py`, `webhook_event.py`, plus `enums.py`
(`BookingStatus`, `PaymentStatus`, `WebhookOutcome`). Constraints (unique, check, foreign keys, indexes) are declared here - see README section 3.

### `app/schemas/`
Pydantic request/response shapes. Notable: `BookingCreate` has **no amount field**; `Price` allows at most 2 decimals and no negatives;
`WebhookPayload.status` only allows `SUCCESS`/`FAILED`; `Page[T]` is the pagination wrapper; ids use `PositiveId` (1..2,147,483,647)
so a huge id gives a clean 422 instead of a database overflow.

### `app/services/`
* **`auth_service.py`** - signup (lower-cases email; the unique index decides races) and authenticate (always runs one bcrypt check so timing does not reveal which emails exist).
* **`catalog_service.py`** - list/get/create/update centres and tests, `set_price` (upsert into `centre_tests`).
* **`booking_state.py`** - **the state machine.** `ALLOWED_TRANSITIONS` table + `validate_transition()` + `change_status()` (validate, set, log).
* **`booking_service.py`** - create (looks up the price, snapshots it, checks "offered" and "in the future"), list, get (owner-scoped), cancel. `get_booking(for_update=True)` takes a row lock.
* **`payment_service.py`** - locks the booking, handles `Idempotency-Key` replays, checks the booking is payable, creates the payment (amount copied from booking), applies SUCCESS/FAILED/PENDING.
* **`webhook_service.py`** - lock payment -> insert event -> lock booking -> apply or ignore -> commit. Duplicate = unique violation = `already_processed`.

### `app/api/`
`auth.py`, `centres.py`, `tests.py`, `bookings.py`, `payments.py` (payment **and** webhook), `deps.py` (current user, admin, pagination, `IdPath`),
`docs.py` (helper that documents error responses in Swagger).

### Other
* **`alembic/`** - `env.py` reads `DATABASE_URL` from the environment; `versions/0001_initial_schema.py` creates everything (and drops the enum types on downgrade).
* **`scripts/seed.py`** - sample data + admin; **`scripts/sign_webhook.py`** - builds a signed webhook request.
* **`tests/conftest.py`** - test database setup and shared fixtures (`client`, `db`, `user_headers`, `admin_headers`, `catalog`, `book`, `pay`).

---

## Likely interview questions

**1. What happens if two identical webhooks arrive at the same time?**
Both requests try to lock the same payment row (`SELECT ... FOR UPDATE`); one wins, the other waits. The winner inserts the
`webhook_events` row, updates the payment and booking, and commits. The loser then gets the lock, tries to insert the same `event_id`,
and the `UNIQUE` constraint rejects it, so it rolls back and answers `200 {"status":"already_processed"}`. Result: one event row, one state change.
Even if the lock were missing, the unique constraint alone would still stop the duplicate (I checked this by removing the lock in a test run); the lock is what protects against *different* events racing.

**2. How would you add a new booking status, e.g. `COMPLETED`?**
(a) Add it to `BookingStatus` in `models/enums.py`. (b) Add its row to `ALLOWED_TRANSITIONS` in `services/booking_state.py`, e.g. `CONFIRMED -> {COMPLETED}` and `COMPLETED: set()`. (c) Write a migration by hand: Alembic's autogenerate does **not** detect new PostgreSQL enum values, so use `op.execute("ALTER TYPE booking_status ADD VALUE 'COMPLETED'")` inside `with op.get_context().autocommit_block():`. (d) Update `tests/test_state_machine.py` (its `ALLOWED` list; the "every status has an entry" test fails until you do step b, which is the safety net). (e) Add an endpoint/service function that performs the transition via `change_status()`.

**3. Why 404 instead of 403 for someone else's booking?**
403 says "this exists but is not yours", which lets an attacker enumerate valid ids. Every booking query includes `Booking.user_id == current_user.id`, so another user's booking behaves exactly like a missing one. (Admin-only endpoints do return 403.)

**4. Why snapshot the price into `booking.amount`, and why never trust the client?**
The amount must be what the user was shown at booking time even if an admin later changes the price (there is a test for this). The client could send any number, so `BookingCreate` has no amount field at all; the server reads `CentreTest.price`. The payment's amount is copied from the booking the same way. Money is `NUMERIC(10,2)` / `Decimal`, because floats cannot represent values like 0.10 exactly.

**5. How do you stop a double payment?**
`payment_service` locks the booking row (`FOR UPDATE`) first, then checks the status inside that lock. After the first payment succeeds the booking is `CONFIRMED`, so the second request gets `409 booking_not_payable`. A test fires 6 concurrent payments with different idempotency keys and asserts exactly one 201 and five 409s (it fails if I remove the lock).

**6. What is the difference between the `Idempotency-Key` and the webhook `event_id`?**
Both make retries safe but for different callers. `Idempotency-Key` is chosen by our *client* on `POST /payments/`: same key -> same payment returned, no second charge (unique per user). `event_id` is chosen by the *provider* on the webhook: same id -> already processed. The first is stored on `payments`, the second on `webhook_events`.

**7. Why do you lock the payment *before* inserting the event row?**
I first did it the other way round and my concurrency test hit a PostgreSQL **deadlock**: inserting an event with a foreign key to `payments` takes a shared lock on the payment row; two concurrent events both hold it and both then wait to upgrade to `FOR UPDATE`. Locking the payment first (and always booking after payment) removes the cycle. The `README` section 5 has the details.

**8. A SUCCESS webhook arrives for a booking the user already cancelled. What happens? What would you do in production?**
`change_status(booking, CONFIRMED)` is illegal from `CANCELLED`, so the event is stored with outcome `IGNORED` and a warning is logged; the response is still 200 so the provider stops retrying. In production this means the customer was charged for a cancelled booking, so I would trigger an automatic refund and alert, ideally via an outbox/background job.

**9. How does the admin role work, and how would you extend it?**
`users.is_admin` boolean. `require_admin` (in `api/deps.py`) is a dependency on every write endpoint of centres/tests and returns 403 for others. The first admin comes from `ADMIN_EMAIL`/`ADMIN_PASSWORD` via `python -m scripts.seed`. For more roles I would replace the boolean with a `role` enum (or a roles table) and make `require_role("lab_manager")` a dependency factory.

**10. Why test against real PostgreSQL instead of SQLite, and how are tests isolated?**
Row locks (`FOR UPDATE`) and unique-constraint races are PostgreSQL behaviour; SQLite cannot test them. The test database is built by running the real Alembic migration (so migrations are tested too) and truncated before every test; the setup refuses to run unless the DB name ends with `_test`, so it can never wipe the dev database.

---

## Small live changes an interviewer might ask for

**A. "Allow users to cancel a CONFIRMED booking."**
* `app/services/booking_state.py`: `BookingStatus.CONFIRMED: {BookingStatus.CANCELLED}` in `ALLOWED_TRANSITIONS` (and update the docstring diagram).
* Tests (running the suite after the change shows exactly these 4 failures): `tests/test_state_machine.py` - add `(S.CONFIRMED, S.CANCELLED)` to `ALLOWED` (this fixes the parametrised `[CONFIRMED-CANCELLED]` case), change `test_confirmed_and_cancelled_are_terminal`, and change `test_change_status_leaves_booking_untouched_when_rejected` to use another illegal move such as `CANCELLED -> PENDING`; `tests/test_bookings.py` - rewrite `test_cancelling_a_confirmed_booking_returns_409`.
* Mention: the payment should be refunded (not built). The webhook and payment code need no change because they all use `change_status()`.

**B. "Appointments must be at least 2 hours in the future."**
* `app/core/config.py`: add `min_booking_lead_minutes: int = 120` (and a line in `.env.example`).
* `app/services/booking_service.py`, in `create_booking`: compare against `datetime.now(timezone.utc) + timedelta(minutes=settings.min_booking_lead_minutes)` instead of plain `now`.
* `tests/test_bookings.py`: add a test with an appointment 30 minutes ahead -> 400 `appointment_in_past` (maybe rename the code to `appointment_too_soon`).

**C. "Add an optional `notes` text to bookings."**
* `app/models/booking.py`: `notes: Mapped[str | None] = mapped_column(Text)`.
* `app/schemas/booking.py`: add `notes: str | None = Field(None, max_length=500)` to `BookingCreate` and `notes: str | None` to `BookingOut`.
* `app/services/booking_service.py` (`create_booking` parameter) and `app/api/bookings.py` (pass `payload.notes`).
* New migration: `alembic revision --autogenerate -m "add booking notes"` and review it. If you forget, `tests/test_migrations.py` fails.
* `tests/test_bookings.py`: one test that notes round-trip.

**D. "Reject webhook events whose timestamp is more than 5 minutes old (replay protection)."**
* `app/core/config.py`: `webhook_tolerance_seconds: int = 300`.
* `app/services/webhook_service.py`, at the top of `process_webhook` (before locking): if `now - payload.timestamp` is larger than the tolerance, raise `InvalidPayloadError` (422) or `BadRequestError` (400).
* `tests/test_webhook.py`: send an event with `timestamp` 10 minutes old (the `webhook_body(..., timestamp=...)` helper accepts overrides) and expect 4xx; existing tests keep passing because they use "now".

**Bonus: "Add a `name` filter to `GET /centres/`."**
`app/api/centres.py` (new `Query` parameter) -> `catalog_service.list_centres` (another `.where(Centre.name.ilike(...))`, reuse `_contains_pattern`) -> `tests/test_catalog.py`.
