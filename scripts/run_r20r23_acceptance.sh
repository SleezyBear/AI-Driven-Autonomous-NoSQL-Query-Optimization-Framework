#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ./nosql/bin/python ]]; then
  python3.12 -m venv nosql
  ./nosql/bin/python -m pip install -r requirements.txt
fi

PYTHON=./nosql/bin/python
PROJECT="r20r23-$$"
SECRET_DIR="$(mktemp -d "${TMPDIR:-/tmp}/r20r23-secrets.XXXXXX")"
export CONTROL_PLANE_MASTER_KEY_FILE="$SECRET_DIR/control_plane_master_key"
export MONGODB_REPLICA_KEYFILE="$SECRET_DIR/mongodb_replica_keyfile"
export JWT_SIGNING_KEY="r20r23-acceptance-signing-key-with-sufficient-entropy"
export APP_ENV=test
export DATABASE_URL="postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:5432/control_plane"

cleanup() {
  docker compose -p "$PROJECT" --profile light down --remove-orphans >/dev/null 2>&1 || true
  if [[ "$SECRET_DIR" == "${TMPDIR:-/tmp}"/r20r23-secrets.* ]]; then
    rm -rf "$SECRET_DIR"
  fi
}
trap cleanup EXIT INT TERM

openssl rand 32 > "$CONTROL_PLANE_MASTER_KEY_FILE"
openssl rand -base64 756 > "$MONGODB_REPLICA_KEYFILE"
chmod 400 "$CONTROL_PLANE_MASTER_KEY_FILE" "$MONGODB_REPLICA_KEYFILE"
mkdir -p artifacts/generated

echo "[R20-R23] lock, environment, and secret checks"
$PYTHON scripts/check_dependency_locks.py
$PYTHON scripts/verify_requirements.py
$PYTHON scripts/check_python_dependencies.py
$PYTHON scripts/audit_tracked_secrets.py
$PYTHON -m pip check

echo "[R20-R23] clean dependency reconstruction"
docker run --rm --platform linux/amd64 \
  -v "$ROOT_DIR:/src:ro" -w /src python:3.12-slim \
  sh -c 'python -m venv /tmp/clean && /tmp/clean/bin/python -m pip install --retries 8 --timeout 60 --require-hashes -r requirements.txt >/dev/null && /tmp/clean/bin/python -m pip check'
docker run --rm --platform linux/amd64 \
  -v "$ROOT_DIR/frontend:/src:ro" node:22.14.0-alpine \
  sh -c 'cp -R /src /tmp/frontend && cd /tmp/frontend && npm ci --ignore-scripts && npm test && npm run build'

echo "[R20-R23] current vulnerability audits and inventories"
$PYTHON -m pip_audit --no-deps -r requirements.txt --progress-spinner off
(cd frontend && npm audit --audit-level=low)
$PYTHON scripts/generate_sbom.py
BUILD_NODE_VERSION=22.14.0 $PYTHON scripts/capture_build_provenance.py

echo "[R20-R23] isolated control-plane and Mongo fixtures"
docker compose -p "$PROJECT" --profile light up -d --wait postgres mongo-monitored mongo-evaluation
docker compose -p "$PROJECT" --profile light run --rm mongo-monitored-init
docker compose -p "$PROJECT" --profile light run --rm mongo-evaluation-init
$PYTHON -m alembic -c backend/alembic.ini upgrade head

echo "[R20-R23] focused runtime and operational qualification"
$PYTHON -m pytest backend/tests/hardening backend/tests/test_health.py backend/tests/security/test_audit_controls.py backend/tests/production/test_runtime_settings.py
PYTHONPATH=backend $PYTHON scripts/r22_postgres_acceptance.py
PYTHONPATH=backend $PYTHON scripts/r23_mongodb_acceptance.py

