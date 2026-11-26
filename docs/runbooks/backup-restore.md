# Runbook: backup & restore (spec §6.1.9)

Targets: RPO ≤ 24h, RTO ≤ 8h per instance.

## Backup

Daily (cron on the host, Phase 1 automates via provisioning):

```bash
# Per-database logical dump, encrypted at rest by volume encryption
docker exec grc-postgres pg_dump -U postgres -Fc ciso_customer1 \
  > backups/$(date +%F)/ciso_customer1.dump
docker exec grc-postgres pg_dump -U postgres -Fc controlplane \
  > backups/$(date +%F)/controlplane.dump
docker exec grc-postgres pg_dump -U postgres -Fc emailworker \
  > backups/$(date +%F)/emailworker.dump
docker exec grc-postgres pg_dump -U postgres -Fc keycloak \
  > backups/$(date +%F)/keycloak.dump

# Evidence volumes (per instance, never rolled up — spec §6.3)
docker run --rm -v grctool_ciso_evidence_customer1:/data:ro \
  -v "$PWD/backups/$(date +%F)":/backup alpine \
  tar czf /backup/evidence_customer1.tar.gz -C /data .
```

Backups are per-instance, encrypted (volume-level AES-256), and stored
off-host. Retention per customer contract; deletion follows the offboarding
runbook (spec §6.3).

## Restore test (weekly — document each run)

```bash
# 1. Restore into a scratch database, never over production
docker exec grc-postgres createdb -U postgres restore_test
cat backups/<date>/ciso_customer1.dump | \
  docker exec -i grc-postgres pg_restore -U postgres -d restore_test
# 2. Spot-check row counts
docker exec grc-postgres psql -U postgres -d restore_test \
  -c "select count(*) from core_requirementassessment;"
# 3. Drop the scratch database
docker exec grc-postgres dropdb -U postgres restore_test
```

| Date | Operator | DB | Rows check | Result |
|---|---|---|---|---|
| _pending first run_ | | | | |
