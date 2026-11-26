"""Pydantic schemas mirroring the migration loader contract and API surface."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class CustomerUpsert(BaseModel):
    legal_name: str
    entity_type: str | None = None
    risk_classification: str | None = None
    partner: str | None = None
    region_tag: str | None = None
    onboarding_date: date | None = None
    assessment_cycle_anchor: date | None = None
    instance_url: str | None = None
    notification_emails: list[str] | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    legal_name: str
    entity_type: str | None
    risk_classification: str | None
    partner: str | None
    cycle_anchor_date: date | None
    instance_url: str | None


class GapIn(BaseModel):
    gap_no: str | None = None  # assigned from the per-customer sequence if absent
    cycle: str | None = None
    sat_domain: str | None = None
    control_ref: str
    control_description: str | None = None
    tier: str | None = None
    compliance_status: str | None = None
    gap_description: str | None = None
    severity: str | None = None
    target_quarter: str | None = None
    evidence_notes: str | None = None


class InitiativeIn(BaseModel):
    initiative_id: str | None = None  # assigned from the per-customer sequence if absent
    title: str
    domain: str | None = None
    phase: str | None = None
    priority: int | None = None
    owner: str | None = None
    team: str | None = None
    start_date: date | None = None
    target_end: date | None = None
    status: str = "Not Started"
    pct_done: float = 0
    budget_sar: float | None = None
    actuals_sar: float | None = None
    raci_r: str | None = None
    raci_a: str | None = None
    raci_c: str | None = None
    raci_i: str | None = None
    deliverables: str | None = None


class MappingIn(BaseModel):
    gap_no: str
    initiative_id: str


class RemediationImport(BaseModel):
    gaps: list[GapIn]
    initiatives: list[InitiativeIn]
    mappings: list[MappingIn]


class InitiativePatch(BaseModel):
    status: str | None = None
    pct_done: float | None = None
    actuals_sar: float | None = None
    target_end: date | None = None
    author: str | None = None
    comment: str | None = None


class CycleIn(BaseModel):
    label: str
    opens_on: date
    due_date: date


class CycleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    opens_on: date | None
    due_date: date | None
    state: str
    submitted_at: datetime | None
    submitted_by: str | None
