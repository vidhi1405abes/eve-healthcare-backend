from datetime import datetime, timedelta, timezone


def future_iso(days: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def past_iso(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def webhook_body(event_id: str, reference: str, status: str = "SUCCESS", **overrides) -> bytes:
    import json

    payload = {
        "event_id": event_id,
        "provider_reference": reference,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **overrides,
    }
    return json.dumps(payload).encode()


def signed_headers(body: bytes) -> dict[str, str]:
    from app.core.security import sign_webhook_body

    return {"X-Signature": sign_webhook_body(body), "Content-Type": "application/json"}
