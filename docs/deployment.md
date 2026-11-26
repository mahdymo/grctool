# Remote deployment — ia.tareeq.one

Deploys the full Phase 0 stack on a single host with automatic HTTPS.
Hostnames are fully configurable via env; this guide uses the first
deployment's names:

| Host | Service |
|---|---|
| `ia.tareeq.one` | CISO Assistant (the app — apex domain) |
| `auth.ia.tareeq.one` | Keycloak |
| `ops.ia.tareeq.one` | Control plane (restrict to office/VPN IPs) |
| `hooks.ia.tareeq.one` | Resend webhooks (public, signature-verified) |

This deployment uses `HTTPS_PORT=9443` (443 is occupied on the host), so
every URL carries the port: the app is `https://ia.tareeq.one:9443`, the
Keycloak console `https://auth.ia.tareeq.one:9443/admin`, and the Resend
webhook endpoint `https://hooks.ia.tareeq.one:9443/webhooks/resend`.
Keep `APP_PORT_SUFFIX=:9443` in `.env` in sync with `HTTPS_PORT` — the
suffix feeds the app's public URL and CSRF origins. Let's Encrypt still
needs `HTTP_PORT=80` reachable for certificate issuance; Caddy redirects
`http://…` to the correct `https://…:9443` automatically.

## 1. Server requirements

- Ubuntu 24.04 (or similar), 4 vCPU / 8 GB RAM / 80 GB disk minimum
- Docker Engine + Compose plugin:
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER && newgrp docker
  ```
- Firewall: only 22, 80, 443 open
  ```bash
  sudo ufw allow 22,80,443/tcp && sudo ufw enable
  ```

## 2. DNS (before first boot — Let's Encrypt needs it)

Create A records (and AAAA if the host has IPv6) at the `tareeq.one` DNS
provider, all pointing at the server IP:

```
ia.tareeq.one          A  <server-ip>
auth.ia.tareeq.one     A  <server-ip>
ops.ia.tareeq.one      A  <server-ip>
hooks.ia.tareeq.one    A  <server-ip>
```

Verify: `dig +short ia.tareeq.one auth.ia.tareeq.one ops.ia.tareeq.one hooks.ia.tareeq.one`

## 3. Install

```bash
git clone <repo-url> grctool && cd grctool/compose
cp env.production.example .env
# fill in .env — generate each secret: openssl rand -base64 24
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Caddy obtains certificates on first request; watch with
`docker logs -f grc-caddy`. First backend boot runs ~5 min of migrations.

## 4. First-boot setup

```bash
# Admin user + PAT (from repo root)
docker exec grc-backend-customer1 python manage.py shell -c "
from iam.models import User
User.objects.create_superuser(email='admin@tareeq.one', password='<strong-password>')"

# Import the IA SAT libraries (PAT minted as in scripts/verify-phase0.sh)
python scripts/upload_libraries.py --url https://ia.tareeq.one --token <PAT> \
    --dir libraries/ia-sat-ml/v1.0

# Migrate Gulf Coverage (workbooks copied to migration/source-data/ first —
# they are gitignored, so transfer them out-of-band, e.g. scp)
python migration/load_ciso.py --url https://ia.tareeq.one --token <PAT> \
    --staging migration/staging/gulf-coverage.json --cycle 2026-H2
python migration/load_control_plane.py --url https://ops.ia.tareeq.one \
    --token <CONTROL_PLANE_TOKEN> --staging migration/staging/gulf-coverage.json
python migration/reconcile.py --staging migration/staging/gulf-coverage.json \
    --url https://ia.tareeq.one --token <PAT> --cycle 2026-H2 \
    --control-plane-url https://ops.ia.tareeq.one --control-plane-token <CONTROL_PLANE_TOKEN>
```

## 5. Post-deploy hardening checklist (spec §6)

- [ ] Restrict `ops.ia.tareeq.one` to office/VPN IPs (uncomment the
      `remote_ip` block in `deploy/Caddyfile.prod`)
- [ ] Keycloak: log into `https://auth.ia.tareeq.one/admin`, disable the
      bootstrap admin after creating a named admin with TOTP
- [ ] Resend: verify sending domain `ia.tareeq.one` (SPF/DKIM/DMARC
      records per Resend dashboard), create prod API key + webhook
      (endpoint `https://hooks.ia.tareeq.one/webhooks/resend`, events
      `email.delivered/bounced/complained`), put both secrets in `.env`,
      `docker compose ... up -d --force-recreate email-worker`
- [ ] Backups: schedule `docs/runbooks/backup-restore.md` daily via cron
- [ ] Uptime monitor on `https://ia.tareeq.one/api/health/`

## Ports already taken on the host?

`HTTP_PORT`, `HTTPS_PORT` and `WEBHOOK_PORT` in `.env` control every port
this stack binds on the host. If other Docker containers already occupy
80/443 you have three options:

1. **Free 80/443 for this stack** (recommended for a dedicated domain):
   stop or re-port the other containers, keep `HTTP_PORT=80 HTTPS_PORT=443`.
2. **Run behind your existing reverse proxy**: set `HTTP_PORT`/`HTTPS_PORT`
   to free ports, terminate TLS on your existing proxy, and proxy the four
   hostnames to this stack. Caddy still routes by hostname internally; you
   lose its automatic certificates (your proxy owns TLS).
3. **Non-standard ports without a front proxy**: works for browsing
   (`https://ia.tareeq.one:8443`), but Let's Encrypt's HTTP-01/TLS-ALPN-01
   challenges need 80/443 reachable — you'd have to switch Caddy to the
   DNS-01 challenge (requires a DNS-provider plugin build of Caddy).

`WEBHOOK_PORT` only matters in dev (bound to 127.0.0.1); in prod webhooks
arrive via Caddy on `HOOKS_HOST`, and the prod overlay removes the published
port entirely.

## Changing the hostname later

Every hostname is env-driven. To move to a new domain: update the four
`*_HOST` vars in `.env`, add DNS records, `docker compose -f docker-compose.yml
-f docker-compose.prod.yml up -d --force-recreate caddy backend frontend keycloak`.
Caddy fetches new certificates automatically.

## Partner subdomains (Phase 2 preview)

The same pattern extends to whitelabel partners: add a vhost in
`Caddyfile.prod` (e.g. `partner-a.ia.tareeq.one`), a partner realm in
`keycloak/realms/`, and a themed frontend instance per the spec §2.1.
