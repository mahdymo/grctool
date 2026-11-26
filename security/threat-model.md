# Threat Model — IA SAT Compliance & Remediation Platform (v1.0)

Method: STRIDE over the data-flow diagram below. Required by spec §6.1.1;
**this document must be reviewed and signed off before implementation
proceeds past Phase 0.** Reviewer: ____ Date: ____

## 1. Why this platform is a target

It aggregates **control weaknesses across multiple insurance customers** —
effectively a pre-built attack plan ("which customers are weak on PDPL
30.x?") — plus PII (owner names, emails) subject to PDPL. Compromise of the
portfolio roll-up leaks every customer's gaps at once.

## 2. Data-flow diagram & trust boundaries

```
            TB1: internet → proxy
[Users] ──TLS──> [Caddy reverse proxy]
                     │ TB2: proxy → internal network
        ┌────────────┼──────────────────┬───────────────┐
        ▼            ▼                  ▼               ▼
   [Keycloak]  [CISO Assistant    [Control plane]  [Email worker]
    (OIDC/SAML)  instance(s)]          │                │
                     │                 │                │ TB4: worker → Resend API
                     ▼                 ▼                ▼
                [Postgres]        [Postgres]        [Resend]──> [Recipient MTAs]
                     ▲                 ▲
                     └──TB3: control plane → instance APIs (token/mTLS)
```

Trust boundaries:
- **TB1** internet → reverse proxy (only public surface; TLS 1.2+, HSTS)
- **TB2** proxy → internal services (no direct DB access from proxy)
- **TB3** control plane → customer instances (authenticated API tokens; mTLS in prod)
- **TB4** email worker → Resend (TLS + API key; the only component holding the key)

## 3. Assets

| Asset | Sensitivity | Location |
|---|---|---|
| Assessment statuses & gap registers | Confidential — attack target list | per-instance Postgres, control plane |
| Evidence files | Confidential — customer-internal docs | instance volumes |
| Resend API key | Secret — send-as-us capability | email worker env only |
| Keycloak signing keys / client secrets | Secret — auth bypass | Keycloak DB |
| DB credentials | Secret | per-service env, least-privilege roles |
| PII (names, emails, RACI) | PDPL personal data | instances + control plane |
| Audit logs | Integrity-critical | append-only tables |

## 4. STRIDE analysis

### Spoofing
- **S1** Stolen user credentials → Keycloak MFA (TOTP) mandatory for all users; break-glass accounts hardware-key protected, monitored. *Residual: phishing-resistant MFA (WebAuthn) rollout.*
- **S2** Forged email webhooks → svix signature verification; forged-signature test in CI (AC 5).
- **S3** Token theft between control plane and instances → short-lived tokens; mTLS in prod (TB3); network isolation (no published DB ports).

### Tampering
- **T1** Silent mutation of submitted assessments → cycle lock + append-only snapshots (`cycle_snapshots`); status changes in append-only `status_audit_log`.
- **T2** Tampered container images → images pinned by digest; Trivy in CI; no deploy on critical findings.
- **T3** Malicious dependency → pip-audit + Dependabot/Renovate; lockfiles.

### Repudiation
- **R1** "I didn't change that status" → audit log records author, timestamp (NTP-synced), old/new status on every transition; retained ≥ 2 years.

### Information disclosure
- **I1** Cross-customer data leak → instance-per-customer isolation; separate DB roles per service; cross-customer access denial tests (AC 4); control plane holds roll-up metrics only (no evidence, no assessment text).
- **I2** Secret leakage via repo → gitleaks pre-commit + CI; `.env` gitignored; customer workbooks gitignored (`migration/source-data/`, `migration/staging/`).
- **I3** PII in logs → log policy: no email bodies, no assessment content in app logs (spec §6.2); structlog JSON logs reviewed in CI.
- **I4** Verbose errors/stack traces → `DJANGO_DEBUG=False`, docs endpoints disabled on sidecars.

### Denial of service
- **D1** Auth endpoint brute force → Keycloak brute-force protection (5 failures → progressive lockout); allauth login rate limits on instances.
- **D2** Queue flooding → email idempotency keys; dead-letter caps; Redis not publicly reachable.
- **D3** File upload abuse → upload allowlist (pdf/png/jpg/xlsx/zip ≤ 25 MB), randomized filenames, storage outside webroot (spec §6.1.7).

### Elevation of privilege
- **E1** Control Owner editing others' controls → object-level permissions server-side (spec §5.2); RBAC matrix tests.
- **E2** Partner seeing another partner's customers → one realm per partner; group→instance attributes; control plane filters by partner claim.
- **E3** Container escape → `user: 1001`, `read_only` root FS, `cap_drop: ALL`, `no-new-privileges` on upstream services (inherited from upstream compose hardening).

## 5. Top risks & mitigations shipped in Phase 0

| # | Risk | Mitigation in this build |
|---|---|---|
| 1 | Portfolio roll-up compromise exposes all customers | Token auth on every control plane route; minimal data (metrics only); no public route |
| 2 | Resend key leak → phishing as us | Key only in email worker env; rotation runbook; per-env keys |
| 3 | Weak onboarding auth | MFA default-required action; single-use 24h invites; password ≥ 12 + breach screening (Keycloak policy) |
| 4 | Migration tooling leaks customer data | source-data/ + staging/ gitignored; tooling never deployed to prod |

## 6. Out of scope (documented)

- Automated evidence collection (non-goal, spec §1.3)
- DDoS protection beyond proxy rate limits (hosting-layer concern, Phase 3 pentest scope)
