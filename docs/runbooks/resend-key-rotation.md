# Runbook: Resend API key rotation (spec §4.4.2)

Keys are per-environment (dev / staging / prod) and live only in the
secrets manager / deploy-time environment. Never in the repo, never in
client code.

## Rotation procedure (zero-downtime)

1. In the Resend dashboard, create a **new API key** for the environment
   (name: `grc-<env>-<yyyy-mm>`).
2. Update the secrets manager entry `RESEND_API_KEY` for that environment.
3. Rolling-restart the email worker only:
   ```bash
   docker compose -f compose/docker-compose.yml up -d --force-recreate email-worker
   ```
4. Verify: enqueue a test job to a internal recipient; confirm
   `send_log.status = sent` and delivery in the Resend dashboard.
5. Revoke the **old** key in the Resend dashboard.
6. Record the rotation (date, operator, key name) in the change log.

## Webhook secret rotation

`RESEND_WEBHOOK_SECRET` rotates the same way: create a new webhook signing
secret in Resend, update the secret store, restart the worker. During the
overlap, signature failures return 401 and Resend retries — no loss.

## Compromise response

If a key may have leaked: revoke immediately (step 5 first), rotate, then
audit `send_log` for sends outside expected idempotency-key patterns and
review Resend dashboard logs for unknown sends. Triage SLA: critical, 72h
(spec §6.1.13).
