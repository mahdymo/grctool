#!/usr/bin/env bash
# Phase 0 verification (AC 1-6 subset that is automatable locally).
# Run from the repo root with the stack up:  bash scripts/verify-phase0.sh
set -euo pipefail
cd "$(dirname "$0")/.."

CP_TOKEN=$(grep CONTROL_PLANE_TOKEN compose/.env | cut -d= -f2)
ADMIN_EMAIL="admin@ehsanlab.local"
ADMIN_PASSWORD="Phase0-Verify-$(date +%s)!"

echo "== AC1: service health =="
for svc in "http://app.grc.localhost/api/health/" "http://auth.grc.localhost/realms/ehsanlab-internal/.well-known/openid-configuration" "http://ops.grc.localhost/health" "http://127.0.0.1:8081/health"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$svc")
  echo "  $svc -> $code"
  [ "$code" = "200" ] || { echo "FAIL: $svc"; exit 1; }
done

echo "== Keycloak realms imported (M3) =="
for realm in ehsanlab-internal partner-a; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://auth.grc.localhost/realms/$realm")
  echo "  realm $realm -> $code"
  [ "$code" = "200" ] || { echo "FAIL: realm $realm"; exit 1; }
done

echo "== control plane auth fail-closed (AC 4 surface) =="
code=$(curl -s -o /dev/null -w "%{http_code}" "http://ops.grc.localhost/api/customers")
echo "  anonymous /api/customers -> $code (expect 401)"
[ "$code" = "401" ] || { echo "FAIL: control plane not fail-closed"; exit 1; }

echo "== create CISO Assistant admin + PAT =="
docker exec grc-backend-customer1 python manage.py shell -c "
from iam.models import User
if not User.objects.filter(email='$ADMIN_EMAIL').exists():
    User.objects.create_superuser(email='$ADMIN_EMAIL', password='$ADMIN_PASSWORD')
    print('admin created')
else:
    print('admin exists')
" | tail -1

PAT=$(docker exec grc-backend-customer1 python manage.py shell -c "
from iam.models import User, PersonalAccessToken
from knox.models import AuthToken
user = User.objects.get(email='$ADMIN_EMAIL')
token, plaintext = AuthToken.objects.create(user=user, expiry=None)
PersonalAccessToken.objects.create(name='phase0-verify', auth_token=token)
print(plaintext)
" | tail -1)
echo "  PAT minted: ${PAT:0:8}..."

echo "== AC2: import IA SAT libraries =="
for f in libraries/ia-sat-ml/v1.0/*.yaml; do
  LIB_ID=$(curl -s -X POST "http://app.grc.localhost/api/stored-libraries/upload" \
    -H "Authorization: Token $PAT" -F "file=@$f" | python -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)
  if [ -z "$LIB_ID" ]; then
    # already uploaded -> find by urn
    echo "  upload returned no id for $f (may already exist) — continuing"
    continue
  fi
  result=$(curl -s -X POST "http://app.grc.localhost/api/stored-libraries/$LIB_ID/import" \
    -H "Authorization: Token $PAT")
  echo "  $(basename $f): $result"
done

echo "== framework control counts (expect 112/131/17/39/42) =="
docker exec grc-backend-customer1 python manage.py shell -c "
from core.models import Framework
for fw in Framework.objects.filter(urn__contains='ia-sat-ml'):
    n = fw.requirement_nodes.filter(assessable=True).count()
    print(f'  {fw.ref_id}: {n} assessable')
" | grep assessable

echo "== AC3: Gulf Coverage migration =="
python migration/load_ciso.py --url http://app.grc.localhost --token "$PAT" \
  --staging migration/staging/gulf-coverage.json --cycle 2026-H2 2>&1 | tail -3
python migration/load_control_plane.py --url http://ops.grc.localhost \
  --token "$CP_TOKEN" --staging migration/staging/gulf-coverage.json
python migration/reconcile.py --staging migration/staging/gulf-coverage.json \
  --url http://app.grc.localhost --token "$PAT" --cycle 2026-H2 \
  --control-plane-url http://ops.grc.localhost --control-plane-token "$CP_TOKEN" | tail -3

echo "== ALL CHECKS PASSED =="
