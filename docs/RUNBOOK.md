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
