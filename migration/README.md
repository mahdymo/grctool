# Migration tooling (one-time, spec §8)

Converts the legacy Excel operating model into platform data. **Not shipped to
prod runtime.** Customer data (`source-data/`, `staging/`) is gitignored —
never commit it.

## Pipeline

```
SAT workbook (.xlsm) ─┐
                      ├─> parse_workbooks.py ─> staging/<customer>.json
Roadmap workbook ─────┘                              │
                        ┌────────────────────────────┼─────────────────────┐
                        ▼                            ▼                     ▼
                 load_ciso.py               load_control_plane.py   reconcile.py
                 (statuses -> CISO          (gaps/initiatives/      (expected vs live,
                  Assistant requirement      mappings -> control     compliance % with
                  assessments via REST)      plane bulk import)      pinned formula)
```

## Steps for a customer migration

1. Copy the customer's two workbooks into `source-data/` (gitignored).
2. `python parse_workbooks.py --sat source-data/<sat>.xlsm --roadmap source-data/<roadmap>.xlsx --out staging/<customer>.json`
3. Import the IA SAT libraries into the customer's instance (see `libraries/`).
4. `python load_ciso.py --url <instance> --token <PAT> --staging staging/<customer>.json --cycle 2026-H2`
5. `python load_control_plane.py --url <control-plane> --token <token> --staging staging/<customer>.json`
6. `python reconcile.py --staging staging/<customer>.json --url ... --token ... --control-plane-url ... --control-plane-token ...`
   — must print `reconciliation OK` before sign-off (AC 3).

All loaders are idempotent: re-running patches only drifted records.

## Data mapping decisions

- Workbook statuses map to CISO Assistant `result`: Compliant→`compliant`,
  Partially Compliant→`partially_compliant`, Non-Compliant→`non_compliant`,
  N/A→`not_applicable`, blank→`not_assessed`.
- N/A justification: taken from the workbook's recommendation column (where
  the SAT records the rationale); placeholder backfill "Migrated from legacy
  workbook — justification pending" if empty (spec §3.1 requires one).
- Recommendation / management response / legacy owner / legacy closing date
  are preserved in the requirement assessment observation field.
- Compliance % formula (pinned from the workbook): `Compliant / (assessed − N/A)`.
- Gap "Tier" is carried verbatim (no derivation logic in v1).
