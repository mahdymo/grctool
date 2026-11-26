"""Queue consumer: BLPOP jobs, render, send, log (spec §4.2).

Pipeline per job: validate -> idempotency check -> suppression check ->
render (escaped, text fallback) -> Resend with retry/backoff -> send log.
Final failure -> dead-letter queue + dead_letters table (admin alert hook).
"""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis

from .config import settings
from .jobs import idempotency_key, validate_job
from .renderer import Renderer
from .resend_client import ResendClient, SendFailed
from .store import Store

logger = logging.getLogger(__name__)


async def process_job(job: dict, store: Store, renderer: Renderer,
                      resend: ResendClient) -> str:
    """Returns the send-log status for the job."""
    validate_job(job)
    key = idempotency_key(job)
    recipient = job["to"]

    if store.already_sent(key):
        logger.info("duplicate suppressed by idempotency key %s", key)
        return "duplicate"
    if store.is_suppressed(recipient):
        store.record_send(key, job["event"], recipient, job.get("entity_id"),
                          None, "suppressed")
        logger.info("recipient %s suppressed (bounce/complaint)", recipient)
        return "suppressed"

    rendered = renderer.render(job["event"], job.get("locale", "en"),
                               job.get("context", {}))
    email_id = await resend.send(
        sender=job.get("from", settings.email_from_default),
        to=recipient,
        subject=rendered.subject,
        html=rendered.html,
        text=rendered.text,
        idempotency_key=key,
    )
    store.record_send(key, job["event"], recipient, job.get("entity_id"),
                      email_id, "sent")
    return "sent"


async def consumer_loop(store: Store, renderer: Renderer, resend: ResendClient,
                        stop: asyncio.Event) -> None:
    redis = aioredis.from_url(settings.redis_url)
    logger.info("email consumer listening on %s", settings.queue_name)
    while not stop.is_set():
        try:
            item = await redis.blpop(settings.queue_name, timeout=5)
        except Exception:
            logger.exception("redis error; retrying")
            await asyncio.sleep(5)
            continue
        if item is None:
            continue
        _, raw = item
        try:
            job = json.loads(raw)
            status = await process_job(job, store, renderer, resend)
            logger.info("job %s -> %s", job.get("event"), status)
        except SendFailed as exc:
            job_repr = raw.decode() if isinstance(raw, bytes) else str(raw)
            await redis.rpush(settings.dead_letter_queue, job_repr)
            store.dead_letter(job_repr, exc.attempts, str(exc))
            logger.error("job dead-lettered after %d attempts: %s",
                         exc.attempts, exc)
        except (ValueError, KeyError) as exc:
            logger.error("invalid job dropped: %s", exc)
        except Exception:
            logger.exception("unexpected error processing job")
    await redis.aclose()
