"""Control plane data model.

Owns what CISO Assistant lacks (spec §3.2, §3.4, §3.5, §11):
customer registry, gap register + initiatives + many-to-many mapping with
per-customer gapless GAP-###/REM-### sequences, assessment cycles with
submit-lock + append-only snapshots, status audit log, portfolio metrics.

Compliance statuses use the IA SAT enum verbatim; SAR budgets; dates stored
UTC (rendered Asia/Riyadh client-side).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    legal_name = Column(String(255), nullable=False, unique=True)
    entity_type = Column(String(64))  # Insurance / Reinsurance / Insurance Broker / Other
    risk_classification = Column(String(64))  # Small-Low / Medium / High (v1: M&L only)
    partner = Column(String(128), nullable=True)
    region_tag = Column(String(64), nullable=True)  # data residency (spec §6.3)
    onboarding_date = Column(Date, nullable=True)
    cycle_anchor_date = Column(Date, nullable=True)  # 6-month cycle anchor
    instance_url = Column(String(255), nullable=True)  # CISO Assistant instance
    notification_emails = Column(JSON, default=list)  # cycle notification recipients
    created_at = Column(DateTime(timezone=True), default=utcnow)

    gaps = relationship("Gap", back_populates="customer")
    initiatives = relationship("Initiative", back_populates="customer")
    cycles = relationship("Cycle", back_populates="customer")


class IdSequence(Base):
    """Per-customer, gapless, never-reused ID counters (spec §11)."""

    __tablename__ = "id_sequences"
    __table_args__ = (UniqueConstraint("customer_id", "kind"),)

    id = Column(Integer, primary_key=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False)
    kind = Column(String(8), nullable=False)  # GAP / REM
    next_value = Column(Integer, nullable=False, default=1)


class Gap(Base):
    __tablename__ = "gaps"
    __table_args__ = (UniqueConstraint("customer_id", "gap_no"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False)
    gap_no = Column(String(16), nullable=False)
    cycle = Column(String(32))
    sat_domain = Column(String(128))
    control_ref = Column(String(64), nullable=False)
    control_description = Column(Text)
    tier = Column(String(8))  # S/M/L carried verbatim (v1)
    compliance_status = Column(String(32))  # Non-Compliant / Partially Compliant
    gap_description = Column(Text)
    severity = Column(String(16))  # Critical/High/Medium/Low
    target_quarter = Column(String(16))
    evidence_notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    customer = relationship("Customer", back_populates="gaps")
    initiatives = relationship(
        "Initiative", secondary="gap_initiative_map", back_populates="gaps"
    )


class Initiative(Base):
    __tablename__ = "initiatives"
    __table_args__ = (UniqueConstraint("customer_id", "initiative_id"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False)
    initiative_id = Column(String(16), nullable=False)  # REM-###
    title = Column(String(500), nullable=False)
    domain = Column(String(128))
    phase = Column(String(32))  # Quick Wins / Foundation / Advanced / Optimization
    priority = Column(Integer)  # 1-5
    owner = Column(String(255))
    team = Column(String(255))
    start_date = Column(Date, nullable=True)
    target_end = Column(Date, nullable=True)
    status = Column(String(32), default="Not Started")  # spec §3.4 enum
    pct_done = Column(Float, default=0)
    budget_sar = Column(Float, nullable=True)
    actuals_sar = Column(Float, nullable=True)
    raci_r = Column(String(255))
    raci_a = Column(String(255))
    raci_c = Column(String(255))
    raci_i = Column(String(255))
    deliverables = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    customer = relationship("Customer", back_populates="initiatives")
    gaps = relationship("Gap", secondary="gap_initiative_map", back_populates="initiatives")


class GapInitiativeMap(Base):
    __tablename__ = "gap_initiative_map"
    __table_args__ = (UniqueConstraint("gap_id", "initiative_id"),)

    id = Column(Integer, primary_key=True)
    gap_id = Column(String(36), ForeignKey("gaps.id"), nullable=False)
    initiative_id = Column(String(36), ForeignKey("initiatives.id"), nullable=False)


class Cycle(Base):
    """Full SAT re-assessment every 6 months from the anchor (spec §3.3)."""

    __tablename__ = "cycles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False)
    label = Column(String(32), nullable=False)  # e.g. 2026-H2
    opens_on = Column(Date)
    due_date = Column(Date)
    state = Column(String(16), default="scheduled")  # scheduled/open/submitted/locked
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    submitted_by = Column(String(255), nullable=True)
    kickoff_sent = Column(String(8), default="")  # "" / "t30" / "t7" markers
    created_at = Column(DateTime(timezone=True), default=utcnow)

    customer = relationship("Customer", back_populates="cycles")
    snapshots = relationship("CycleSnapshot", back_populates="cycle")


class CycleSnapshot(Base):
    """Append-only: on submit, the assessment state is frozen (spec §3.3)."""

    __tablename__ = "cycle_snapshots"

    id = Column(Integer, primary_key=True)
    cycle_id = Column(String(36), ForeignKey("cycles.id"), nullable=False)
    taken_at = Column(DateTime(timezone=True), default=utcnow)
    payload = Column(JSON, nullable=False)  # statuses, counts, compliance %

    cycle = relationship("Cycle", back_populates="snapshots")


class StatusAuditLog(Base):
    """Append-only audit trail for status changes (spec §3.3, §6.1.8)."""

    __tablename__ = "status_audit_log"

    id = Column(Integer, primary_key=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False)
    entity_type = Column(String(32), nullable=False)  # gap / initiative / cycle
    entity_ref = Column(String(32), nullable=False)  # GAP-### / REM-### / cycle label
    old_status = Column(String(32))
    new_status = Column(String(32))
    author = Column(String(255))
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class PortfolioMetric(Base):
    """Cross-customer roll-up — the only cross-customer data (spec §2.1)."""

    __tablename__ = "portfolio_metrics"

    id = Column(Integer, primary_key=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False)
    domain = Column(String(64), nullable=False)
    compliance_pct = Column(Float)
    compliant = Column(Integer, default=0)
    partially_compliant = Column(Integer, default=0)
    non_compliant = Column(Integer, default=0)
    not_applicable = Column(Integer, default=0)
    gap_count = Column(Integer, default=0)
    captured_at = Column(DateTime(timezone=True), default=utcnow)
