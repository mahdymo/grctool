import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.store import Store
from app.webhooks import init as init_webhooks
from app.webhooks import router


@pytest.fixture()
def client(tmp_path):
    store = Store(f"sqlite:///{tmp_path}/test.db")
    init_webhooks(store)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), store


def _signed_headers(payload: bytes, secret: str, *, forged: bool = False) -> dict:
    msg_id = "msg_test_1"
    timestamp = str(int(time.time()))
    secret_bytes = base64.b64decode(secret.removeprefix("whsec_"))
    signed_content = f"{msg_id}.{timestamp}.{payload.decode()}".encode()
    signature = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode()
    if forged:
        signature = base64.b64encode(b"forged-signature-value-padding-0000").decode()
    return {
        "svix-id": msg_id,
        "svix-timestamp": timestamp,
        "svix-signature": f"v1,{signature}",
    }


def test_forged_signature_rejected(client):
    http, _ = client
    payload = json.dumps({"type": "email.bounced", "data": {"to": ["victim@x.com"]}}).encode()
    headers = _signed_headers(payload, settings.resend_webhook_secret, forged=True)
    resp = http.post("/webhooks/resend", content=payload, headers=headers)
    assert resp.status_code == 401


def test_missing_signature_rejected(client):
    http, _ = client
    resp = http.post("/webhooks/resend", content=b"{}")
    assert resp.status_code == 401


def test_valid_bounce_suppresses_recipient(client):
    http, store = client
    payload = json.dumps(
        {"type": "email.bounced", "data": {"to": ["bounce@customer.com"]}}
    ).encode()
    headers = _signed_headers(payload, settings.resend_webhook_secret)
    resp = http.post("/webhooks/resend", content=payload, headers=headers)
    assert resp.status_code == 200
    assert store.is_suppressed("bounce@customer.com")
    assert not store.is_suppressed("other@customer.com")


def test_valid_complaint_suppresses_recipient(client):
    http, store = client
    payload = json.dumps(
        {"type": "email.complained", "data": {"to": ["angry@customer.com"]}}
    ).encode()
    headers = _signed_headers(payload, settings.resend_webhook_secret)
    resp = http.post("/webhooks/resend", content=payload, headers=headers)
    assert resp.status_code == 200
    assert store.is_suppressed("angry@customer.com")
