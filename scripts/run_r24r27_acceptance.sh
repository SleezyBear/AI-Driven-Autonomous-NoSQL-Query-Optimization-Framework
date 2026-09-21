#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON=./nosql/bin/python
if [[ ! -x "$PYTHON" ]]; then
  echo "R24-R27 requires the repository Python 3.12 environment at ./nosql" >&2
  exit 1
fi

PROJECT="r24r27-$$"
SECRET_DIR="$(mktemp -d "${TMPDIR:-/tmp}/r24r27-secrets.XXXXXX")"

free_port() {
  "$PYTHON" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}

export POSTGRES_HOST_PORT="$(free_port)"
export MONGO_MONITORED_HOST_PORT="$(free_port)"
export MONGO_EVALUATION_HOST_PORT="$(free_port)"
export API_HOST_PORT="$(free_port)"
export FRONTEND_HOST_PORT="$(free_port)"
export POSTGRES_DB=r24r27_acceptance
export CONTROL_PLANE_MASTER_KEY_FILE="$SECRET_DIR/control_plane_master_key"
export MONGODB_REPLICA_KEYFILE="$SECRET_DIR/mongodb_replica_keyfile"
export JWT_SIGNING_KEY=r24r27-acceptance-signing-key-with-sufficient-entropy
export APP_ENV=test
export R24R27_PROJECT="$PROJECT"
export DATABASE_URL="postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:${POSTGRES_HOST_PORT}/${POSTGRES_DB}"
export TEST_POSTGRES_SERVER_URL="postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:${POSTGRES_HOST_PORT}/postgres"
export R24_API_URL="http://127.0.0.1:${API_HOST_PORT}"
export R24_MONGO_ROOT_URI="mongodb://control_plane_root:control_plane_root_dev_only@127.0.0.1:${MONGO_MONITORED_HOST_PORT}/admin?authSource=admin&directConnection=true"
export R24_MONGO_EXECUTOR_URI="mongodb://optimizer_executor:executor_dev_only@127.0.0.1:${MONGO_MONITORED_HOST_PORT}/commerce?authSource=admin&directConnection=true"
export R24_MONGO_EVALUATION_URI="mongodb://control_plane_root:control_plane_root_dev_only@127.0.0.1:${MONGO_EVALUATION_HOST_PORT}/admin?authSource=admin&directConnection=true"
export MONITORED_MONGODB_URI="mongodb://optimizer_observer:observer_dev_only@127.0.0.1:${MONGO_MONITORED_HOST_PORT}/admin?authSource=admin&directConnection=true"
export R19LP_PRODUCTION_TEST_MONGODB_URI="$R24_MONGO_ROOT_URI"
export MONGODB_EXECUTOR_URI="$R24_MONGO_EXECUTOR_URI"
export OLLAMA_CHAT_MODEL="${OLLAMA_CHAT_MODEL:-gemma4:e4b}"
export OLLAMA_EMBEDDING_MODEL="${OLLAMA_EMBEDDING_MODEL:-embeddinggemma}"
export OLLAMA_TIMEOUT_SECONDS=600

cleanup() {
  docker compose -p "$PROJECT" --profile light down --remove-orphans >/dev/null 2>&1 || true
  if [[ "$SECRET_DIR" == "${TMPDIR:-/tmp}"/r24r27-secrets.* ]]; then
    rm -rf "$SECRET_DIR"
  fi
}
trap cleanup EXIT INT TERM

openssl rand 32 > "$CONTROL_PLANE_MASTER_KEY_FILE"
openssl rand -base64 756 > "$MONGODB_REPLICA_KEYFILE"
chmod 400 "$CONTROL_PLANE_MASTER_KEY_FILE" "$MONGODB_REPLICA_KEYFILE"
mkdir -p artifacts/generated

wait_api() {
  for _attempt in $(seq 1 90); do
    if curl --max-time 2 --fail --silent "$R24_API_URL/health/ready" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "R24-R27 API did not become ready" >&2
  return 1
}

state_signature() {
  docker compose -p "$PROJECT" exec -T postgres \
    psql -U control_plane -d "$POSTGRES_DB" -Atc \
    "SELECT (SELECT count(*) FROM optimization_runs)::text || ':' || (SELECT count(*) FROM jobs)::text || ':' || (SELECT count(*) FROM production_ledger_entries)::text"
}

echo "[R24-R27] preflight and isolated infrastructure"
"$PYTHON" -m pip check
"$PYTHON" scripts/check_dependency_locks.py
"$PYTHON" scripts/verify_requirements.py
"$PYTHON" scripts/check_python_dependencies.py
"$PYTHON" scripts/audit_tracked_secrets.py
curl --max-time 5 --fail --silent "${OLLAMA_BASE_URL:-http://127.0.0.1:11434}/api/tags" >/dev/null
docker compose -p "$PROJECT" --profile light up -d --wait postgres mongo-monitored mongo-evaluation
docker compose -p "$PROJECT" --profile light run --rm mongo-monitored-init
docker compose -p "$PROJECT" --profile light run --rm mongo-evaluation-init
"$PYTHON" -m alembic -c backend/alembic.ini upgrade head
"$PYTHON" scripts/verify_mongodb_permissions.py

