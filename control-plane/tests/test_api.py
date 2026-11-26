from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import router
from app.db import get_db
from app.main import app
from app.models import Base
from app.services import is_overdue

TOKEN = {"Authorization": "Bearer test-token"}


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_customer(client) -> str:
    resp = client.post(
        "/api/customers/upsert",
        json={"legal_name": "Gulf Coverage", "entity_type": "Insurance Broker"},
        headers=TOKEN,
    )
    assert resp.status_code == 200
    return resp.json()["id"]


IMPORT_PAYLOAD = {
    "gaps": [
        {"gap_no": "GAP-001", "control_ref": "1-1-1", "compliance_status": "Non-Compliant",
         "severity": "High", "tier": "L", "target_quarter": "Q4 2026"},
        {"gap_no": "GAP-002", "control_ref": "30.3", "compliance_status": "Partially Compliant",
         "severity": "Medium"},
        # spec §3.4: compliant controls never enter the gap register
        {"gap_no": "GAP-003", "control_ref": "9.9", "compliance_status": "Compliant"},
    ],
    "initiatives": [
        {"initiative_id": "REM-001", "title": "Appoint cyber lead", "phase": "Foundation",
         "status": "In Progress", "owner": "Compliance Manager"},
        {"initiative_id": "REM-002", "title": "Draft policies", "phase": "Quick Wins"},
    ],
    "mappings": [
        {"gap_no": "GAP-001", "initiative_id": "REM-001"},
        {"gap_no": "GAP-002", "initiative_id": "REM-001"},
        {"gap_no": "GAP-002", "initiative_id": "REM-002"},
    ],
}


def test_auth_required(client):
    assert client.get("/api/customers").status_code == 401
    assert client.get("/api/customers", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_import_is_idempotent_and_skips_compliant(client):
    cid = _make_customer(client)
    first = client.post(f"/api/customers/{cid}/import/remediation",
                        json=IMPORT_PAYLOAD, headers=TOKEN).json()
    second = client.post(f"/api/customers/{cid}/import/remediation",
                         json=IMPORT_PAYLOAD, headers=TOKEN).json()
    assert first == second == {"gaps": 2, "initiatives": 2, "mappings": 3}

    stats = client.get(f"/api/customers/{cid}/stats", headers=TOKEN).json()
    assert stats["gap_count"] == 2
    assert stats["initiative_count"] == 2
    assert stats["mapping_count"] == 3


def test_gap_m2m_mapping(client):
    cid = _make_customer(client)
    client.post(f"/api/customers/{cid}/import/remediation", json=IMPORT_PAYLOAD, headers=TOKEN)
    gaps = client.get(f"/api/customers/{cid}/gaps", headers=TOKEN).json()
    gap2 = next(g for g in gaps if g["gap_no"] == "GAP-002")
    assert sorted(gap2["initiative_ids"]) == ["REM-001", "REM-002"]


def test_sequences_continue_after_import(client):
    """New IDs after migrating GAP-001..002 / REM-001..002 must not collide."""
    cid = _make_customer(client)
    client.post(f"/api/customers/{cid}/import/remediation", json=IMPORT_PAYLOAD, headers=TOKEN)
    # import a gap without an ID -> sequence must assign GAP-003
    payload = {"gaps": [{"control_ref": "4.2", "compliance_status": "Non-Compliant"}],
               "initiatives": [], "mappings": []}
    client.post(f"/api/customers/{cid}/import/remediation", json=payload, headers=TOKEN)
    gaps = client.get(f"/api/customers/{cid}/gaps", headers=TOKEN).json()
    assert "GAP-003" in {g["gap_no"] for g in gaps}


def test_initiative_status_change_is_audited(client):
    cid = _make_customer(client)
    client.post(f"/api/customers/{cid}/import/remediation", json=IMPORT_PAYLOAD, headers=TOKEN)
    resp = client.patch(
        f"/api/customers/{cid}/initiatives/REM-001",
        json={"status": "Done", "author": "consultant@ehsanlab.com", "comment": "verified"},
        headers=TOKEN,
    )
    assert resp.status_code == 200
    log = client.get(f"/api/customers/{cid}/audit-log", headers=TOKEN).json()
    assert log[0]["entity_ref"] == "REM-001"
    assert log[0]["old_status"] == "In Progress"
    assert log[0]["new_status"] == "Done"


def test_invalid_status_rejected(client):
    cid = _make_customer(client)
    client.post(f"/api/customers/{cid}/import/remediation", json=IMPORT_PAYLOAD, headers=TOKEN)
    resp = client.patch(f"/api/customers/{cid}/initiatives/REM-001",
                        json={"status": "Almost Done"}, headers=TOKEN)
    assert resp.status_code == 422


def test_overdue_rule():
    yesterday = date.today() - timedelta(days=1)
    tomorrow = date.today() + timedelta(days=1)
    assert is_overdue(yesterday, "In Progress")
    assert not is_overdue(yesterday, "Done")
    assert not is_overdue(yesterday, "Cancelled")
    assert not is_overdue(tomorrow, "In Progress")
    assert not is_overdue(None, "In Progress")


def test_cycle_submit_locks_and_snapshots(client):
    cid = _make_customer(client)
    cycle = client.post(
        f"/api/customers/{cid}/cycles",
        json={"label": "2026-H2", "opens_on": "2026-10-01", "due_date": "2026-12-31"},
        headers=TOKEN,
    ).json()
    resp = client.post(
        f"/api/cycles/{cycle['id']}/submit",
        json={"submitted_by": "consultant@ehsanlab.com",
              "snapshot": {"compliance_pct": 24.1}},
        headers=TOKEN,
    )
    assert resp.status_code == 200
    # second submit must conflict — no silent mutation (spec §3.3)
    resp2 = client.post(f"/api/cycles/{cycle['id']}/submit",
                        json={"submitted_by": "x"}, headers=TOKEN)
    assert resp2.status_code == 409
    snapshots = client.get(f"/api/cycles/{cycle['id']}/snapshots", headers=TOKEN).json()
    assert len(snapshots) == 1
    assert snapshots[0]["payload"]["compliance_pct"] == 24.1
