import sys

from app.core.config import settings
from app.core.security import verify_webhook_signature
from app.models import Centre, CentreTest, DiagnosticTest, User
from scripts import seed, sign_webhook


def test_seed_is_idempotent(db):
    with seed.SessionLocal() as session:
        seed.seed_catalog(session)
        seed.seed_catalog(session)

    assert db.query(Centre).count() == len(seed.CENTRES)
    assert db.query(DiagnosticTest).count() == len(seed.TESTS)
    assert db.query(CentreTest).count() == sum(len(p) for p in seed.CENTRES.values())


def test_seed_creates_an_admin_and_promotes_an_existing_user(db, monkeypatch, client):
    monkeypatch.setattr(settings, "admin_email", "Boss@Example.com")
    monkeypatch.setattr(settings, "admin_password", "admin-password-123")

    with seed.SessionLocal() as session:
        seed.ensure_admin(session)
        seed.ensure_admin(session)
    admin = db.query(User).one()
    assert (admin.email, admin.is_admin) == ("boss@example.com", True)

    client.post("/auth/signup", json={"email": "later@example.com", "password": "password123"})
    monkeypatch.setattr(settings, "admin_email", "later@example.com")
    with seed.SessionLocal() as session:
        seed.ensure_admin(session)
    db.expire_all()
    assert db.query(User).filter_by(email="later@example.com").one().is_admin is True


def test_sign_webhook_script_prints_a_valid_signature(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["sign_webhook", "--reference", "pay_abc", "--status", "FAILED", "--event-id", "evt_9"]
    )

    sign_webhook.main()

    lines = capsys.readouterr().out.splitlines()
    signature = next(line for line in lines if line.startswith("X-Signature:")).split(": ", 1)[1]
    body = next(line for line in lines if line.startswith("Body:")).split(":", 1)[1].strip()
    assert '"event_id":"evt_9"' in body and '"status":"FAILED"' in body
    assert verify_webhook_signature(body.encode(), signature)
