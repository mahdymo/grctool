#!/usr/bin/env python3
"""Parse the customer SAT + remediation roadmap workbooks into staging JSON.

One-time migration tooling (spec §8) — NOT shipped to prod runtime.
Produces a normalized, deterministic staging file that the loaders
(load_ciso.py, load_control_plane.py) and reconcile.py consume, so parsing
is fully testable offline and the loaders stay thin.

Customer data flow: workbooks (gitignored source-data/) -> staging JSON
(gitignored staging/) -> running instance. Nothing customer-specific is
ever committed.

Usage:
    python parse_workbooks.py --sat ../source-data/IA-SAT-MnL-Risk-Workbook.xlsm \
        --roadmap ../source-data/IA-SAT-Remediation-Roadmap.xlsx \
        --out staging/gulf-coverage.json
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date, datetime
from pathlib import Path

import openpyxl

# Reuse the converter's sheet configs and normalisation so migrated statuses
# key onto exactly the ref_ids the library converter emits (incl. TR- prefixes).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "converter"))
from sat_converter import SHEETS, _norm, _norm_header  # noqa: E402

STATUS_MAP = {
    "Compliant": "compliant",
    "Partially Compliant": "partially_compliant",
    "Non-Compliant": "non_compliant",
    "N/A": "not_applicable",
}

NA_JUSTIFICATION_BACKFILL = "Migrated from legacy workbook — justification pending"

# Columns after the framework columns on every assessment sheet
STATUS_COL = "Compliant Status"
RECOMMENDATION_COL = "Recommendation for Implementation"
OWNER_COL = "Owner"
CLOSING_DATE_COL = "Closing Date"
MGMT_RESPONSE_COL = "Management Response"


def _iso(value: object) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = _norm(value)
    # Workbook dates are sometimes DD/MM/YYYY strings (e.g. assessment date)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text  # e.g. "Q4 2026" stays as-is (target quarter text)


def parse_assessment_statuses(workbook) -> tuple[dict, list[str]]:
    """Per-sheet control statuses keyed by library slug + ref_id."""
    statuses: dict[str, list[dict]] = {}
    warnings_out: list[str] = []
    for slug, cfg in SHEETS.items():
        ws = workbook[cfg["sheet"]]
        rows = list(ws.iter_rows(values_only=True))
        header = [_norm_header(h) for h in rows[0]]

        def col(name: str) -> int | None:
            key = _norm_header(name)
            return header.index(key) if key in header else None

        c_code = col(cfg["code_col"])
        c_reg = col(cfg["regulation_col"])
        c_status = col(STATUS_COL)
        c_rec = col(RECOMMENDATION_COL)
        c_owner = col(OWNER_COL)
        c_close = col(CLOSING_DATE_COL)
        c_resp = col(MGMT_RESPONSE_COL)

        entries: list[dict] = []
        last_regulation = ""
        for row in rows[1:]:
            code = _norm(row[c_code]) if c_code is not None and c_code < len(row) else ""
            if not code:
                continue
            regulation = _norm(row[c_reg]) or last_regulation
            last_regulation = regulation
            prefix = cfg.get("code_prefix_by_regulation", {}).get(regulation, "")
            if prefix and not code.startswith(prefix):
                code = f"{prefix}{code}"

            raw_status = _norm(row[c_status]) if c_status is not None else ""
            status = STATUS_MAP.get(raw_status)
            if raw_status and status is None:
                warnings_out.append(f"{cfg['sheet']}:{code}: unknown status {raw_status!r} -> not_assessed")

            recommendation = _norm(row[c_rec]) if c_rec is not None else ""
            na_justification = None
            if status == "not_applicable":
                # Workbooks record the N/A rationale in the recommendation
                # column; fall back to the backfill placeholder (spec §3.1
                # mandates a justification for every N/A).
                na_justification = recommendation or NA_JUSTIFICATION_BACKFILL

            entries.append(
                {
                    "ref_id": code,
                    "result": status or "not_assessed",
                    "na_justification": na_justification,
                    "recommendation": None if status == "not_applicable" else (recommendation or None),
                    "owner": _norm(row[c_owner]) if c_owner is not None else None,
                    "target_closing": _iso(row[c_close]) if c_close is not None else None,
                    "management_response": _norm(row[c_resp]) if c_resp is not None else None,
                }
            )
        statuses[slug] = entries
    return statuses, warnings_out


def parse_org_info(workbook) -> dict:
    ws = workbook["SAT Compliance Report"]
    info: dict[str, str] = {}
    # Labels sit in an arbitrary column (col F in the reference workbook) with
    # the value a few cells to the right — scan each row for a known label and
    # take the next non-empty cell as its value.
    labels = {
        "Company Name": "company_name",
        "Entity Type": "entity_type",
        "Organization Risk Classification": "risk_classification",
        "Assessment Date": "assessment_date",
    }
    for row in ws.iter_rows(values_only=True):
        if not row:
            continue
        cells = [c for c in row]
        for i, cell in enumerate(cells):
            text = _norm(cell)
            for prefix, field_name in labels.items():
                if text.startswith(prefix) and field_name not in info:
                    value = next(
                        (c for c in cells[i + 1 :] if c is not None and str(c).strip()),
                        None,
                    )
                    if value is not None:
                        info[field_name] = (
                            _iso(value) if field_name == "assessment_date" else _norm(value)
                        )
    return info


def _find_header_row(rows: list, first_cell: str) -> int:
    for i, row in enumerate(rows):
        if row and _norm(row[0]) == first_cell:
            return i
    raise ValueError(f"header row starting with {first_cell!r} not found")


def parse_roadmap(path: Path) -> dict:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    gap_rows = list(wb["Gap Register"].iter_rows(values_only=True))
    gaps = []
    for row in gap_rows[_find_header_row(gap_rows, "Gap No") + 1 :]:
        if not row or not row[0] or not str(row[0]).startswith("GAP"):
            continue
        gaps.append(
            {
                "gap_no": _norm(row[0]),
                "sat_domain": _norm(row[1]),
                "control_ref": _norm(row[2]),
                "control_description": _norm(row[3]),
                "tier": _norm(row[4]),
                "compliance_status": _norm(row[5]),
                "gap_description": _norm(row[6]),
                "severity": _norm(row[7]),
                "target_quarter": _norm(row[8]),
                "evidence_notes": _norm(row[10]) if len(row) > 10 else "",
            }
        )

    init_rows = list(wb["Initiatives"].iter_rows(values_only=True))
    initiatives = []
    for row in init_rows[_find_header_row(init_rows, "Initiative ID") + 1 :]:
        if not row or not row[0] or not str(row[0]).startswith("REM"):
            continue
        def num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        initiatives.append(
            {
                "initiative_id": _norm(row[0]),
                "title": _norm(row[1]),
                "domain": _norm(row[2]),
                "phase": _norm(row[3]),
                "priority": num(row[4]),
                "owner": _norm(row[5]),
                "team": _norm(row[6]),
                "start_date": _iso(row[7]),
                "target_end": _iso(row[8]),
                "status": _norm(row[9]),
                "pct_done": num(row[10]),
                "budget_sar": num(row[11]),
                "actuals_sar": num(row[12]),
                "raci_r": _norm(row[15]) if len(row) > 15 else "",
                "raci_a": _norm(row[16]) if len(row) > 16 else "",
                "raci_c": _norm(row[17]) if len(row) > 17 else "",
                "raci_i": _norm(row[18]) if len(row) > 18 else "",
                "deliverables": _norm(row[19]) if len(row) > 19 else "",
            }
        )

    map_rows = list(wb["Mapping"].iter_rows(values_only=True))
    mappings = []
    for row in map_rows[_find_header_row(map_rows, "Gap No") + 1 :]:
        if not row or not row[0] or not str(row[0]).startswith("GAP"):
            continue
        mappings.append({"gap_no": _norm(row[0]), "initiative_id": _norm(row[1])})

    return {"gaps": gaps, "initiatives": initiatives, "mappings": mappings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sat", type=Path, required=True, help="SAT workbook (.xlsm)")
    parser.add_argument("--roadmap", type=Path, required=True, help="remediation roadmap (.xlsx)")
    parser.add_argument("--out", type=Path, required=True, help="staging JSON output path")
    args = parser.parse_args()

    warnings.filterwarnings("ignore")  # openpyxl extension warnings on the .xlsm

    sat_wb = openpyxl.load_workbook(args.sat, keep_vba=True, read_only=True)
    statuses, parse_warnings = parse_assessment_statuses(sat_wb)
    org = parse_org_info(sat_wb)
    roadmap = parse_roadmap(args.roadmap)

    staging = {
        "customer": org,
        "statuses": statuses,
        **roadmap,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(staging, indent=2, ensure_ascii=False), encoding="utf-8")

    total = sum(len(v) for v in statuses.values())
    print(f"customer: {org.get('company_name')} ({org.get('entity_type')}, {org.get('risk_classification')})")
    for slug, entries in statuses.items():
        counts = {}
        for e in entries:
            counts[e["result"]] = counts.get(e["result"], 0) + 1
        print(f"  {slug:15s} {len(entries):4d} controls  {counts}")
    print(f"  gaps={len(roadmap['gaps'])} initiatives={len(roadmap['initiatives'])} mappings={len(roadmap['mappings'])}")
    for w in parse_warnings:
        print(f"  warning: {w}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
