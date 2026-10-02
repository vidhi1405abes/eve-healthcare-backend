# EVE Healthcare - Diagnostic Test Booking API

Backend for booking diagnostic tests at diagnostic centres, with a **simulated** payment provider and an
**idempotent, signed payment webhook**. Built for the EVE Healthcare SDE Intern backend assignment.

**Stack:** Python 3.11+ · FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · PostgreSQL 16 · JWT (PyJWT) ·
bcrypt · pytest · Docker / docker-compose · Swagger UI (built into FastAPI).

**What it does**

| Area | Summary |
|---|---|
| Auth | Signup / login (JWT), validation, bcrypt hashing, rate-limited auth endpoints |
| Centres & tests | Public list/detail endpoints (pagination, location filter); admin-only create/update; `Numeric` prices |
| Bookings | Server-side price snapshot, future-date + "centre offers test" validation, state machine, owner-only access |
| Payments | `POST /payments/` simulated outcome, optional `Idempotency-Key`, retry after failure |
| Webhook | `POST /payments/webhook/` - HMAC-signed, idempotent, race-safe, respects the state machine |
| Ops | JSON logs + request id, error format, health check, Docker with healthchecks, migrations on startup |

Interactive docs: **http://localhost:8000/docs** (Swagger UI) and `/redoc`.
For a guided tour of the code and interview prep, read [ARCHITECTURE_WALKTHROUGH.md](ARCHITECTURE_WALKTHROUGH.md).

---

## 1. Run it locally

First create your env file (it holds secrets and is git-ignored):

```bash
# bash / macOS / Linux
cp .env.example .env
```
```powershell
# PowerShell (Windows)
Copy-Item .env.example .env
```
Edit `.env` and change `JWT_SECRET_KEY`, `WEBHOOK_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`.
Generate a strong secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

### Option A - Docker (recommended)

```powershell
docker compose up --build          # PowerShell and bash are identical
```
This starts PostgreSQL (with a healthcheck) and the API. The API container waits for the database to be healthy,
runs `alembic upgrade head`, then serves on port 8000.

```powershell
docker compose exec api python -m scripts.seed     # sample centres/tests/prices + the admin user
docker compose exec api pytest                     # run the test-suite inside the container
docker compose logs -f api                         # JSON logs
docker compose down                                # stop (add -v to also delete the database volume)
```

### Option B - without Docker for the API

You need Python 3.11+ and a PostgreSQL server. Easiest: run only the database with Docker
(`docker compose up -d db`; it matches the `eve:eve@localhost:5432` URLs in `.env.example`).
Or use your own PostgreSQL and edit `DATABASE_URL` / `TEST_DATABASE_URL` in `.env`.

