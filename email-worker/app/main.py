"""Email worker service entrypoint.

Owns all Resend communication (spec §4.2): a queue-consumer background task
plus the webhook receiver. Nothing else in the platform talks to Resend.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .consumer import consumer_loop
from .renderer import Renderer
from .resend_client import ResendClient
from .store import Store
from .webhooks import init as init_webhooks
from .webhooks import router as webhook_router

logging.basicConfig(level=logging.INFO)

_store: Store | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store
    _store = Store(settings.database_url)
    init_webhooks(_store)
    stop = asyncio.Event()
    renderer = Renderer(settings.template_dir)
    resend = ResendClient(settings.resend_api_key,
                          base_url=settings.resend_api_url,
                          max_attempts=settings.max_attempts)
    task = asyncio.create_task(consumer_loop(_store, renderer, resend, stop))
    yield
    stop.set()
    await asyncio.wait_for(task, timeout=15)


app = FastAPI(title="GRC Email Worker", docs_url=None, redoc_url=None,
              lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "email-worker"}
