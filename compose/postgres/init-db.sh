#!/bin/bash
# Bootstrap per-service databases and least-privilege users (spec §6.1.6).
# Runs once on first container start. Passwords come from container env.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE ROLE ciso LOGIN PASSWORD '${CISO_DB_PASSWORD}';
    CREATE DATABASE ciso_customer1 OWNER ciso;

    CREATE ROLE keycloak LOGIN PASSWORD '${KC_DB_PASSWORD}';
    CREATE DATABASE keycloak OWNER keycloak;

    CREATE ROLE controlplane LOGIN PASSWORD '${CP_DB_PASSWORD}';
    CREATE DATABASE controlplane OWNER controlplane;

    CREATE ROLE emailworker LOGIN PASSWORD '${EW_DB_PASSWORD}';
    CREATE DATABASE emailworker OWNER emailworker;

    -- No service user may create roles/databases or read another service's DB.
    REVOKE ALL ON DATABASE postgres FROM ciso, keycloak, controlplane, emailworker;
EOSQL
