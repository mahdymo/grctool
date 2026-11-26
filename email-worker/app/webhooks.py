"""Resend webhook receiver with svix signature verification (spec §4.4.4).

Events handled: email.delivered, email.bounced, email.complained.
Bounces/complaints suppress the recipient until an admin reviews the
suppression record. Forged or missing signatures are rejected with 401 —
proven by the forged-signature test (AC 5).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from svix.webhooks import Webhook, WebhookVerificationError

from .config import settings
from .store import Store

logger = logging.getLogger(__name__)

router = APIRouter()
_store: Store | None = None


def init(store: Store) -> None:
    global _store
    _store = store


@router.post("/webhooks/resend")
async def resend_webhook(request: Request) -> dict:
    payload = await request.body()
    headers = {
        "svix-id": request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }
    try:
        event = Webhook(settings.resend_webhook_secret).verify(payload, headers)
    except WebhookVerificationError:
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    event_type = event.get("type", "")
    email = ""
    to_field = event.get("data", {}).get("to", [])
    if isinstance(to_field, list) and to_field:
        email = to_field[0]
    elif isinstance(to_field, str):
        email = to_field

    if event_type == "email.bounced" and email:
        _store.suppress(email, "bounced")
        logger.warning("recipient suppressed (bounce): %s", email)
    elif event_type == "email.complained" and email:
        _store.suppress(email, "complained")
        logger.warning("recipient suppressed (complaint): %s", email)
    elif event_type == "email.delivered":
        logger.info("delivered: %s", event.get("data", {}).get("email_id", ""))

    return {"received": True}
