#!/usr/bin/env python3
"""IA SAT workbook -> CISO Assistant library YAML converter.

Reads the five assessment sheets of the IA Self-Assessment Tool (M&L risk)
workbook and emits one versioned CISO Assistant v2 library file per domain.

FRAMEWORK CONTENT ONLY. Assessment statuses, owners, dates and any other
customer data are never read by this tool — customer data import lives in
migration/ (spec §3.1: build-once framework library, reusable everywhere).

Mapping onto CISO Assistant's RequirementNode model (v4.3.4 — the model has
no dedicated implementation-guidance field, so the two verbatim guidance
columns are appended to `description` as labelled sections):

    Control #                  -> ref_id (stable key, spec §3.1)
    Control Description        -> description (verbatim, first section)
    Supporting Manual (Guide)  -> description, "**Implementation guide**" section
    Verification Control       -> description, "**Verification method**" section
    Required Evidence          -> typical_evidence (verbatim)
    Domain # / Domain          -> non-assessable parent requirement nodes (NCA only)

Usage:
    python sat_converter.py WORKBOOK.xlsm --out-dir ../libraries/ia-sat-ml/v1.0
    python sat_converter.py WORKBOOK.xlsm --validate-only
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
import yaml

LIBRARY_VERSION = 1  # CISO Assistant requires an integer library version
LIBRARY_LABEL = "v1.0"  # human-facing label used in file/dir names
LIBRARY_SLUG = "ia-sat-ml"
PROVIDER = "Insurance Authority (KSA)"
PACKAGER = "EhsanLab"

EXPECTED_COUNTS = {
    "nca-ecc": 112,
    "pdpl": 131,
    "sama-mvc": 17,
    "emerging-tech": 39,
    "it-resilience": 42,
}

EVIDENCE_COL = "Required Evidence"
GUIDE_COL = 'Supporting Manual "Implementation Guide"'
VERIFICATION_COL = "Verification Control"

# Per-sheet column maps. Headers are matched after normalisation (strip,
# collapse whitespace, casefold) because the workbook headers carry trailing
# spaces and typos ("Regulation / Frameowkr /Standard").
#
# code_col / description_col differ from the obvious columns on the NCA
# sheet: it has a dual layout where the real 112 controls (65 top-level +
# 47 sub-controls) live in "Control # 1" / "Control Description 1".
SHEETS: dict[str, dict] = {
    "nca-ecc": {
        "sheet": "NCA None CNIs Private Sector",
        "name": "IA SAT — Cybersecurity (NCA ECC, non-CNI private sector)",
        "ref_id": "NCA ECC",
        "code_col": "Control # 1",
        "description_col": "Control Description 1",
        "regulation_col": "Regulation",
        "hierarchy": "nca",
    },
    "pdpl": {
        "sheet": "Privacy",
        "name": "IA SAT — Privacy (SDAIA PDPL)",
        "ref_id": "SDAIA PDPL",
        "code_col": "Control #",
        "description_col": "Control Description",
        "regulation_col": "Regulation 1",
        "hierarchy": "flat",
        # The Privacy sheet mixes three sub-regulations whose bare article
        # numbers collide (PDPL art. 3 vs Transfer Regulation art. 3). Keep
        # PDPL codes native; prefix the others so ref_ids stay unique and
        # recognisable.
        "code_prefix_by_regulation": {
            "SDAIA (Regulation on Personal Data Transfer Outside the Kingdom)": "TR-",
        },
    },
    "sama-mvc": {
        "sheet": "SAMA MVC",
        "name": "IA SAT — SAMA Minimum Viable Controls",
        "ref_id": "SAMA MVC",
        "code_col": "Control #",
        "description_col": "Control Description",
        "regulation_col": "Regulation",
        "hierarchy": "flat",
    },
    "emerging-tech": {
        "sheet": "Emerging Tech",
        "name": "IA SAT — Emerging Technology",
        "ref_id": "IA Emerging Tech",
        "code_col": "Control #",
        "description_col": "Control Description",
        "regulation_col": "Regulation/Framework",
        "hierarchy": "flat",
    },
    "it-resilience": {
        "sheet": "IT Resilience",
        "name": "IA SAT — IT Resilience",
        "ref_id": "IA IT Resilience",
        "code_col": "Control #",
        "description_col": "Control Description",
        "regulation_col": "Regulation / Frameowkr /Standard",
        "hierarchy": "flat",
    },
}


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm_header(value: object) -> str:
    return _norm(value).casefold()


def _slug_code(code: str) -> str:
    return re.sub(r"[^a-z0-9.\-]+", "-", code.casefold()).strip("-")


@dataclass
class Control:
    code: str
    description: str
    evidence: str
    guide: str
    verification: str
    regulation: str
    domain_name: str = ""


@dataclass
class SheetResult:
    controls: list[Control] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def read_sheet(workbook, cfg: dict) -> SheetResult:
    ws = workbook[cfg["sheet"]]
    rows = list(ws.iter_rows(values_only=True))
    header = [_norm_header(h) for h in rows[0]]

    def col(name: str) -> int:
        key = _norm_header(name)
        if key not in header:
            raise ValueError(f"{cfg['sheet']}: column {name!r} not found in header")
        return header.index(key)

    c_code = col(cfg["code_col"])
    c_desc = col(cfg["description_col"])
    c_reg = col(cfg["regulation_col"])
    c_ev = col(EVIDENCE_COL)
    c_guide = col(GUIDE_COL)
    c_ver = col(VERIFICATION_COL)
    c_domain = col("Domain 1") if cfg["hierarchy"] == "nca" else None

    result = SheetResult()
    last_regulation = ""
    for row in rows[1:]:
        code = _norm(row[c_code]) if c_code < len(row) else ""
        if not code:
            continue  # blank spacer rows and sub-control continuation rows
        regulation = _norm(row[c_reg]) or last_regulation
        last_regulation = regulation
        prefix = cfg.get("code_prefix_by_regulation", {}).get(regulation, "")
        if prefix and not code.startswith(prefix):
            code = f"{prefix}{code}"
        control = Control(
            code=code,
            description=_norm(row[c_desc]),
            evidence=_norm(row[c_ev]),
            guide=_norm(row[c_guide]),
            verification=_norm(row[c_ver]),
            regulation=regulation,
            domain_name=_norm(row[c_domain]) if c_domain is not None else "",
        )
        if not control.description:
            result.warnings.append(f"{cfg['sheet']}: control {code} has no description")
        result.controls.append(control)

    codes = [c.code for c in result.controls]
    dupes = {c for c in codes if codes.count(c) > 1}
    if dupes:
        raise ValueError(f"{cfg['sheet']}: duplicate control codes: {sorted(dupes)}")
    return result


def compose_description(control: Control) -> str:
    parts = [control.description]
    if control.guide:
        parts.append(f"**Implementation guide**\n\n{control.guide}")
    if control.verification:
        parts.append(f"**Verification method**\n\n{control.verification}")
    return "\n\n".join(parts)


def short_name(control: Control) -> str:
    text = control.description
    return text if len(text) <= 80 else text[:77].rstrip() + "…"


def req_urn(slug: str, code: str) -> str:
    return f"urn:intuitem:risk:req_node:{LIBRARY_SLUG}-{slug}:{_slug_code(code)}"


def build_nodes(slug: str, cfg: dict, controls: list[Control]) -> list[dict]:
    root_urn = req_urn(slug, "root")
    nodes: list[dict] = [
        {
            "urn": root_urn,
            "assessable": False,
            "depth": 1,
            "ref_id": cfg["ref_id"],
            "name": cfg["name"],
        }
    ]

    def leaf(control: Control, depth: int, parent_urn: str) -> dict:
        return {
            "urn": req_urn(slug, control.code),
            "assessable": True,
            "depth": depth,
            "parent_urn": parent_urn,
            "ref_id": control.code,
            "name": short_name(control),
            "description": compose_description(control),
            "typical_evidence": control.evidence or None,
        }

    if cfg["hierarchy"] == "nca":
        # 3-segment codes (1-1-1) are controls under a domain (1-1); 4-segment
        # codes (2-2-1-1) are sub-controls under their 3-segment control when
        # it exists, otherwise directly under the domain.
        domain_urns: dict[str, str] = {}
        control_urns: dict[str, str] = {}
        for control in controls:
            segments = control.code.split("-")
            domain_ref = "-".join(segments[:2])
            if domain_ref not in domain_urns:
                domain_urns[domain_ref] = req_urn(slug, f"domain-{domain_ref}")
                nodes.append(
                    {
                        "urn": domain_urns[domain_ref],
                        "assessable": False,
                        "depth": 2,
                        "parent_urn": root_urn,
                        "ref_id": domain_ref,
                        "name": control.domain_name or domain_ref,
                    }
                )
            if len(segments) <= 3:
                parent = domain_urns[domain_ref]
                control_urns[control.code] = req_urn(slug, control.code)
            else:
                parent_code = "-".join(segments[:3])
                parent = control_urns.get(parent_code, domain_urns[domain_ref])
            nodes.append(leaf(control, 3 if len(segments) <= 3 else 4, parent))
    else:
        for control in controls:
            nodes.append(leaf(control, 2, root_urn))

    for node in nodes:
        if node.get("typical_evidence") is None:
            node.pop("typical_evidence", None)
    return nodes


def build_library(slug: str, cfg: dict, controls: list[Control]) -> dict:
    lib_urn = f"urn:intuitem:risk:library:{LIBRARY_SLUG}-{slug}"
    return {
        "convert_library_version": "v2",
        "urn": lib_urn,
        "locale": "en",
        "ref_id": f"{cfg['ref_id']} (IA SAT M&L)",
        "name": cfg["name"],
        "description": (
            f"Insurance Authority Self-Assessment Tool (Medium & Low risk entities) — "
            f"{cfg['name']}. Converted verbatim from the IA SAT workbook by the "
            f"grctool converter; do not edit by hand."
        ),
        "version": LIBRARY_VERSION,
        "provider": PROVIDER,
        "packager": PACKAGER,
        "objects": {
            "framework": {
                "urn": f"urn:intuitem:risk:framework:{LIBRARY_SLUG}-{slug}",
                "ref_id": cfg["ref_id"],
                "name": cfg["name"],
                "requirement_nodes": build_nodes(slug, cfg, controls),
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("workbook", type=Path, help="IA SAT workbook (.xlsm)")
    parser.add_argument("--out-dir", type=Path, help="output directory for library YAML")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="parse and validate without writing files",
    )
    args = parser.parse_args()

    workbook = openpyxl.load_workbook(args.workbook, keep_vba=True, read_only=True)
    exit_code = 0
    libraries: dict[str, dict] = {}

    for slug, cfg in SHEETS.items():
        result = read_sheet(workbook, cfg)
        expected = EXPECTED_COUNTS[slug]
        actual = len(result.controls)
        status = "OK" if actual == expected else "COUNT MISMATCH"
        print(f"{slug:15s} {cfg['sheet']:30s} controls={actual:4d} expected={expected:4d} {status}")
        for warning in result.warnings:
            print(f"  warning: {warning}")
        if actual != expected:
            exit_code = 1
        libraries[slug] = build_library(slug, cfg, result.controls)

    if args.validate_only:
        return exit_code

    if args.out_dir is None:
        parser.error("--out-dir is required unless --validate-only")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for slug, library in libraries.items():
        out = args.out_dir / f"{LIBRARY_SLUG}-{slug}-{LIBRARY_LABEL}.yaml"
        with out.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(library, fh, allow_unicode=True, sort_keys=False, width=100)
        print(f"wrote {out}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
