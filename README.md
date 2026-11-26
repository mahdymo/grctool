# IA SAT Compliance & Remediation Platform

Multi-customer GRC platform for Insurance Authority (IA) SAT engagements, built for
EhsanLab operations and whitelabel partners. See `docs/` for architecture, threat
model, and runbooks.

**Base platform:** [CISO Assistant](https://github.com/intuitem/ciso-assistant-community)
(AGPL-3.0), run **unmodified** as pinned container images. All custom code lives in
sidecar services. See `NOTICE` for AGPL compliance information.

## Layout

| Path | Purpose |
|---|---|
| `compose/` | Docker Compose stacks (dev base + overlays) |
| `converter/` | IA SAT workbook → CISO Assistant library YAML (framework catalog only, no customer data) |
| `libraries/` | Generated, versioned IA SAT library files (`ia-sat-ml/v1.0`) |
| `migration/` | One-time, idempotent customer-data import tooling (not shipped to prod) |
| `control-plane/` | Customer registry, assessment cycles, portfolio roll-up API |
| `email-worker/` | Queue consumer + Resend client + webhooks + templates |
| `keycloak/` | Realm configuration as code, MFA policies |
| `deploy/` | Reverse proxy config, provisioning scripts |
| `security/` | Threat model, CI gate configuration |
| `docs/` | Data-model mapping, runbooks |

## Quick start (dev)

```bash
cp compose/.env.example compose/.env   # fill in values
docker compose -f compose/docker-compose.yml up -d
```

Then browse to `http://app.grc.localhost` (CISO Assistant via Caddy) and
`http://auth.grc.localhost` (Keycloak admin).

## Deploy to a server (production)

Hostnames are env-driven — see `docs/deployment.md`. Short version:

```bash
cd compose
cp env.production.example .env   # APP_HOST=ia.tareeq.one, secrets, ACME email
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Caddy provisions Let's Encrypt certificates automatically for
`ia.tareeq.one`, `auth.`, `ops.` and `hooks.` subdomains (DNS must point at
the server first).

## Security gates

All changes via PR; CI runs gitleaks, pip-audit, Semgrep, and Trivy. Direct pushes
to `main` are blocked. Install pre-commit hooks locally:

```bash
pip install pre-commit && pre-commit install
```
