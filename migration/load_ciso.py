#!/usr/bin/env python3
"""Load migrated assessment statuses into a running CISO Assistant instance.

One-time migration tooling (spec §8) — idempotent: safe to re-run; only
changed requirement assessments are patched.

Prerequisites:
  1. Instance running; IA SAT libraries imported (libraries/ia-sat-ml/v1.0).
  2. A personal access token (PAT) for an account with write access.

Usage:
    python load_ciso.py --url http://app.grc.localhost --token <PAT> \
        --staging staging/gulf-coverage.json --cycle "2026-H2"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

# Library slug -> framework URN (must match converter/sat_converter.py)
FRAMEWORK_URNS = {
    slug: f"urn:intuitem:risk:framework:ia-sat-ml-{slug}"
    for slug in ("nca-ecc", "pdpl", "sama-mvc", "emerging-tech", "it-resilience")
}

DOMAIN_NAMES = {
    "nca-ecc": "Cybersecurity (NCA ECC)",
    "pdpl": "Privacy (SDAIA PDPL)",
    "sama-mvc": "SAMA MVC",
    "emerging-tech": "Emerging Tech",
    "it-resilience": "IT Resilience",
}


class CisoClient:
    def __init__(self, base_url: str, token: str):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/api",
            headers={"Authorization": f"Token {token}"},
            timeout=60,
        )

    def get_all(self, path: str, **params) -> list[dict]:
        results, offset = [], 0
        while True:
            resp = self.client.get(path, params={**params, "limit": 200, "offset": offset})
            resp.raise_for_status()
            page = resp.json()
            results.extend(page["results"])
            if not page.get("next"):
                return results
            offset += 200

    def post(self, path: str, payload: dict) -> dict:
        resp = self.client.post(path, json=payload)
        resp.raise_for_status()
        return resp.json()

    def patch(self, path: str, payload: dict) -> dict:
        resp = self.client.patch(path, json=payload)
        resp.raise_for_status()
        return resp.json()


def find_framework(client: CisoClient, urn: str) -> dict:
    matches = [f for f in client.get_all("/frameworks/") if f.get("urn") == urn]
    if not matches:
        raise SystemExit(f"framework {urn} not found — import the IA SAT libraries first")
    return matches[0]


def ensure_compliance_assessment(client: CisoClient, framework: dict, name: str) -> dict:
    existing = [
        ca
        for ca in client.get_all("/compliance-assessments/")
        if ca.get("name") == name and ca.get("framework", {}).get("id") == framework["id"]
    ]
    if existing:
        print(f"  assessment exists: {name}")
        return existing[0]
    created = client.post(
        "/compliance-assessments/",
        {
            "name": name,
            "framework": framework["id"],
            "folder": framework["folder"]["id"],
        },
    )
    print(f"  assessment created: {name}")
    return created


def observation_for(entry: dict) -> str | None:
    """Where the migrated free text lands on the requirement assessment."""
    parts = []
    if entry.get("na_justification"):
        parts.append(f"N/A justification: {entry['na_justification']}")
    if entry.get("recommendation"):
        parts.append(f"Recommendation: {entry['recommendation']}")
    if entry.get("management_response"):
        parts.append(f"Management response: {entry['management_response']}")
    if entry.get("owner"):
        parts.append(f"Owner (legacy): {entry['owner']}")
    if entry.get("target_closing"):
        parts.append(f"Target closing (legacy): {entry['target_closing']}")
    return "\n".join(parts) if parts else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--cycle", required=True, help="cycle label, e.g. 2026-H2")
    args = parser.parse_args()

    staging = json.loads(args.staging.read_text(encoding="utf-8"))
    client = CisoClient(args.url, args.token)

    total_patched = total_unchanged = 0
    for slug, urn in FRAMEWORK_URNS.items():
        entries = staging["statuses"][slug]
        framework = find_framework(client, urn)
        name = f"IA SAT M&L {args.cycle} — {DOMAIN_NAMES[slug]}"
        assessment = ensure_compliance_assessment(client, framework, name)

        req_assessments = client.get_all(
            "/requirement-assessments/", compliance_assessment__id=assessment["id"]
        )
        by_ref = {}
        for ra in req_assessments:
            requirement = ra.get("requirement")
            if isinstance(requirement, dict) and requirement.get("ref_id"):
                by_ref[requirement["ref_id"]] = ra
            else:
                # Listing returns bare IDs on some versions — fetch the detail.
                resp = client.client.get(f"/requirement-assessments/{ra['id']}/")
                resp.raise_for_status()
                detail = resp.json()
                by_ref[detail["requirement"]["ref_id"]] = detail

        patched = unchanged = missing = 0
        for entry in entries:
            ra = by_ref.get(entry["ref_id"])
            if ra is None:
                print(f"  warning: no requirement assessment for {entry['ref_id']}")
                missing += 1
                continue
            payload = {
                "result": entry["result"],
                "status": "done" if entry["result"] != "not_assessed" else "to_do",
            }
            observation = observation_for(entry)
            if observation:
                payload["observation"] = observation
            if ra.get("result") == payload["result"] and ra.get("observation") == payload.get(
                "observation", ra.get("observation")
            ):
                unchanged += 1
                continue
            client.patch(f"/requirement-assessments/{ra['id']}/", payload)
            patched += 1
        print(f"  {slug:15s} patched={patched} unchanged={unchanged} missing={missing}")
        total_patched += patched
        total_unchanged += unchanged

    print(f"done: {total_patched} patched, {total_unchanged} already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
