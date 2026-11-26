#!/usr/bin/env python3
"""Load migrated gaps/initiatives/mappings into the control plane.

One-time migration tooling (spec §8) — idempotent: the control plane upserts
by gap_no / initiative_id, so re-running never duplicates records.

Usage:
    python load_control_plane.py --url http://ops.grc.localhost \
        --token <CONTROL_PLANE_TOKEN> --staging staging/gulf-coverage.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--staging", type=Path, required=True)
    args = parser.parse_args()

    staging = json.loads(args.staging.read_text(encoding="utf-8"))
    customer = staging["customer"]

    client = httpx.Client(
        base_url=args.url.rstrip("/"),
        headers={"Authorization": f"Bearer {args.token}"},
        timeout=60,
    )

    resp = client.post(
        "/api/customers/upsert",
        json={
            "legal_name": customer.get("company_name"),
            "entity_type": customer.get("entity_type"),
            "risk_classification": customer.get("risk_classification"),
            "assessment_cycle_anchor": customer.get("assessment_date"),
        },
    )
    resp.raise_for_status()
    customer_id = resp.json()["id"]
    print(f"customer upserted: {customer.get('company_name')} -> {customer_id}")

    resp = client.post(
        f"/api/customers/{customer_id}/import/remediation",
        json={
            "gaps": staging["gaps"],
            "initiatives": staging["initiatives"],
            "mappings": staging["mappings"],
        },
    )
    resp.raise_for_status()
    result = resp.json()
    print(
        f"imported: gaps={result['gaps']} initiatives={result['initiatives']} "
        f"mappings={result['mappings']} (created+updated, idempotent)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
