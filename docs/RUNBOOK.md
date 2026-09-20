# Runbook

Phase 0 bootstrap: `./scripts/bootstrap.sh`.

## Local control-plane master key

Generate the development-only secret outside version control:

```bash
mkdir -p .secrets
./nosql/bin/python scripts/generate_master_key.py \
  --output .secrets/control_plane_master_key
```

Docker Compose mounts this file into the API and worker containers as
`/run/secrets/control_plane_master_key`. Do not create `/run/secrets` on the macOS host and never put this key in `.env` or PostgreSQL.

## Local MongoDB replica-set key

MongoDB requires an internal key file when replica sets use authorization. Generate the ignored development-only key once:

```bash
./nosql/bin/python scripts/generate_mongodb_keyfile.py \
  --output .secrets/mongodb_replica_keyfile
```

Compose securely copies this key inside each MongoDB container before `mongod` starts.

## R20–R23 qualification

Run the complete hardening gate from the repository root:

```bash
make r20r23-acceptance
```

The target creates a unique Compose project plus individually named disposable
PostgreSQL and MongoDB containers. It never uses named development volumes and
its cleanup intentionally omits `-v`. Do not modify it to use `docker compose
down -v`, a volume/system prune, development databases, or human-owned MongoDB
namespaces.

Generated evidence is written under ignored `artifacts/generated/`:

- `backend.cdx.json` and `frontend.cdx.json`: CycloneDX 1.5 inventories;
- `provenance.json`: revision, dirty state, tool versions, lock hashes, and
  build commands;
- `backend-tests.log`, `frontend.log`, and `mypy.log`: final regression output.

## Production startup contract

Production operators must set `APP_ENV=production` and explicitly supply:

- a non-development `DATABASE_URL` using PostgreSQL/asyncpg;
- `JWT_SIGNING_KEY` with at least 32 characters and no example/dev marker;
- `CONTROL_PLANE_MASTER_KEY_FILE` naming a readable, externally provisioned,
  exact 32-byte AES key;
- concrete non-wildcard `ALLOWED_HOSTS`;
- concrete non-wildcard HTTPS `CORS_ALLOWED_ORIGINS`.

The service does not generate production secrets. Missing or unsafe values stop
startup. Keep the API behind a reverse proxy and preserve the configured
forwarded-IP trust boundary; the shipped Uvicorn command trusts proxy headers
only from `127.0.0.1`. `/health/live` is a process probe, `/health/ready` is the
PostgreSQL dependency probe, and `/metrics` exposes bounded-label Prometheus
metrics. A target-specific MongoDB outage does not by itself make the entire
control-plane API unready.

## PostgreSQL capacity and migrations

Pool limits apply to every API and worker process. Calculate the worst case
before scaling:

```text
per_process = POSTGRES_POOL_SIZE + POSTGRES_MAX_OVERFLOW
total_application = (api_processes + worker_processes) * per_process
```

Defaults are 5 pooled + 5 overflow = 10 per process. For two API and two worker
processes, reserve 40 application connections. Ensure `total_application`, one
migration connection, monitoring connections, and an administration/recovery
reserve remain below PostgreSQL `max_connections`. Do not use overflow capacity
as the normal steady state.

Other defaults are a 30-second pool wait, 1,800-second recycle, 10-second
connect timeout, 60-second statement timeout, and 5-second lock timeout. Tune
only from measured operational evidence and update the budget when scaling.

Run upgrades as a dedicated deployment step:

```bash
./nosql/bin/python -m alembic -c backend/alembic.ini upgrade head
```

Alembic serializes runners with a PostgreSQL session advisory lock and
`MIGRATION_LOCK_TIMEOUT_SECONDS` (default 120). Never auto-downgrade migration
`0019`; its reversal needs an approved maintenance plan. Keep PostgreSQL
transactions short: no transaction may span AI inference, a benchmark, a Mongo
mutation, a monitoring wait, or a human approval wait.

Before a production upgrade, take a PostgreSQL custom-format backup to an
operator-controlled encrypted destination. Restore it into a new database—not
over the live or development database—and verify Alembic head, foreign-key
integrity, job/run identities, immutable fingerprints, and the production
ledger hash chain before promotion. `scripts/r22_postgres_acceptance.py`
automates this drill only against a guarded disposable container.

During a PostgreSQL outage, expect API readiness to return 503 and workers to
stop authoritative claims/progress. Restore service, confirm readiness and
worker health recover, verify durable job/run counts and ledger integrity, then
resume traffic. Never fabricate lifecycle progress while PostgreSQL is absent.

## MongoDB production connections and recovery

Construct production clients only through `app.mongodb.client`. Production
rejects `directConnection=true` and development credentials, requires TLS, and
keeps certificate and hostname verification enabled. Configure a trusted CA via
`MONGO_TLS_CA_FILE` and, when mutual TLS is required, the client key/certificate
via `MONGO_TLS_CERTIFICATE_KEY_FILE`. Never use invalid-certificate or
invalid-hostname bypasses.

Default client bounds are 5-second selection/connect, 30-second socket,
0–20 pooled connections, a 10-second wait queue, and 60-second idle lifetime.
Close clients only when their owning process/component shuts down; reuse them
within that lifetime. The read-only target probe may discover topology, primary,
server version, FCV, and query-settings capability, but must not write
application documents.

For an outage/election, allow the topology-aware driver to rediscover a primary,
then re-probe capabilities and reconcile the persisted action/effect before any
retry. The executor identity must remain unable to write application documents,
drop collections/databases, or change unrelated server configuration. Confirm
the existing durable action marker/ledger before retrying so an observed effect
is not duplicated. `scripts/r23_mongodb_acceptance.py` exercises TLS,
authorization, election, outage, restart, and reconciliation only in disposable
MongoDB containers.
