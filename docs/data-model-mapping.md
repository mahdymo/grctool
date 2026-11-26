# Data model mapping — spec ↔ platform (spec §11 requirement)

Where CISO Assistant has richer native models, the spec's concepts map onto
them as follows. Anything CISO Assistant lacks lives in the control plane.

## Framework layer (CISO Assistant, unmodified)

| Spec / workbook | CISO Assistant | Notes |
|---|---|---|
| Regulation (NCA ECC, PDPL, SAMA MVC, Emerging Tech, IT Resilience) | 5 `Framework`s, one per domain | library `ia-sat-ml/v1.0`, 5 YAML files |
| Domain # / Domain | non-assessable `RequirementNode` (depth 2, NCA only) | other domains are flat |
| Control # | `RequirementNode.ref_id` (stable key) | Privacy Transfer-Regulation articles prefixed `TR-` (collision with PDPL articles) |
| Control Description | `RequirementNode.description` §1 | verbatim |
| Implementation Guide | `description` section "**Implementation guide**" | model has no dedicated field in v4.3.4 |
| Verification method | `description` section "**Verification method**" | ditto |
| Required Evidence | `RequirementNode.typical_evidence` | verbatim |
| Library version | library `version` field | new IA SAT version = new library files; assessment history untouched |

## Assessment layer (CISO Assistant)

| Spec | CISO Assistant | Notes |
|---|---|---|
| Full SAT per cycle | `ComplianceAssessment` per framework, named `IA SAT M&L <cycle> — <domain>` | 5 per cycle |
| Status enum | `RequirementAssessment.result`: compliant / partially_compliant / non_compliant / not_applicable / not_assessed | exact IA SAT legend |
| N/A justification (mandatory) | `observation` field, prefixed "N/A justification:" | enforced at migration + API layer |
| Recommendation / management response / legacy owner / closing date | `observation` (labelled lines) | preserved verbatim from workbook |
| Assessment lock on submit | control plane `Cycle` state + `CycleSnapshot` (append-only) | CISO Assistant has no native versioning |
| Delta update audit trail | control plane `StatusAuditLog` (append-only) | author, timestamp, old/new, comment |

## Remediation layer (control plane — no CISO Assistant equivalent)

| Spec §3.4 | Control plane table | Notes |
|---|---|---|
| Gap (GAP-###) | `gaps` | per-customer gapless sequence `id_sequences`; only Non-/Partially-Compliant eligible |
| Initiative (REM-###) | `initiatives` | phase/priority/status enums per spec; budget in SAR |
| Gap ↔ Initiative M2M | `gap_initiative_map` | junction table |
| Overdue rule | computed: `target_end < today AND status ∉ {Done, Cancelled}` | dashboard + email trigger |
| RACI | `initiatives.raci_r/a/c/i` | person-name fields in v1 |

## Portfolio layer (control plane)

| Spec §3.5 | Implementation |
|---|---|
| Compliance % per domain | `Compliant / (assessed − N/A)` — formula pinned from the SAT workbook's own dashboard |
| Cross-customer heatmap | `portfolio_metrics` (latest per customer × domain), polled ≤ 5 min |
| Evidence | stays in instances; never rolled up (spec §6.3) |