echo "[R24] real API, frontend, and no-mock lifecycle"
docker compose -p "$PROJECT" --profile light up -d --build --wait api frontend
wait_api
PYTHONPATH=backend "$PYTHON" scripts/r24_system_acceptance.py | tee artifacts/generated/r24-system.log
"$PYTHON" -c 'import json; from pathlib import Path; p=json.loads(Path("artifacts/generated/r24-system.json").read_text()); assert p["status"]=="SYSTEM_PASS" and len(p["paths"])==8 and p["real_ollama"] and p["query_settings"]["exact_inverse"]'

echo "[R24] API restart durability"
before_api_restart="$(state_signature)"
docker compose -p "$PROJECT" restart api
wait_api
after_api_restart="$(state_signature)"
[[ "$before_api_restart" == "$after_api_restart" ]]

echo "[R24] Playwright against persisted real stack"
docker run --rm --platform linux/amd64 \
  --add-host host.docker.internal:host-gateway \
  --env-file artifacts/generated/r24-playwright.env \
  -e PLAYWRIGHT_BASE_URL="http://host.docker.internal:${FRONTEND_HOST_PORT}" \
  -v "$ROOT_DIR/frontend:/app" -w /app \
  mcr.microsoft.com/playwright:v1.55.1-jammy \
  npx playwright test | tee artifacts/generated/playwright.log

echo "[R25] adversarial, security, statistical, and durable failure qualification"
"$PYTHON" -m pytest \
  backend/tests/safetybench backend/tests/r25 backend/tests/ai \
  backend/tests/pipeline/test_diagnosis.py backend/tests/diagnosis/test_durable_diagnosis.py \
  backend/tests/ranking/test_durable_ranking.py backend/tests/telemetry \
  backend/tests/unit/admission backend/tests/security backend/tests/auth \
  backend/tests/recovery backend/tests/rollback
PYTHONPATH=backend "$PYTHON" scripts/r25_replica_partition.py

echo "[R26] worker, run, approval, target-lock concurrency"
"$PYTHON" -m pytest \
  backend/tests/worker backend/tests/r26 \
  backend/tests/approvals/test_durable_distributed.py \
  backend/tests/production/test_distributed_target_lock.py
PYTHONPATH=backend "$PYTHON" scripts/r26_load_soak.py --duration 60 \
  | tee artifacts/generated/r26-soak.log

echo "[R27] autonomy, predeployment, rollback, monitoring, and experience authority"
"$PYTHON" -m pytest \
  backend/tests/autonomy backend/tests/production backend/tests/monitoring \
  backend/tests/experience backend/tests/rollback backend/tests/reversion

echo "[R24] PostgreSQL and Mongo interruption/recovery"
before_outages="$(state_signature)"
docker compose -p "$PROJECT" stop -t 10 postgres
readiness_during_postgres="$({ curl --max-time 10 --silent --output /dev/null --write-out '%{http_code}' "$R24_API_URL/health/ready" || true; })"
[[ "$readiness_during_postgres" == "503" ]]
docker compose -p "$PROJECT" start postgres
wait_api
[[ "$before_outages" == "$(state_signature)" ]]

docker compose -p "$PROJECT" stop -t 10 mongo-monitored
if "$PYTHON" -c 'import os; from pymongo import MongoClient; c=MongoClient(os.environ["R24_MONGO_ROOT_URI"],serverSelectionTimeoutMS=1500); c.admin.command({"ping":1})'; then
  echo "MongoDB unexpectedly remained reachable during interruption" >&2
  exit 1
fi
docker compose -p "$PROJECT" start mongo-monitored
for _attempt in $(seq 1 60); do
  if "$PYTHON" -c 'import os; from pymongo import MongoClient; c=MongoClient(os.environ["R24_MONGO_ROOT_URI"],serverSelectionTimeoutMS=1000); c.admin.command({"ping":1}); c.close()' >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
"$PYTHON" -c 'import os; from pymongo import MongoClient; c=MongoClient(os.environ["R24_MONGO_ROOT_URI"],serverSelectionTimeoutMS=2000); assert c.admin.command({"ping":1})["ok"]==1; c.close()'
[[ "$before_outages" == "$(state_signature)" ]]

echo "[Regression] R19 and accepted R20-R23 behavior"
"$PYTHON" -m pytest \
  backend/tests/runs backend/tests/worker backend/tests/approvals \
  backend/tests/production backend/tests/monitoring backend/tests/rollback
"$PYTHON" -m pytest \
  backend/tests/hardening backend/tests/test_health.py \
  backend/tests/security/test_audit_controls.py \
  backend/tests/production/test_runtime_settings.py
PYTHONPATH=backend "$PYTHON" scripts/r22_postgres_acceptance.py
PYTHONPATH=backend "$PYTHON" scripts/r23_mongodb_acceptance.py

echo "[Regression] full backend, frontend, and static closure"
"$PYTHON" -m pytest backend/tests | tee artifacts/generated/backend-tests-r24r27.log
"$PYTHON" -m ruff check backend benchmarks scripts
MYPYPATH=backend "$PYTHON" -m mypy backend/app | tee artifacts/generated/mypy-r24r27.log
"$PYTHON" scripts/generate_openapi_types.py --check
docker run --rm --platform linux/amd64 \
  -v "$ROOT_DIR/frontend:/src:ro" node:22.14.0-alpine \
  sh -c 'cp -R /src /tmp/frontend && cd /tmp/frontend && npm ci --ignore-scripts >/dev/null && npm test && npm run build' \
  | tee artifacts/generated/frontend-r24r27.log
"$PYTHON" scripts/check_system_pass_registry.py
git diff --check

echo "R24-R27 ACCEPTANCE: PASS"
