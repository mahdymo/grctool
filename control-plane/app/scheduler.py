"""Background jobs: cycle notification triggers + portfolio roll-up (spec §3.3, §3.5).

- T-30 / T-7 before a cycle's due date: enqueue assessment kickoff/reminder
  emails to the email worker (spec §4.3).
- Every poll interval: pull compliance metrics from each registered customer
  instance's CISO Assistant API into portfolio_metrics (< 5 min roll-up
  latency target, spec §7).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from .db import SessionLocal
from .models import Cycle, Customer, PortfolioMetric
from .services import enqueue_email

logger = logging.getLogger(__name__)

DOMAIN_NAMES = {
    "nca-ecc": "Cybersecurity (NCA ECC)",
    "pdpl": "Privacy (SDAIA PDPL)",
    "sama-mvc": "SAMA MVC",
    "emerging-tech": "Emerging Tech",
    "it-resilience": "IT Resilience",
}


def check_cycle_notifications(today: date | None = None) -> int:
    """Enqueue T-30 kickoff / T-7 reminder emails. Returns jobs enqueued."""
    today = today or date.today()
    sent = 0
    with SessionLocal() as db:
        cycles = db.execute(
            select(Cycle).where(Cycle.state.in_(["scheduled", "open"]))
        ).scalars().all()
        for cycle in cycles:
            customer = db.get(Customer, cycle.customer_id)
            if customer is None or cycle.due_date is None:
                continue
            days_left = (cycle.due_date - today).days
            context = {
                "cycle": cycle.label,
                "customer_name": customer.legal_name,
                "due_date": cycle.due_date.isoformat(),
                "assessment_url": customer.instance_url or "",
                "recipient_name": "team",
            }
            # Recipients resolved from instance admin config in Phase 1;
            # Phase 0 sends to the registered consultant contact.
            recipients = customer.notification_emails or []
            if days_left <= 30 and "t30" not in (cycle.kickoff_sent or ""):
                _enqueue_to(recipients, "assessment_kickoff", cycle.label, context)
                cycle.kickoff_sent = (cycle.kickoff_sent or "") + "t30"
                sent += 1
            if days_left <= 7 and "t7" not in (cycle.kickoff_sent or ""):
                context["days_remaining"] = days_left
                _enqueue_to(recipients, "assessment_reminder", cycle.label, context)
                cycle.kickoff_sent = (cycle.kickoff_sent or "") + "t7"
                sent += 1
        db.commit()
    return sent


def _enqueue_to(recipients, event: str, entity_id: str, context: dict) -> None:
    for recipient in recipients or []:
        enqueue_email(
            {
                "event": event,
                "to": recipient,
                "entity_id": entity_id,
                "context": context,
            }
        )


def poll_portfolio_metrics() -> int:
    """Pull per-domain compliance from each instance API. Returns rows written."""
    written = 0
    with SessionLocal() as db:
        customers = db.execute(
            select(Customer).where(Customer.instance_url.isnot(None))
        ).scalars().all()
        for customer in customers:
            try:
                metrics = _fetch_instance_metrics(customer)
            except Exception:
                logger.exception("portfolio poll failed for %s", customer.legal_name)
                continue
            for metric in metrics:
                db.add(metric)
                written += 1
        db.commit()
    return written


def _fetch_instance_metrics(customer: Customer) -> list[PortfolioMetric]:
    """Compliance % per domain = compliant / (assessed − N/A) — pinned formula."""
    rows: list[PortfolioMetric] = []
    with httpx.Client(base_url=customer.instance_url.rstrip("/") + "/api", timeout=30) as client:
        # Instance API token is provisioned per instance (mTLS in prod, §6.2)
        assessments = client.get("/compliance-assessments/", params={"limit": 100}).json()
        for assessment in assessments.get("results", []):
            domain = _domain_from_name(assessment.get("name", ""))
            if domain is None:
                continue
            counts = {"compliant": 0, "partially_compliant": 0,
                      "non_compliant": 0, "not_applicable": 0}
            offset = 0
            while True:
                page = client.get(
                    "/requirement-assessments/",
                    params={"compliance_assessment": assessment["id"],
                            "limit": 200, "offset": offset},
                ).json()
                for ra in page["results"]:
                    result = ra.get("result")
                    if result in counts:
                        counts[result] += 1
                if not page.get("next"):
                    break
                offset += 200
            denominator = sum(counts.values()) - counts["not_applicable"]
            pct = round(100 * counts["compliant"] / denominator, 1) if denominator else 0.0
            rows.append(
                PortfolioMetric(
                    customer_id=customer.id,
                    domain=domain,
                    compliance_pct=pct,
                    compliant=counts["compliant"],
                    partially_compliant=counts["partially_compliant"],
                    non_compliant=counts["non_compliant"],
                    not_applicable=counts["not_applicable"],
                )
            )
    return rows


def _domain_from_name(assessment_name: str) -> str | None:
    for slug, label in DOMAIN_NAMES.items():
        if assessment_name.endswith(f"— {label}"):
            return label
    return None


def build_scheduler() -> AsyncIOScheduler:
    from .config import settings

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(check_cycle_notifications, "cron", hour=6, minute=0)
    scheduler.add_job(poll_portfolio_metrics, "interval",
                      seconds=settings.portfolio_poll_seconds)
    return scheduler
