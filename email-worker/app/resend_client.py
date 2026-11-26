"""Resend REST client with retry/backoff (spec §4.4.3).

Honors rate limits (429 -> Retry-After), exponential backoff 2^n seconds,
max 5 attempts. The final failure raises SendFailed; the consumer moves the
job to the dead-letter queue and alerts admins. Never called synchronously
from user-facing flows — only from the queue consumer (spec §4.2).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class SendFailed(Exception):
    def __init__(self, message: str, attempts: int):
        super().__init__(message)
        self.attempts = attempts


class ResendClient:
    def __init__(self, api_key: str, base_url: str = "https://api.resend.com",
                 max_attempts: int = 5):
        self.max_attempts = max_attempts
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )

    async def send(self, *, sender: str, to: str, subject: str, html: str,
                   text: str, idempotency_key: str) -> str:
        """Returns the Resend email id. Raises SendFailed after max attempts."""
        payload = {
            "from": sender,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        }
        headers = {"Idempotency-Key": idempotency_key}
        last_error = "unknown"
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = await self.client.post("/emails", json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    return resp.json().get("id", "")
                if resp.status_code == 429 or resp.status_code >= 500:
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2 ** attempt
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning("resend attempt %d failed (%s), retry in %.0fs",
                                   attempt, resp.status_code, delay)
                    await asyncio.sleep(delay)
                    continue
                # 4xx other than 429: permanent, don't retry
                raise SendFailed(f"HTTP {resp.status_code}: {resp.text[:200]}", attempt)
            except httpx.TransportError as exc:
                last_error = str(exc)
                await asyncio.sleep(2 ** attempt)
        raise SendFailed(last_error, self.max_attempts)
