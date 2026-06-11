"""Idempotent WebEx webhook self-registration for the MIGA bot.

Run:  python -m packages.webex_bot.register_webhook

Reads WEBEX_BOT_ACCESS_TOKEN and WEBEX_PUBLIC_URL (the ephemeral tunnel https base,
e.g. an ngrok / cloudflared URL), deletes any existing MIGA webhooks, then creates two
webhooks targeting <WEBEX_PUBLIC_URL>/webhooks/webex:
  - resource=messages,          event=created
  - resource=attachmentActions, event=created

Webhooks are named with a MIGA prefix so re-running is idempotent (old MIGA webhooks are
removed first). The script only manages webhooks whose name starts with that prefix.
"""
from __future__ import annotations

import logging
import os
import sys

import httpx

logger = logging.getLogger("miga.webex_bot.register_webhook")

WEBEX_API = os.getenv("WEBEX_API_BASE_URL", "https://webexapis.com/v1")
WEBHOOK_NAME_PREFIX = "MIGA"
TARGET_PATH = "/webhooks/webex"
RESOURCES: list[tuple[str, str]] = [
    ("messages", "created"),
    ("attachmentActions", "created"),
]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def list_webhooks(client: httpx.Client, token: str) -> list[dict]:
    resp = client.get(f"{WEBEX_API}/webhooks", headers=_headers(token))
    resp.raise_for_status()
    return resp.json().get("items", [])


def delete_miga_webhooks(client: httpx.Client, token: str) -> list[str]:
    """Delete existing webhooks whose name starts with the MIGA prefix. Returns ids."""
    deleted: list[str] = []
    for wh in list_webhooks(client, token):
        if str(wh.get("name", "")).startswith(WEBHOOK_NAME_PREFIX):
            wid = wh.get("id", "")
            resp = client.delete(f"{WEBEX_API}/webhooks/{wid}", headers=_headers(token))
            if resp.status_code < 400:
                deleted.append(wid)
                logger.info("deleted existing webhook %s (%s)", wid, wh.get("name"))
    return deleted


def create_webhooks(client: httpx.Client, token: str, target_url: str) -> list[str]:
    """Create the messages/created and attachmentActions/created webhooks. Returns ids."""
    created: list[str] = []
    for resource, event in RESOURCES:
        payload = {
            "name": f"{WEBHOOK_NAME_PREFIX}-{resource}-{event}",
            "targetUrl": target_url,
            "resource": resource,
            "event": event,
        }
        resp = client.post(f"{WEBEX_API}/webhooks", headers=_headers(token), json=payload)
        resp.raise_for_status()
        wid = resp.json().get("id", "")
        created.append(wid)
        logger.info("created webhook %s for %s/%s -> %s", wid, resource, event, target_url)
    return created


def register(token: str, public_url: str, client: httpx.Client | None = None) -> list[str]:
    """Idempotently (re)register the MIGA webhooks. Returns the new webhook ids."""
    target_url = public_url.rstrip("/") + TARGET_PATH
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        delete_miga_webhooks(client, token)
        return create_webhooks(client, token, target_url)
    finally:
        if owns_client:
            client.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    token = os.getenv("WEBEX_BOT_ACCESS_TOKEN", "")
    public_url = os.getenv("WEBEX_PUBLIC_URL", "")
    if not token:
        print("ERROR: WEBEX_BOT_ACCESS_TOKEN is not set", file=sys.stderr)
        return 1
    if not public_url:
        print("ERROR: WEBEX_PUBLIC_URL is not set (the ngrok/cloudflared https URL)", file=sys.stderr)
        return 1
    ids = register(token, public_url)
    print(f"Registered {len(ids)} MIGA webhooks at {public_url.rstrip('/')}{TARGET_PATH}: {ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
