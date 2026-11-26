#!/usr/bin/env python3
"""Upload + import the IA SAT libraries into a running CISO Assistant instance.

Usage:
    python scripts/upload_libraries.py --url http://app.grc.localhost --token <PAT> \
        --dir libraries/ia-sat-ml/v1.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args()

    client = httpx.Client(
        base_url=args.url.rstrip("/") + "/api",
        headers={"Authorization": f"Token {args.token}"},
        timeout=120,
    )

    failures = 0
    for path in sorted(args.dir.glob("*.yaml")):
        resp = client.post(
            "/stored-libraries/upload/",
            params={"filename": path.name},
            headers={
                "Content-Type": "application/yaml",
                "Content-Disposition": f"attachment; filename={path.name}",
            },
            content=path.read_bytes(),
        )
        if resp.status_code not in (200, 201):
            print(f"  {path.name}: upload failed {resp.status_code} {resp.text[:120]}")
            failures += 1
            continue
        lib_id = resp.json().get("id")
        resp = client.post(f"/stored-libraries/{lib_id}/import/")
        print(f"  {path.name}: import -> {resp.json().get('status', resp.text[:120])}")
        if resp.status_code != 200:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