```powershell
# PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt
alembic upgrade head                # create the tables
python -m scripts.seed              # sample data + admin user
uvicorn app.main:app --reload       # http://localhost:8000/docs
```
```bash
# bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

### Migrations

```bash
alembic upgrade head                                    # apply all migrations
alembic revision --autogenerate -m "describe change"    # after editing a model; ALWAYS review the generated file
alembic downgrade -1                                    # undo the last migration
```
One migration exists: `alembic/versions/0001_initial_schema.py`. A test (`test_migrations.py`) runs `alembic check`
and fails if a model changed without a migration.

### Seed data and the admin user

`python -m scripts.seed` is idempotent (safe to run again). It adds 6 tests, 5 centres with prices, and an admin
user taken from `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env`. If that email already exists as a normal user, it is
**promoted** to admin. Normal signups are never admins. (`users.is_admin` is the flag.)

### Run the tests

```bash
pytest            # same command in PowerShell and bash (inside Docker: docker compose exec api pytest)
```
Tests use a **real PostgreSQL** database named by `TEST_DATABASE_URL` (default `.../eve_test`). It is created
automatically, built with the Alembic migrations, and **truncated before every test**, so the test setup refuses to run
unless the database name ends with `_test`. See [Tests](#9-tests).

---

## 2. API endpoints

All errors share one shape: `{"error": {"code": "...", "message": "...", "request_id": "..."}}`.
Money (`price`, `amount`) is a decimal **string**, e.g. `"350.00"`, never a float.
Authenticated endpoints need `Authorization: Bearer <token>`.

| Method & path | Auth | Purpose | Main status codes |
|---|---|---|---|
| `POST /auth/signup` | - | Create account | 201, 409 duplicate email, 422, 429 |
| `POST /auth/login` | - | Get JWT | 200, 401, 422, 429 |
| `GET /auth/me` | user | Current user | 200, 401 |
| `GET /centres/?location=&limit=&offset=` | public | List centres | 200, 422 |
| `GET /centres/{id}` | public | Centre + its tests and prices | 200, 404, 422 |
| `POST /centres/` | admin | Create centre | 201, 401, 403, 409 |
| `PATCH /centres/{id}` | admin | Update centre | 200, 403, 404, 409 |
| `PUT /centres/{id}/tests/{test_id}` | admin | Offer a test / change price | 201 created, 200 updated, 403, 404 |
| `GET /tests/` | public | List tests | 200 |
| `POST /tests/`, `PATCH /tests/{id}` | admin | Create / update test | 201/200, 403, 409 |
| `POST /bookings/` | user | Book a test | 201, 400, 401, 404, 422 |
| `GET /bookings/?status=&limit=&offset=` | user | My bookings | 200 |
| `GET /bookings/{id}` | user | One of my bookings | 200, 404 |
| `POST /bookings/{id}/cancel` | user | Cancel | 200, 404, 409 |
| `POST /payments/` | user | Simulated payment (+ `Idempotency-Key`) | 201, 404, 409, 422 |
| `POST /payments/webhook/` | HMAC signature | Provider callback | 200, 401, 404, 422 |
| `GET /health` | - | Liveness + DB ping | 200, 503 |

List endpoints return `{"items": [...], "total": N, "limit": L, "offset": O}`; `limit` is 1-100 (default 20).

### Example requests

The examples below are real responses captured from the running app. They use bash `curl`; **on Windows PowerShell
`curl` is an alias of `Invoke-WebRequest`, so use `curl.exe` or `Invoke-RestMethod`** (a PowerShell version is shown
for login and the webhook).

**Signup and login**
```bash
curl -X POST http://localhost:8000/auth/signup -H "Content-Type: application/json" \
  -d '{"email":"patient@example.com","password":"a-strong-password"}'
# 201 {"id":2,"email":"patient@example.com","is_admin":false,"created_at":"2026-10-02T05:24:18.183660Z"}

curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" \
  -d '{"email":"patient@example.com","password":"a-strong-password"}'
# 200 {"access_token":"eyJhbGciOi...","token_type":"bearer","expires_in":3600}
```
```powershell
$login = Invoke-RestMethod -Method Post -Uri http://localhost:8000/auth/login -ContentType 'application/json' `
  -Body '{"email":"patient@example.com","password":"a-strong-password"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod -Uri http://localhost:8000/bookings/ -Headers $headers
```
Errors: duplicate signup -> `409 {"error":{"code":"email_already_registered",...}}`; wrong password -> `401 invalid_credentials`.

**Browse centres (public)**
```bash
curl "http://localhost:8000/centres/?location=delhi&limit=1"
# {"items":[{"id":1,"name":"CityCare Diagnostics","location":"Delhi"}],"total":2,"limit":1,"offset":0}

