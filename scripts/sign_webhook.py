import argparse
import json
import uuid
from datetime import datetime, timezone

import httpx

from app.core.security import sign_webhook_body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reference", required=True, help="provider_reference of the payment (from POST /payments/)")
    parser.add_argument("--status", choices=["SUCCESS", "FAILED"], default="SUCCESS")
    parser.add_argument("--event-id", default=None, help="default: a random id. Reuse one to simulate a duplicate.")
    parser.add_argument("--send", metavar="BASE_URL", help="also POST it, e.g. http://localhost:8000")
    args = parser.parse_args()

    payload = {
        "event_id": args.event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "provider_reference": args.reference,
        "status": args.status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    body = json.dumps(payload, separators=(",", ":"))
    signature = sign_webhook_body(body.encode())
    url = (args.send or "http://localhost:8000").rstrip("/") + "/payments/webhook/"

    print(f"X-Signature: {signature}")
    print(f"Body:        {body}\n")
    print("# bash")
    print(f"curl -X POST {url} -H 'Content-Type: application/json' -H 'X-Signature: {signature}' -d '{body}'\n")
    print("# PowerShell")
    print(f"$body = '{body}'")
    print(
        f"Invoke-RestMethod -Method Post -Uri {url} -ContentType 'application/json' "
        f"-Headers @{{ 'X-Signature' = '{signature}' }} -Body $body"
    )

    if args.send:
        response = httpx.post(url, content=body, headers={"Content-Type": "application/json", "X-Signature": signature})
        print(f"\nSent -> HTTP {response.status_code}: {response.text}")


if __name__ == "__main__":
    main()
