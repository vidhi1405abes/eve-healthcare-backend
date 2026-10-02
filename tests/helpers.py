from datetime import datetime, timedelta, timezone


def future_iso(days: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def past_iso(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