curl http://localhost:8000/centres/1
# {"id":1,"name":"CityCare Diagnostics","location":"Delhi","tests":[
#    {"test_id":1,"name":"Complete Blood Count","description":"Hemoglobin, RBC, WBC and platelet counts","price":"350.00"}, ...]}
```

**Admin: create a centre** (a normal user gets `403 {"error":{"code":"admin_required",...}}`)
```bash
curl -X POST http://localhost:8000/centres/ -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Lakeview Labs","location":"Noida"}'
# 201 {"id":6,"name":"Lakeview Labs","location":"Noida"}
curl -X PUT http://localhost:8000/centres/6/tests/1 -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"price":"399.00"}'
```

**Book a test** - note the client tried to send `amount`; it is ignored and the server price is used
```bash
curl -X POST http://localhost:8000/bookings/ -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"centre_id":1,"test_id":1,"appointment_datetime":"2030-01-15T09:30:00+00:00","amount":"1.00"}'
# 201 {"id":1,"user_id":2,"test_id":1,"centre_id":1,"appointment_datetime":"2030-01-15T09:30:00Z",
#      "amount":"350.00","status":"PENDING","created_at":"...","updated_at":"..."}
```
`appointment_datetime` must include a timezone (naive datetimes -> 422) and be in the future (else 400
`appointment_in_past`). A centre that does not offer the test -> 400 `test_not_offered`.

**Pay (simulated), with an idempotency key**
```bash
curl -X POST http://localhost:8000/payments/ -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: pay-attempt-1" -H "Content-Type: application/json" \
  -d '{"booking_id":1,"simulate_outcome":"PENDING"}'
# 201 {"id":1,"booking_id":1,"amount":"350.00","status":"PENDING",
#      "provider_reference":"pay_90e8d32d96d841f981fb7318bbc33b84","idempotency_key":"pay-attempt-1",...}
```
`simulate_outcome` is optional: `SUCCESS` (booking CONFIRMED), `FAILED` (booking FAILED), or `PENDING` (the provider
"will confirm later by webhook"). Without it the result is random with probability `PAYMENT_SUCCESS_RATE`
(default 0.8). Repeating the call with the **same** `Idempotency-Key` returns the same payment again, with the
response header `Idempotent-Replayed: true`. Paying a CONFIRMED / CANCELLED booking -> `409 booking_not_payable`
(`{"error":{"code":"booking_not_payable","message":"Booking is CONFIRMED and cannot be paid",...}}`).

**Webhook with a signature**

The provider signs the **raw request body** with HMAC-SHA256 using `WEBHOOK_SECRET` and sends the hex digest in
`X-Signature`. A helper builds a valid request for you (works in Docker too:
`docker compose exec api python -m scripts.sign_webhook ...`):

```bash
python -m scripts.sign_webhook --reference pay_90e8d32d96d841f981fb7318bbc33b84 --status SUCCESS --event-id evt_1
```
It prints the body, the signature and ready-to-paste commands:
```bash
curl -X POST http://localhost:8000/payments/webhook/ -H 'Content-Type: application/json' \
  -H 'X-Signature: bd805cc6ec8a7a38e30ec15ad6a34a7540c640d84e6c57b63a32462a98294155' \
  -d '{"event_id":"evt_1","provider_reference":"pay_90e8d32d96d841f981fb7318bbc33b84","status":"SUCCESS","timestamp":"2026-10-02T05:24:19.652713+00:00"}'
```
```powershell
$body = '{"event_id":"evt_1","provider_reference":"pay_90e8d32d96d841f981fb7318bbc33b84","status":"SUCCESS","timestamp":"2026-10-02T05:24:19.652713+00:00"}'
Invoke-RestMethod -Method Post -Uri http://localhost:8000/payments/webhook/ -ContentType 'application/json' `
  -Headers @{ 'X-Signature' = 'bd805cc6ec8a7a38e30ec15ad6a34a7540c640d84e6c57b63a32462a98294155' } -Body $body
```
(The signature above matches the example body only with the `WEBHOOK_SECRET` of the machine that produced it; run the
script yourself to get one for your secret. `--send http://localhost:8000` makes the script post it for you.)

Responses seen in the real run (same event twice, then a conflicting late event, then a bad signature):