echo "[R20-R23] container build, non-root, readiness, and shutdown smoke"
docker compose -p "$PROJECT" --profile light build api worker frontend
API_IMAGE="${PROJECT}-api:latest"
docker image inspect "$API_IMAGE" >/dev/null
for runtime_image in "$API_IMAGE" "${PROJECT}-worker:latest"; do
  docker run --rm --platform linux/amd64 "$runtime_image" python -c \
    'import importlib.util; names=("pytest","mypy","ruff","pip_audit"); present=[name for name in names if importlib.util.find_spec(name)]; assert not present, f"non-runtime tools installed: {present}"'
done
if docker run --rm --platform linux/amd64 -e APP_ENV=production "$API_IMAGE"; then
  echo "production API unexpectedly started without required configuration" >&2
  exit 1
fi
docker compose -p "$PROJECT" --profile light up -d --wait api worker frontend
for service in api worker frontend; do
  container_id="$(docker compose -p "$PROJECT" ps -q "$service")"
  configured_user="$(docker inspect --format '{{.Config.User}}' "$container_id")"
  if [[ -z "$configured_user" || "$configured_user" == "0" || "$configured_user" == "root" ]]; then
    echo "$service container is configured to run as root" >&2
    exit 1
  fi
done
curl --fail --silent http://127.0.0.1:8000/health/live >/dev/null
curl --fail --silent http://127.0.0.1:8000/health/ready >/dev/null
curl --fail --silent http://127.0.0.1:8000/metrics >/dev/null
job_count_before="$(
  docker compose -p "$PROJECT" exec -T postgres \
    psql -U control_plane -d control_plane -Atc 'SELECT count(*) FROM jobs'
)"
docker compose -p "$PROJECT" stop -t 10 postgres
api_outage_status="$(
  curl --max-time 15 --silent --output /dev/null --write-out '%{http_code}' \
    http://127.0.0.1:8000/health/ready || true
)"
if [[ "$api_outage_status" != "503" ]]; then
  echo "API readiness did not return 503 during PostgreSQL outage" >&2
  exit 1
fi
if docker compose -p "$PROJECT" exec -T worker python -m app.worker.service --healthcheck; then
  echo "worker unexpectedly reported ready during PostgreSQL outage" >&2
  exit 1
fi
docker compose -p "$PROJECT" start postgres
api_recovered=false
worker_recovered=false
for _attempt in $(seq 1 60); do
  if curl --max-time 2 --fail --silent http://127.0.0.1:8000/health/ready >/dev/null; then
    api_recovered=true
    break
  fi
  sleep 1
done
for _attempt in $(seq 1 60); do
  if docker compose -p "$PROJECT" exec -T worker python -m app.worker.service --healthcheck >/dev/null 2>&1; then
    worker_recovered=true
    break
  fi
  sleep 1
done
if [[ "$api_recovered" != "true" || "$worker_recovered" != "true" ]]; then
  echo "API or worker did not recover after PostgreSQL restart" >&2
  exit 1
fi
job_count_after="$(
  docker compose -p "$PROJECT" exec -T postgres \
    psql -U control_plane -d control_plane -Atc 'SELECT count(*) FROM jobs'
)"
if [[ "$job_count_before" != "$job_count_after" ]]; then
  echo "durable job state changed across PostgreSQL outage" >&2
  exit 1
fi
docker compose -p "$PROJECT" stop -t 45 worker api

echo "[R20-R23] accepted functionality and static regression"
$PYTHON -m pytest backend/tests | tee artifacts/generated/backend-tests.log
$PYTHON -m ruff check backend benchmarks scripts
MYPYPATH=backend $PYTHON -m mypy backend/app | tee artifacts/generated/mypy.log
$PYTHON scripts/generate_openapi_types.py --check
docker run --rm --platform linux/amd64 \
  -v "$ROOT_DIR/frontend:/src:ro" node:22.14.0-alpine \
  sh -c 'cp -R /src /tmp/frontend && cd /tmp/frontend && npm ci --ignore-scripts >/dev/null && npm test && npm run build' \
  | tee artifacts/generated/frontend.log
git diff --check

echo "R20-R23 ACCEPTANCE: PASS"
