"""Control plane — customer registry, cycles, remediation, portfolio roll-up.

The only component holding cross-customer data (spec §2.1). Phase 0 surface:
REST API (service-token auth) + background scheduler (cycle notifications,
portfolio polling).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import router
from .config import settings
from .db import init_db

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = None
    if settings.scheduler_enabled:
        from .scheduler import build_scheduler

        scheduler = build_scheduler()
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(title="GRC Control Plane", docs_url=None, redoc_url=None,
              lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "control-plane"}