| Request | Response |
|---|---|
| first delivery of `evt_demo_1` (SUCCESS) | `200 {"status":"processed","detail":"payment SUCCESS; booking CONFIRMED"}` |
| the same event again | `200 {"status":"already_processed"}` |
| a new `evt_demo_2` saying FAILED, after SUCCESS | `200 {"status":"ignored","detail":"payment is already SUCCESS; cannot become FAILED"}` |
| wrong / missing `X-Signature` | `401 {"error":{"code":"invalid_signature",...}}` |
| unknown `provider_reference` | `404 payment_not_found` |
| bad JSON / missing field / status `PENDING` / naive timestamp | `422 invalid_payload` |

After those 3 deliveries the database held **1** payment, **1** booking and **2** `webhook_events` rows.

---

## 3. Database schema

```mermaid
erDiagram
    USERS ||--o{ BOOKINGS : makes
    USERS ||--o{ PAYMENTS : pays
    CENTRES ||--o{ CENTRE_TESTS : offers
    DIAGNOSTIC_TESTS ||--o{ CENTRE_TESTS : "is offered via"
    CENTRES ||--o{ BOOKINGS : hosts
    DIAGNOSTIC_TESTS ||--o{ BOOKINGS : "is booked as"
    BOOKINGS ||--o{ PAYMENTS : "is paid by"
    PAYMENTS ||--o{ WEBHOOK_EVENTS : "is updated by"

    USERS {
        int id PK
        string email UK
        string hashed_password
        bool is_admin
        timestamptz created_at
    }
    CENTRES {
        int id PK
        string name
        string location "indexed, UK with name"
        timestamptz created_at
    }
    DIAGNOSTIC_TESTS {
        int id PK
        string name UK
        text description
        timestamptz created_at
    }
    CENTRE_TESTS {
        int id PK
        int centre_id FK
        int test_id FK
        numeric price "CHECK price >= 0"
    }
    BOOKINGS {
        int id PK
        int user_id FK "indexed"
        int test_id FK
        int centre_id FK
        timestamptz appointment_datetime
        numeric amount "price snapshot, CHECK >= 0"
        enum status "indexed"
        timestamptz created_at
        timestamptz updated_at
    }
    PAYMENTS {
        int id PK
        int booking_id FK "indexed"
        int user_id FK
        numeric amount "copied from booking"
        enum status
        string provider_reference UK
        string idempotency_key "UK with user_id"
        timestamptz created_at
        timestamptz updated_at
    }
    WEBHOOK_EVENTS {
        int id PK
        string event_id UK
        int payment_id FK "indexed"
        string status
        timestamptz event_timestamp
        enum outcome "APPLIED or IGNORED"
        text detail
        timestamptz received_at
    }
```

**Why the key constraints exist**

| Constraint | Reason |
|---|---|
| `users.email` unique index (stored lower-case) | No duplicate accounts, even when two signups race. |
| `centre_tests` UNIQUE `(centre_id, test_id)` | A centre has exactly one price per test; `PUT .../tests/{id}` updates instead of duplicating. |
| `centre_tests.price`, `bookings.amount`, `payments.amount` are `NUMERIC(10,2)` with `CHECK >= 0` | Exact money arithmetic; floats are never used (Python `Decimal`, JSON strings). |
| `bookings.amount` is a **snapshot** | Later price changes must not alter existing bookings (tested). |
| `bookings.status`, `payments.status` are PostgreSQL enums | The database rejects invalid states; the legal *transitions* live in one Python function. |
| Indexes on `bookings.user_id`, `bookings.status`, `payments.booking_id`, `payments.provider_reference`, `centres.location` | These are the columns used by list filters and the webhook lookup. |
| `payments.provider_reference` unique | The webhook finds a payment by it; it must identify exactly one payment. |
| `payments` UNIQUE `(user_id, idempotency_key)` | Client retries cannot create two payments. Scoped **per user** so one user's key can never collide with, or reveal, another user's payment. NULL keys never conflict. |
| `webhook_events.event_id` UNIQUE | The foundation of webhook idempotency (section 5). |
| Foreign keys everywhere, all timestamps `timestamptz` | Referential integrity; no naive-time bugs. |

