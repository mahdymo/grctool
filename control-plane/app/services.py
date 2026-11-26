"""Business logic: sequences, remediation import, cycles, roll-up helpers."""

from __future__ import annotations

import json
from datetime import date

import redis
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    Cycle,
    CycleSnapshot,
    Customer,
    Gap,
    GapInitiativeMap,
    IdSequence,
    Initiative,
    StatusAuditLog,
)

# Rule (spec §3.4): only these statuses may create gaps.
GAP_ELIGIBLE_STATUSES = {"Non-Compliant", "Partially Compliant"}
INITIATIVE_STATUSES = {"Not Started", "In Progress", "Blocked", "Done", "Cancelled"}


def next_id(db: Session, customer_id: str, kind: str) -> str:
    """Per-customer, gapless, never-reused IDs (spec §11).

    Row-level lock on the counter makes concurrent allocation safe; the
    counter only ever moves forward.
    """
    seq = db.execute(
        select(IdSequence)
        .where(IdSequence.customer_id == customer_id, IdSequence.kind == kind)
        .with_for_update()
    ).scalar_one_or_none()
    if seq is None:
        seq = IdSequence(customer_id=customer_id, kind=kind, next_value=1)
        db.add(seq)
        db.flush()
    value = seq.next_value
    seq.next_value = value + 1
    db.flush()
    return f"{kind}-{value:03d}"


def bump_sequence_past(db: Session, customer_id: str, kind: str, used_id: str) -> None:
    """After importing a legacy ID (e.g. GAP-239), keep the sequence ahead."""
    try:
        number = int(used_id.split("-")[1])
    except (IndexError, ValueError):
        return
    seq = db.execute(
        select(IdSequence)
        .where(IdSequence.customer_id == customer_id, IdSequence.kind == kind)
        .with_for_update()
    ).scalar_one_or_none()
    if seq is None:
        seq = IdSequence(customer_id=customer_id, kind=kind, next_value=number + 1)
        db.add(seq)
    elif seq.next_value <= number:
        seq.next_value = number + 1
    db.flush()


def import_remediation(db: Session, customer: Customer, payload) -> dict:
    """Idempotent bulk upsert by gap_no / initiative_id (migration path)."""
    gaps_done = 0
    for gap_in in payload.gaps:
        if gap_in.compliance_status and gap_in.compliance_status not in GAP_ELIGIBLE_STATUSES:
            # spec §3.4: compliant controls never enter the gap register
            continue
        gap_no = gap_in.gap_no or next_id(db, customer.id, "GAP")
        gap = db.execute(
            select(Gap).where(Gap.customer_id == customer.id, Gap.gap_no == gap_no)
        ).scalar_one_or_none()
        fields = gap_in.model_dump(exclude={"gap_no"})
        if gap is None:
            gap = Gap(customer_id=customer.id, gap_no=gap_no, **fields)
            db.add(gap)
        else:
            for k, v in fields.items():
                setattr(gap, k, v)
        if gap_in.gap_no:
            bump_sequence_past(db, customer.id, "GAP", gap_no)
        gaps_done += 1
    db.flush()

    initiatives_done = 0
    for init_in in payload.initiatives:
        rem_id = init_in.initiative_id or next_id(db, customer.id, "REM")
        initiative = db.execute(
            select(Initiative).where(
                Initiative.customer_id == customer.id,
                Initiative.initiative_id == rem_id,
            )
        ).scalar_one_or_none()
        fields = init_in.model_dump(exclude={"initiative_id"})
        if initiative is None:
            initiative = Initiative(customer_id=customer.id, initiative_id=rem_id, **fields)
            db.add(initiative)
        else:
            for k, v in fields.items():
                setattr(initiative, k, v)
        if init_in.initiative_id:
            bump_sequence_past(db, customer.id, "REM", rem_id)
        initiatives_done += 1
    db.flush()

    mappings_done = 0
    for map_in in payload.mappings:
        gap = db.execute(
            select(Gap).where(Gap.customer_id == customer.id, Gap.gap_no == map_in.gap_no)
        ).scalar_one_or_none()
        initiative = db.execute(
            select(Initiative).where(
                Initiative.customer_id == customer.id,
                Initiative.initiative_id == map_in.initiative_id,
            )
        ).scalar_one_or_none()
        if gap is None or initiative is None:
            continue
        exists = db.execute(
            select(GapInitiativeMap).where(
                GapInitiativeMap.gap_id == gap.id,
                GapInitiativeMap.initiative_id == initiative.id,
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(GapInitiativeMap(gap_id=gap.id, initiative_id=initiative.id))
        mappings_done += 1

    db.commit()
    return {"gaps": gaps_done, "initiatives": initiatives_done, "mappings": mappings_done}


def audit_status_change(db: Session, customer_id: str, entity_type: str,
                        entity_ref: str, old: str | None, new: str | None,
                        author: str | None, comment: str | None) -> None:
    db.add(
        StatusAuditLog(
            customer_id=customer_id,
            entity_type=entity_type,
            entity_ref=entity_ref,
            old_status=old,
            new_status=new,
            author=author,
            comment=comment,
        )
    )


def submit_cycle(db: Session, cycle: Cycle, submitted_by: str,
                 snapshot_payload: dict) -> CycleSnapshot:
    """Lock the cycle and freeze state. No silent mutation afterwards (§3.3)."""
    if cycle.state in ("submitted", "locked"):
        raise ValueError(f"cycle {cycle.label} already {cycle.state}")
    snapshot = CycleSnapshot(cycle_id=cycle.id, payload=snapshot_payload)
    db.add(snapshot)
    cycle.state = "submitted"
    cycle.submitted_at = func.now()
    cycle.submitted_by = submitted_by
    audit_status_change(db, cycle.customer_id, "cycle", cycle.label,
                        "open", "submitted", submitted_by, None)
    db.commit()
    return snapshot


def enqueue_email(job: dict) -> None:
    client = redis.Redis.from_url(settings.redis_url)
    client.rpush(settings.email_queue_name, json.dumps(job))
    client.close()


def is_overdue(target_end: date | None, status: str) -> bool:
    """Overdue rule (spec §3.4): target end < today and not Done/Cancelled."""
    if target_end is None or status in ("Done", "Cancelled"):
        return False
    return target_end < date.today()
