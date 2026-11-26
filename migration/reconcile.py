#!/usr/bin/env python3
"""Reconcile migrated data against the source workbooks (spec §8, AC 3).

Computes the expected numbers from the staging JSON — per-domain status
counts, compliance % (pinned formula: Compliant / (assessed − N/A), N/A
excluded from the denominator), gap count, initiative count — and
optionally compares them against a live CISO Assistant instance and the
control plane. Exit code 1 on any mismatch.

Usage:
    python reconcile.py --staging staging/gulf-coverage.json \
        --url http://app.grc.localhost --token <PAT> --cycle 2026-H2 \
        --control-plane-url http://ops.grc.localhost --control-plane-token <TOKEN>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

DOMAIN_NAMES = {
    "nca-ecc": "Cybersecurity (NCA ECC)",
    "pdpl": "Privacy (SDAIA PDPL)",
    "sama-mvc": "SAMA MVC",
    "emerging-tech": "Emerging Tech",
    "it-resilience": "IT Resilience",
}


def expected_metrics(staging: dict) -> dict:
    domains = {}
    for slug, entries in staging["statuses"].items():
        counts = {"compliant": 0, "partially_compliant": 0, "non_compliant": 0,
                  "not_applicable": 0, "not_assessed": 0}
        for e in entries:
            counts[e["result"]] += 1
        assessed = sum(counts.values()) - counts["not_assessed"]
        denominator = assessed - counts["not_applicable"]
        compliance_pct = round(100 * counts["compliant"] / denominator, 1) if denominator else 0.0
        domains[slug] = {**counts, "assessed": assessed, "compliance_pct": compliance_pct}
    return {
        "domains": domains,
        "gap_count": len(staging["gaps"]),
        "initiative_count": len(staging["initiatives"]),
        "mapping_count": len(staging["mappings"]),
    }


def print_expected(expected: dict) -> None:
    print(f"{'domain':28s} {'C':>4} {'PC':>4} {'NC':>4} {'N/A':>4} {'unass':>6} {'compl%':>7}")
    for slug, m in expected["domains"].items():
        print(
            f"{DOMAIN_NAMES[slug]:28s} {m['compliant']:>4} {m['partially_compliant']:>4} "
            f"{m['non_compliant']:>4} {m['not_applicable']:>4} {m['not_assessed']:>6} "
            f"{m['compliance_pct']:>6.1f}%"
        )
    print(
        f"gaps={expected['gap_count']} initiatives={expected['initiative_count']} "
        f"mappings={expected['mapping_count']}"
    )


def check_live_ciso(expected: dict, url: str, token: str, cycle: str) -> list[str]:
    """Compare per-domain result counts on the live instance with expectations."""
    failures = []
    client = httpx.Client(
        base_url=url.rstrip("/") + "/api",
        headers={"Authorization": f"Token {token}"},
        timeout=60,
    )
    assessments = client.get("/compliance-assessments/", params={"limit": 200}).json()["results"]
    for slug, name in DOMAIN_NAMES.items():
        target = f"IA SAT M&L {cycle} — {name}"
        matches = [a for a in assessments if a.get("name") == target]
        if not matches:
            failures.append(f"{slug}: compliance assessment {target!r} not found")
            continue
        counts = {"compliant": 0, "partially_compliant": 0, "non_compliant": 0,
                  "not_applicable": 0, "not_assessed": 0}
        offset = 0
        while True:
            page = client.get(
                "/requirement-assessments/",
                params={"compliance_assessment__id": matches[0]["id"], "limit": 200, "offset": offset},
            ).json()
            for ra in page["results"]:
                result = ra.get("result") or "not_assessed"
                counts[result] = counts.get(result, 0) + 1
            if not page.get("next"):
                break
            offset += 200
        want = expected["domains"][slug]
        for key in ("compliant", "partially_compliant", "non_compliant", "not_applicable"):
            if counts.get(key, 0) != want[key]:
                failures.append(f"{slug}.{key}: live={counts.get(key, 0)} expected={want[key]}")
    return failures


def check_live_control_plane(expected: dict, url: str, token: str, customer_name: str) -> list[str]:
    failures = []
    client = httpx.Client(
        base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {token}"}, timeout=60
    )
    resp = client.get("/api/customers", params={"name": customer_name})
    resp.raise_for_status()
    customers = resp.json()
    if not customers:
        return [f"customer {customer_name!r} not found in control plane"]
    stats = client.get(f"/api/customers/{customers[0]['id']}/stats").json()
    if stats.get("gap_count") != expected["gap_count"]:
        failures.append(f"gap_count: live={stats.get('gap_count')} expected={expected['gap_count']}")
    if stats.get("initiative_count") != expected["initiative_count"]:
        failures.append(
            f"initiative_count: live={stats.get('initiative_count')} "
            f"expected={expected['initiative_count']}"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--url", help="CISO Assistant base URL (live check)")
    parser.add_argument("--token", help="CISO Assistant PAT")
    parser.add_argument("--cycle", default="2026-H2")
    parser.add_argument("--control-plane-url")
    parser.add_argument("--control-plane-token")
    args = parser.parse_args()

    staging = json.loads(args.staging.read_text(encoding="utf-8"))
    expected = expected_metrics(staging)
    print("== expected (from source workbooks) ==")
    print_expected(expected)

    failures: list[str] = []
    if args.url and args.token:
        print("\n== live CISO Assistant check ==")
        failures += check_live_ciso(expected, args.url, args.token, args.cycle)
    if args.control_plane_url and args.control_plane_token:
        print("== live control plane check ==")
        failures += check_live_control_plane(
            expected, args.control_plane_url, args.control_plane_token,
            staging["customer"].get("company_name"),
        )

    if failures:
        print("\nMISMATCHES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nreconciliation OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