---

## 4. Booking state machine

```mermaid
stateDiagram-v2
    [*] --> PENDING: booking created
    PENDING --> CONFIRMED: payment SUCCESS
    PENDING --> FAILED: payment FAILED
    PENDING --> CANCELLED: user cancels
    FAILED --> PENDING: user retries payment
    FAILED --> CANCELLED: user cancels
    CONFIRMED --> [*]
    CANCELLED --> [*]
```

| From | Allowed next states |
|---|---|
| `PENDING` | `CONFIRMED`, `FAILED`, `CANCELLED` |
| `FAILED` | `PENDING` (payment retry), `CANCELLED` |
| `CONFIRMED` | none (terminal) |
| `CANCELLED` | none (terminal) |

* **One rule, one place:** `validate_transition()` in `app/services/booking_state.py` is the only function that decides
  legality. Cancel, payment and webhook code all call `change_status()`, which calls it. Illegal moves raise
  `InvalidStateTransition` -> HTTP **409**.
* **Choice - failed payments are retryable.** A FAILED payment sets the booking to `FAILED`; paying again moves it back
  to `PENDING` and creates a **new** payment row (the failed one stays as history). The alternative (FAILED is terminal)
  would force the user to re-book after a card hiccup. To retry, use a *new* `Idempotency-Key`; replaying the old key
  returns the old failed payment.
* **Choice - a confirmed booking cannot be cancelled** (409), because cancelling it properly needs a refund flow,
  which is out of scope here.
* **Payments have their own tiny status** (`PENDING` -> `SUCCESS` | `FAILED`) and the webhook only ever moves a
  payment out of `PENDING`.

---

## 5. How idempotency is guaranteed

### Webhook (`app/services/webhook_service.py`)

Three mechanisms work together; each covers a gap the others leave.

1. **UNIQUE `webhook_events.event_id` (the real guarantee).** Every processed event leaves a row. The database itself
   refuses a second row with the same `event_id`, regardless of what the Python code does or how many servers run it.
2. **Same transaction.** The event row, the payment update and the booking update are committed together (one
   `commit()`). So "event recorded" and "state changed" are all-or-nothing: no event can be recorded without its effect, and
   no effect can happen without its event. If processing fails, the whole transaction rolls back and the provider's retry
   starts clean.
3. **`SELECT ... FOR UPDATE` on the payment, then the booking.** Row locks make concurrent events for one payment run
   one after another. Without them, a `SUCCESS` and a `FAILED` event arriving together could both read `PENDING` and both apply.

What happens, step by step, when **two identical webhooks arrive at the same moment**:

```mermaid
sequenceDiagram
    participant A as Request A
    participant B as Request B (same event_id)
    participant DB as PostgreSQL
    A->>DB: SELECT payment FOR UPDATE  (lock acquired)
    B->>DB: SELECT payment FOR UPDATE  (waits...)
    A->>DB: INSERT webhook_event(event_id=E)
    A->>DB: SELECT booking FOR UPDATE, update payment + booking
    A->>DB: COMMIT  (lock released)
    DB-->>B: lock acquired, sees the committed row
    B->>DB: INSERT webhook_event(event_id=E)
    DB-->>B: unique violation (23505)
    B->>DB: ROLLBACK
    Note over B: responds 200 {"status": "already_processed"}, changed nothing
```
Request A answers `processed`, B answers `already_processed`; exactly one state change, one event row.

