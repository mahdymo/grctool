"""Email job schema and idempotency keys (spec §4.4.5).

A job is a JSON dict on the Redis list `email:jobs`:

    {
      "event": "task_assignment",        # one of EVENTS
      "to": "owner@customer.com",
      "entity_id": "REM-014",            # what the event is about
      "context": {"title": "...", ...},  # template variables (escaped on render)
      "locale": "en",                    # template locale slot (Arabic later)
      "idempotency_key": "..."           # optional; derived if absent
    }

Idempotency key = event : entity_id : UTC date — duplicate triggers on the
same day for the same entity don't double-send.
"""

from __future__ import annotations

from datetime import datetime, timezone

EVENTS = {
    "user_invite",
    "password_reset",
    "assessment_kickoff",
    "assessment_reminder",
    "task_assignment",
    "cycle_submission",
}


def idempotency_key(job: dict) -> str:
    key = job.get("idempotency_key")
    if key:
        return key
    today = datetime.now(timezone.utc).date().isoformat()
    return f"{job['event']}:{job.get('entity_id', '-')}:{'-'.join(str(job['to']).lower().split())}:{today}"


def validate_job(job: dict) -> None:
    missing = {"event", "to"} - job.keys()
    if missing:
        raise ValueError(f"job missing fields: {missing}")
    if job["event"] not in EVENTS:
        raise ValueError(f"unknown event: {job['event']}")
