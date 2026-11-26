"""REST API surface (all routes require the service token)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import require_token
from .db import get_db
from .models import (
    Cycle,
    Customer,
    Gap,
    GapInitiativeMap,
    Initiative,
    PortfolioMetric,
    StatusAuditLog,
)
from .schemas import (
    CycleIn,
    CycleOut,
    CustomerOut,
    CustomerUpsert,
    InitiativePatch,
    RemediationImport,
)
from .services import (
    INITIATIVE_STATUSES,
    audit_status_change,
    import_remediation,
    is_overdue,
    submit_cycle,
)

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


def _customer_or_404(db: Session, customer_id: str) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="customer not found")
    return customer


# ---------------- customers ----------------

@router.post("/customers/upsert", response_model=CustomerOut)
def upsert_customer(body: CustomerUpsert, db: Session = Depends(get_db)):
    customer = db.execute(
        select(Customer).where(Customer.legal_name == body.legal_name)
    ).scalar_one_or_none()
    fields = body.model_dump(exclude={"legal_name", "assessment_cycle_anchor"})
    anchor = body.assessment_cycle_anchor
    if customer is None:
        customer = Customer(legal_name=body.legal_name, cycle_anchor_date=anchor, **fields)
        db.add(customer)
    else:
        for k, v in fields.items():
            if v is not None:
                setattr(customer, k, v)
        if anchor is not None:
            customer.cycle_anchor_date = anchor
    db.commit()
    return customer


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(name: str | None = None, db: Session = Depends(get_db)):
    query = select(Customer)
    if name:
        query = query.where(Customer.legal_name.ilike(f"%{name}%"))
    return db.execute(query).scalars().all()


@router.get("/customers/{customer_id}/stats")
def customer_stats(customer_id: str, db: Session = Depends(get_db)):
    _customer_or_404(db, customer_id)
    gap_count = db.scalar(select(func.count(Gap.id)).where(Gap.customer_id == customer_id))
    initiative_count = db.scalar(
        select(func.count(Initiative.id)).where(Initiative.customer_id == customer_id)
    )
    mapping_count = db.scalar(
        select(func.count(GapInitiativeMap.id))
        .join(Gap, Gap.id == GapInitiativeMap.gap_id)
        .where(Gap.customer_id == customer_id)
    )
    by_severity = dict(
        db.execute(
            select(Gap.severity, func.count()).where(Gap.customer_id == customer_id)
            .group_by(Gap.severity)
        ).all()
    )
    initiatives = db.execute(
        select(Initiative).where(Initiative.customer_id == customer_id)
    ).scalars().all()
    overdue = [i.initiative_id for i in initiatives if is_overdue(i.target_end, i.status)]
    budget = sum(i.budget_sar or 0 for i in initiatives)
    actuals = sum(i.actuals_sar or 0 for i in initiatives)
    return {
        "gap_count": gap_count,
        "initiative_count": initiative_count,
        "mapping_count": mapping_count,
        "gaps_by_severity": by_severity,
        "overdue_initiatives": overdue,
        "budget_sar": budget,
        "actuals_sar": actuals,
    }


# ---------------- remediation ----------------

@router.post("/customers/{customer_id}/import/remediation")
def import_customer_remediation(customer_id: str, body: RemediationImport,
                                db: Session = Depends(get_db)):
    customer = _customer_or_404(db, customer_id)
    return import_remediation(db, customer, body)


@router.get("/customers/{customer_id}/gaps")
def list_gaps(customer_id: str, severity: str | None = None,
              db: Session = Depends(get_db)):
    _customer_or_404(db, customer_id)
    query = select(Gap).where(Gap.customer_id == customer_id)
    if severity:
        query = query.where(Gap.severity == severity)
    gaps = db.execute(query.order_by(Gap.gap_no)).scalars().all()
    return [
        {
            "gap_no": g.gap_no,
            "sat_domain": g.sat_domain,
            "control_ref": g.control_ref,
            "tier": g.tier,
            "compliance_status": g.compliance_status,
            "severity": g.severity,
            "target_quarter": g.target_quarter,
            "initiative_ids": [i.initiative_id for i in g.initiatives],
        }
        for g in gaps
    ]


@router.get("/customers/{customer_id}/initiatives")
def list_initiatives(customer_id: str, status: str | None = None,
                     db: Session = Depends(get_db)):
    _customer_or_404(db, customer_id)
    query = select(Initiative).where(Initiative.customer_id == customer_id)
    if status:
        query = query.where(Initiative.status == status)
    initiatives = db.execute(query.order_by(Initiative.initiative_id)).scalars().all()
    return [
        {
            "initiative_id": i.initiative_id,
            "title": i.title,
            "phase": i.phase,
            "priority": i.priority,
            "owner": i.owner,
            "start_date": i.start_date,
            "target_end": i.target_end,
            "status": i.status,
            "pct_done": i.pct_done,
            "budget_sar": i.budget_sar,
            "actuals_sar": i.actuals_sar,
            "overdue": is_overdue(i.target_end, i.status),
        }
        for i in initiatives
    ]


@router.patch("/customers/{customer_id}/initiatives/{initiative_id}")
def patch_initiative(customer_id: str, initiative_id: str, body: InitiativePatch,
                     db: Session = Depends(get_db)):
    _customer_or_404(db, customer_id)
    initiative = db.execute(
        select(Initiative).where(
            Initiative.customer_id == customer_id,
            Initiative.initiative_id == initiative_id,
        )
    ).scalar_one_or_none()
    if initiative is None:
        raise HTTPException(status_code=404, detail="initiative not found")
    if body.status is not None and body.status not in INITIATIVE_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(INITIATIVE_STATUSES)}")

    changed = body.model_dump(exclude_none=True, exclude={"author", "comment"})
    old_status = initiative.status
    for k, v in changed.items():
        setattr(initiative, k, v)
    if body.status is not None and body.status != old_status:
        audit_status_change(db, customer_id, "initiative", initiative_id,
                            old_status, body.status, body.author, body.comment)
    db.commit()
    return {"initiative_id": initiative_id, "status": initiative.status}


@router.get("/customers/{customer_id}/audit-log")
def audit_log(customer_id: str, db: Session = Depends(get_db)):
    _customer_or_404(db, customer_id)
    rows = db.execute(
        select(StatusAuditLog)
        .where(StatusAuditLog.customer_id == customer_id)
        .order_by(StatusAuditLog.created_at.desc())
        .limit(500)
    ).scalars().all()
    return [
        {
            "entity_type": r.entity_type,
            "entity_ref": r.entity_ref,
            "old_status": r.old_status,
            "new_status": r.new_status,
            "author": r.author,
            "comment": r.comment,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ---------------- cycles ----------------

@router.post("/customers/{customer_id}/cycles", response_model=CycleOut)
def create_cycle(customer_id: str, body: CycleIn, db: Session = Depends(get_db)):
    _customer_or_404(db, customer_id)
    cycle = Cycle(customer_id=customer_id, **body.model_dump())
    db.add(cycle)
    db.commit()
    return cycle


@router.get("/customers/{customer_id}/cycles", response_model=list[CycleOut])
def list_cycles(customer_id: str, db: Session = Depends(get_db)):
    _customer_or_404(db, customer_id)
    return db.execute(
        select(Cycle).where(Cycle.customer_id == customer_id).order_by(Cycle.due_date)
    ).scalars().all()


@router.post("/cycles/{cycle_id}/submit")
def submit(cycle_id: str, body: dict, db: Session = Depends(get_db)):
    cycle = db.get(Cycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="cycle not found")
    submitted_by = body.get("submitted_by", "unknown")
    snapshot_payload = body.get("snapshot", {})
    try:
        snapshot = submit_cycle(db, cycle, submitted_by, snapshot_payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"cycle": cycle.label, "state": cycle.state, "snapshot_id": snapshot.id}


@router.get("/cycles/{cycle_id}/snapshots")
def cycle_snapshots(cycle_id: str, db: Session = Depends(get_db)):
    cycle = db.get(Cycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="cycle not found")
    return [
        {"id": s.id, "taken_at": s.taken_at, "payload": s.payload}
        for s in cycle.snapshots
    ]


# ---------------- portfolio ----------------

@router.get("/portfolio/heatmap")
def portfolio_heatmap(db: Session = Depends(get_db)):
    """Customer × domain compliance from the latest captured metrics (§3.5)."""
    customers = db.execute(select(Customer)).scalars().all()
    result = []
    for customer in customers:
        latest: dict[str, PortfolioMetric] = {}
        metrics = db.execute(
            select(PortfolioMetric)
            .where(PortfolioMetric.customer_id == customer.id)
            .order_by(PortfolioMetric.captured_at.desc())
        ).scalars().all()
        for metric in metrics:
            latest.setdefault(metric.domain, metric)
        result.append(
            {
                "customer": customer.legal_name,
                "customer_id": customer.id,
                "domains": {
                    d: {
                        "compliance_pct": m.compliance_pct,
                        "gap_count": m.gap_count,
                        "captured_at": m.captured_at,
                    }
                    for d, m in latest.items()
                },
            }
        )
    return result