Other rules in the same service:
* A webhook **never creates** a payment or booking; unknown `provider_reference` -> 404 (nothing stored, so the
  provider's retry works once the payment exists).
* **Out-of-order or conflicting events are recorded as `IGNORED`**, not applied, and logged as warnings:
  a late `FAILED` after `SUCCESS`, a `SUCCESS` for an already-failed payment, or an event for a booking the user already
  cancelled. The HTTP answer is still `200` so the provider stops retrying.
* **Signature:** `X-Signature` = hex HMAC-SHA256 of the raw body, compared with `hmac.compare_digest` (constant time).
  It is checked **before** the JSON is parsed, so unauthenticated callers learn nothing about validation rules.

> **Lock order matters (a real bug found by the concurrency test).** The first version inserted the event row *before*
> locking the payment. Because `webhook_events.payment_id` is a foreign key, that insert takes a shared lock on the
> payment row; two concurrent events then both held the shared lock and both waited to upgrade it to `FOR UPDATE` -
> PostgreSQL reported a **deadlock**. The fix is to lock the payment first and insert the event second. Lock order
> everywhere is: booking, or payment -> booking (the webhook), so no cycle can form.

**Provider retries are safe by design.** Because the endpoint is idempotent, a provider can redeliver as often as it likes
(and should, if it gets a 5xx or a timeout). Failed attempts are logged (`webhook_unknown_payment`,
`webhook_invalid_signature`, `webhook_ignored`) but not stored in a table, to keep the schema small - see "improve".

### Payments (`app/services/payment_service.py`)

* The booking row is locked (`FOR UPDATE`) while paying, so two simultaneous pay requests cannot both succeed:
  one gets 201, the others 409. (Tested with 6 concurrent requests.)
* With an `Idempotency-Key`, a repeat returns the original payment. The check happens **before** the "is the booking
  payable" check, otherwise a retry of a successful payment would fail with "already CONFIRMED". If two identical
  requests race on different bookings, the `UNIQUE (user_id, idempotency_key)` constraint catches the loser.
* Using the same key for a *different* booking -> `409 idempotency_key_reused`.

---

## 6. Important assumptions and trade-offs

* **Synchronous SQLAlchemy** (plain `def` endpoints, run in FastAPI's threadpool): simplest to read and explain; transactions
  and row locks are easy to reason about. Async would add complexity without benefit at this scale.
* **Services own the business rules, routers are thin.** Routers parse input, call one service function, return the result.
* **404, not 403, for other people's bookings** (and their payments). A 403 would confirm that the id exists. All booking
  queries are filtered by `user_id`, so someone else's booking is indistinguishable from a missing one. Admin-only
  endpoints do return 403 (the endpoint's existence is not a secret).
* **Status code choices:** 422 = the request is malformed (bad email, naive datetime, bad id format); 400 = well-formed but
  breaks a business rule (past appointment, centre does not offer the test); 404 = referenced centre/test/booking does not
  exist; 409 = conflicts with current state (duplicate email, illegal transition, double payment).
* **The webhook's `PENDING` simulation.** The spec says `POST /payments/` yields SUCCESS or FAILED. I additionally allow
  `simulate_outcome=PENDING` ("provider accepted it, will confirm via webhook") because otherwise the webhook could never
  change anything - every payment would already be final. The normal flow is still synchronous SUCCESS/FAILED.
* **`simulate_outcome` is a testing hook** and is exposed to every authenticated user. In production it would be removed
  or limited to non-production environments.
* **Cancelling while a payment is in flight** is allowed; if the provider later reports SUCCESS, the event is ignored and
  logged. A real system would trigger a refund here (not implemented).
* **Idempotency-key replay returns the *current* state** of the original payment (it may have changed via webhook),
  with status 201 and `Idempotent-Replayed: true`.
* **Webhook `timestamp`** must be timezone-aware and is stored but **not used for ordering**: ordering safety comes from the
  state machine, not from comparing clocks. There is no replay-window check on the timestamp (see "improve").
* **Rate limiting** is an in-memory sliding window per client IP on signup/login (default 10/min). It is per process
  and sees the proxy's IP behind a reverse proxy; a shared store would be needed in production.
* **No double-booking / slot-capacity checks:** the same user may book the same slot twice; centres have unlimited capacity.
* **Redis caching and Celery are deliberately left out.** Nothing here needs them: the centre list is cheap and indexed, and the
  simulated payment is instantaneous. Adding them would add moving parts (two more services, cache invalidation,
  task retries) with no measurable benefit, and the assignment prefers a small, well-designed solution.
* The `Test` model is called **`DiagnosticTest`** in code (table `diagnostic_tests`) so pytest does not mistake it for a test
  class; the API path is still `/tests/`.
* Passwords are limited to 72 bytes (a bcrypt limit) and validated for that.

---

## 7. What I would improve with more time

* **Real payment gateway:** create a gateway order/intent and rely on its webhooks; verify the provider's timestamp window to stop replay attacks; rotate webhook secrets.
* **Outbox pattern:** write "booking confirmed" notifications to an outbox table in the same transaction and publish them reliably.
* **Celery / background jobs:** retry failed webhook processing with backoff, expire stale `PENDING` payments, send e-mail/SMS.
* **Persist failed webhook attempts** (a `webhook_failures` table or dead-letter queue) for replay and alerting.
* **Redis:** cache the centre listing (invalidate on admin writes) and move the rate limiter there so it works across instances.
* **Refresh tokens**, logout/token revocation, e-mail verification, password reset, account lockout.
* **Double-booking and slot-capacity checks**, centre opening hours, rescheduling, refunds for cancelled paid bookings.
* **Audit log** of status changes (who/when/why) as a table instead of only logs.
* **Observability:** Prometheus metrics, OpenTelemetry traces, alerts on `webhook_ignored` / failed payments.
* **Security hardening:** secrets manager, CORS policy, request size limits, pagination caps per role, dependency scanning.
* **CI:** run pytest, `alembic check` and linting on every push; build the Docker image in CI.

---

## 8. Project structure

```
app/
  main.py            FastAPI app: middleware, error handlers, routers, /health
  api/               routers (thin) + deps.py (current user, admin check, pagination)
  core/              config, security (JWT, bcrypt, HMAC), logging, exceptions, middleware, rate limiter
  db/                SQLAlchemy base + session
  models/            tables (User, Centre, DiagnosticTest, CentreTest, Booking, Payment, WebhookEvent)
  schemas/           Pydantic request/response models
  services/          business rules: auth, catalog, booking_state (state machine), booking, payment, webhook
alembic/             migrations (0001_initial_schema)
scripts/             seed.py, sign_webhook.py
tests/               pytest suite (real PostgreSQL)
Dockerfile, docker-compose.yml, .env.example, requirements.txt
```

## 9. Tests

`pytest` runs **143 tests** (about 5 seconds): auth (incl. expired/forged tokens, rate limit), catalog and admin rules,
bookings, the state machine (every possible transition is checked), payments (incl. idempotency keys and concurrency),
the webhook (duplicates sent 3 times, 8 concurrent identical deliveries, conflicting events, bad signatures, unknown
payments, invalid payloads), DB constraints, migrations-in-sync, error format, request-id logging, OpenAPI, and the scripts.

Design of the test setup (`tests/conftest.py`): real PostgreSQL (row locks and unique-constraint races cannot be tested on
SQLite); schema built by running the real Alembic migration; tables truncated before every test; the setup refuses to run
on a database whose name does not end in `_test`.

Every edge case from the assignment has a test - see the checklist at the end of the delivery message and
`ARCHITECTURE_WALKTHROUGH.md`.

## 10. Verification status (honest notes)

* Everything was run against **PostgreSQL 16** with Python 3.12: the full test-suite (143 passing, repeated several times
  to look for flakiness), `alembic upgrade/downgrade/upgrade/check`, the seed script, and a manual end-to-end run against a
  live `uvicorn` process (the responses in section 2 come from it).
* I removed the row locks on purpose once to confirm the concurrency tests really fail without them (they did), then restored them.
* **Not executed:** the `Dockerfile` and `docker-compose.yml` could not be built or run where this was developed (no Docker
  daemon available). The compose file is syntactically valid YAML and its commands mirror what was run manually, but please run
  `docker compose up --build` once on your machine and tell me if anything needs adjusting. The image uses Python 3.11; the tests were run on 3.12.
