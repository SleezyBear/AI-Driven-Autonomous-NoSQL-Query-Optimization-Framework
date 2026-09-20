"""Disposable PostgreSQL migration, backup/restore, index, and outage acceptance."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.ledger.postgres import PostgresProductionLedger


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "pgvector/pgvector:pg17"
SAFE_CONTAINER = re.compile(r"^r20r23-pg-[a-f0-9]{12}$")


def _run(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, cwd=ROOT, check=check, text=True, capture_output=True)


async def _wait(port: int) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            connection = await asyncpg.connect(
                user="control_plane",
                password="r22_disposable_only",
                database="postgres",
                host="127.0.0.1",
                port=port,
                timeout=1,
            )
            await connection.close()
            return
        except (OSError, asyncpg.PostgresError, asyncio.TimeoutError):
            await asyncio.sleep(0.5)
    raise RuntimeError("disposable PostgreSQL did not become ready")


def _url(port: int, database: str) -> str:
    return (
        f"postgresql+asyncpg://control_plane:r22_disposable_only@127.0.0.1:{port}/{database}"
    )


async def _database(port: int, name: str) -> None:
    connection = await asyncpg.connect(
        user="control_plane",
        password="r22_disposable_only",
        database="postgres",
        host="127.0.0.1",
        port=port,
    )
    try:
        await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


def _migrate(url: str, revision: str = "head") -> None:
    environment = {**os.environ, "DATABASE_URL": url}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "backend/alembic.ini",
            "upgrade",
            revision,
        ],
        cwd=ROOT,
        env=environment,
        check=True,
    )


async def _exercise(container: str, port: int) -> None:
    for database in ("fresh", "prior", "concurrent", "source", "restored"):
        await _database(port, database)

    _migrate(_url(port, "fresh"))
    _migrate(_url(port, "prior"), "0018_approval_continuation")
    _migrate(_url(port, "prior"))

    concurrent_environment = {**os.environ, "DATABASE_URL": _url(port, "concurrent")}
    command = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        "backend/alembic.ini",
        "upgrade",
        "head",
    ]
    runners = [
        subprocess.Popen(command, cwd=ROOT, env=concurrent_environment) for _ in range(2)
    ]
    if any(runner.wait(timeout=180) != 0 for runner in runners):
        raise RuntimeError("concurrent migration runner failed")

    source_url = _url(port, "source")
    _migrate(source_url)
    engine = create_async_engine(source_url)
    user_id, approver_id, target_id, window_id, snapshot_id = (
        uuid4() for _ in range(5)
    )
    namespace_id, shape_id, run_id, candidate_id, action_id = (
        uuid4() for _ in range(5)
    )
    invocation_id, diagnosis_id, admission_id, approval_id, approval_decision_id = (
        uuid4() for _ in range(5)
    )
    deployment_id, rollback_id, experience_id, job_id = (uuid4() for _ in range(4))
    now = datetime.now(timezone.utc)
    snapshot_fingerprint = f"r22-snapshot-{snapshot_id.hex}"
    candidate_fingerprint = f"r22-candidate-{candidate_id.hex}"
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id,created_at,updated_at,email,password_hash,role,status,failed_login_count) "
                    "VALUES (:user,:now,:now,:email,'hash','OPERATOR','ACTIVE',0), "
                    "(:approver,:now,:now,:approver_email,'hash','ADMIN','ACTIVE',0)"
                ),
                {
                    "user": user_id,
                    "approver": approver_id,
                    "now": now,
                    "email": f"r22-{user_id.hex}@example.test",
                    "approver_email": f"r22-{approver_id.hex}@example.test",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO targets "
                    "(id,created_at,updated_at,owner_user_id,name,deployment_mode,state,connection_label,is_active) "
                    "VALUES (:id,:now,:now,:owner,:name,'APPROVAL_CONTROLLED','ACTIVE','r22-disposable',true)"
                ),
                {"id": target_id, "now": now, "owner": user_id, "name": f"r22-{target_id.hex}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO telemetry_windows "
                    "(id,created_at,updated_at,target_id,started_at,ended_at,source,status) "
                    "VALUES (:id,:now,:now,:target,:now,:now,'R22_RESTORE','COMPLETE')"
                ),
                {"id": window_id, "now": now, "target": target_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO workload_snapshots "
                    "(id,created_at,updated_at,target_id,telemetry_window_id,snapshot,fingerprint,completeness) "
                    "VALUES (:id,:now,:now,:target,:window,'{}',:fingerprint,'{}')"
                ),
                {
                    "id": snapshot_id,
                    "now": now,
                    "target": target_id,
                    "window": window_id,
                    "fingerprint": snapshot_fingerprint,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO namespaces (id,created_at,updated_at,target_id,name,allowlisted) "
                    "VALUES (:id,:now,:now,:target,'orders',true)"
                ),
                {"id": namespace_id, "now": now, "target": target_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO query_shapes "
                    "(id,created_at,updated_at,namespace_id,shape_hash,normalized_shape,operation) "
                    "VALUES (:id,:now,:now,:namespace,:hash,'{}','find')"
                ),
                {
                    "id": shape_id,
                    "now": now,
                    "namespace": namespace_id,
                    "hash": f"r22-shape-{shape_id.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO optimization_runs "
                    "(id,created_at,updated_at,target_id,workload_snapshot_id,status,requested_by_user_id,deployment_mode,primary_metric_key) "
                    "VALUES (:id,:now,:now,:target,:snapshot,'ROLLED_BACK',:user,'APPROVAL_CONTROLLED','p99')"
                ),
                {
                    "id": run_id,
                    "now": now,
                    "target": target_id,
                    "snapshot": snapshot_id,
                    "user": user_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO candidates "
                    "(id,created_at,updated_at,optimization_run_id,query_shape_id,status,candidate_hash,source_snapshot_id,deterministic_fingerprint,policy_classification) "
                    "VALUES (:id,:now,:now,:run,:shape,'ADMITTED',:hash,:snapshot,:fingerprint,'APPROVAL_REQUIRED')"
                ),
                {
                    "id": candidate_id,
                    "now": now,
                    "run": run_id,
                    "shape": shape_id,
                    "hash": f"r22-hash-{candidate_id.hex}",
                    "snapshot": snapshot_id,
                    "fingerprint": candidate_fingerprint,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO candidate_actions "
                    "(id,created_at,updated_at,candidate_id,action_type,action_payload,reversible) "
                    "VALUES (:id,:now,:now,:candidate,'CREATE_INDEX','{}',true)"
                ),
                {"id": action_id, "now": now, "candidate": candidate_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO ai_invocations "
                    "(id,created_at,updated_at,optimization_run_id,stage,provider,model,prompt_version,schema_version,workload_snapshot_id,input_hash,sanitized_input,status,attempt_number) "
                    "VALUES (:id,:now,:now,:run,'DIAGNOSIS','test','test','v1','v1',:snapshot,:hash,'{}','COMPLETED',1)"
                ),
                {
                    "id": invocation_id,
                    "now": now,
                    "run": run_id,
                    "snapshot": snapshot_id,
                    "hash": f"r22-input-{invocation_id.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO diagnosis_artifacts "
                    "(id,created_at,updated_at,optimization_run_id,workload_snapshot_id,target_id,ai_invocation_id,schema_version,source_snapshot_fingerprint,deterministic_evidence_hash,artifact_fingerprint) "
                    "VALUES (:id,:now,:now,:run,:snapshot,:target,:invocation,'v1',:source,:evidence,:fingerprint)"
                ),
                {
                    "id": diagnosis_id,
                    "now": now,
                    "run": run_id,
                    "snapshot": snapshot_id,
                    "target": target_id,
                    "invocation": invocation_id,
                    "source": snapshot_fingerprint,
                    "evidence": f"r22-evidence-{diagnosis_id.hex}",
                    "fingerprint": f"r22-diagnosis-{diagnosis_id.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO admission_decisions "
                    "(id,created_at,updated_at,candidate_id,verdict,evidence_hash) "
                    "VALUES (:id,:now,:now,:candidate,'ADMITTED',:evidence)"
                ),
                {
                    "id": admission_id,
                    "now": now,
                    "candidate": candidate_id,
                    "evidence": f"r22-admission-{admission_id.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO approval_requests "
                    "(id,created_at,updated_at,admission_decision_id,requested_by_user_id,status,action_id,target_id,candidate_id,evidence_hash,expires_at,optimization_run_id,candidate_fingerprint) "
                    "VALUES (:id,:now,:now,:admission,:user,'APPROVED',:action,:target,:candidate,:evidence,:expires,:run,:fingerprint)"
                ),
                {
                    "id": approval_id,
                    "now": now,
                    "admission": admission_id,
                    "user": user_id,
                    "action": str(action_id),
                    "target": target_id,
                    "candidate": candidate_id,
                    "evidence": f"r22-approval-{approval_id.hex}",
                    "expires": now + timedelta(minutes=15),
                    "run": run_id,
                    "fingerprint": candidate_fingerprint,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO approval_decisions "
                    "(id,created_at,updated_at,approval_request_id,decided_by_user_id,decision,reason) "
                    "VALUES (:id,:now,:now,:approval,:approver,'APPROVED','r22 restore drill')"
                ),
                {
                    "id": approval_decision_id,
                    "now": now,
                    "approval": approval_id,
                    "approver": approver_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO deployment_artifacts "
                    "(id,created_at,updated_at,optimization_run_id,candidate_id,candidate_fingerprint,action_fingerprint,idempotency_key,status,before_state,inverse_action,after_state) "
                    "VALUES (:id,:now,:now,:run,:candidate,:candidate_fingerprint,:action_fingerprint,:key,'ROLLED_BACK','{}','{}','{}')"
                ),
                {
                    "id": deployment_id,
                    "now": now,
                    "run": run_id,
                    "candidate": candidate_id,
                    "candidate_fingerprint": candidate_fingerprint,
                    "action_fingerprint": f"r22-action-{action_id.hex}",
                    "key": f"r22-deployment-{deployment_id.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO rollback_records "
                    "(id,created_at,updated_at,candidate_id,status,rollback_payload) "
                    "VALUES (:id,:now,:now,:candidate,'ROLLED_BACK','{}')"
                ),
                {"id": rollback_id, "now": now, "candidate": candidate_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO experience_records "
                    "(id,created_at,updated_at,candidate_id,outcome,evidence,actual_postdeploy_outcome,rollback_outcome) "
                    "VALUES (:id,:now,:now,:candidate,'ROLLED_BACK',CAST(:evidence AS jsonb),'REGRESSION','SUCCEEDED')"
                ),
                {
                    "id": experience_id,
                    "now": now,
                    "candidate": candidate_id,
                    "evidence": '{"monitoring":"regression","rollback":"verified"}',
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO jobs "
                    "(id,created_at,updated_at,optimization_run_id,payload,status,attempts,kind,available_at) "
                    "VALUES (:id,:now,:now,:run,'{}','PENDING',0,'ROLLBACK',:now)"
                ),
                {"id": job_id, "now": now, "run": run_id},
            )
        ledger = PostgresProductionLedger(engine)
        await ledger.append(
            target_id=target_id,
            run_id=run_id,
            candidate_id=candidate_id,
            action_id="r22-backup-probe",
            event_type="R22_BACKUP_PROBE",
            before_state={},
            intended_state={"index": "owned_probe"},
            after_state={"index": "owned_probe"},
            forward_action={"type": "CREATE_INDEX"},
            inverse_action={"type": "DROP_OWNED_INDEX"},
            evidence_hash="r22-evidence",
            actor="r22-acceptance",
        )
    finally:
        await engine.dispose()

    _run(
        "docker",
        "exec",
        container,
        "pg_dump",
        "-U",
        "control_plane",
        "-d",
        "source",
        "-Fc",
        "-f",
        "/tmp/r22.dump",
    )
    _run(
        "docker",
        "exec",
        container,
        "pg_restore",
        "-U",
        "control_plane",
        "-d",
        "restored",
        "--exit-on-error",
        "/tmp/r22.dump",
    )
    restored_url = _url(port, "restored")
    restored = create_async_engine(restored_url)
    try:
        if not await PostgresProductionLedger(restored).verify_target(target_id):
            raise RuntimeError("restored production ledger hash chain is invalid")
        async with restored.connect() as connection:
            restored_counts = {
                table: int(
                    await connection.scalar(text(f"SELECT count(*) FROM {table}")) or 0
                )
                for table in (
                    "optimization_runs",
                    "workload_snapshots",
                    "diagnosis_artifacts",
                    "candidates",
                    "approval_requests",
                    "deployment_artifacts",
                    "rollback_records",
                    "experience_records",
                    "jobs",
                )
            }
            restored_snapshot = await connection.scalar(
                text("SELECT fingerprint FROM workload_snapshots WHERE id=:id"),
                {"id": snapshot_id},
            )
            restored_candidate = await connection.scalar(
                text("SELECT deterministic_fingerprint FROM candidates WHERE id=:id"),
                {"id": candidate_id},
            )
            indexes = set(
                (
                    await connection.execute(
                        text(
                            "SELECT indexname FROM pg_indexes WHERE indexname IN "
                            "('ix_jobs_claim_pending','ix_jobs_claim_expired',"
                            "'ix_runs_requester_created','ix_approvals_status_expiry',"
                            "'ix_production_ledger_created')"
                        )
                    )
                ).scalars()
            )
            if (
                any(count != 1 for count in restored_counts.values())
                or restored_snapshot != snapshot_fingerprint
                or restored_candidate != candidate_fingerprint
                or len(indexes) != 5
            ):
                raise RuntimeError(
                    "restored artifact identity, fingerprint, or index verification failed"
                )
    finally:
        await restored.dispose()

    connection = await asyncpg.connect(
        user="control_plane",
        password="r22_disposable_only",
        database="restored",
        host="127.0.0.1",
        port=port,
    )
    state_before = await connection.fetchval("SELECT count(*) FROM jobs")
    await connection.close()
    _run("docker", "pause", container)
    outage_observed = False
    try:
        try:
            await asyncpg.connect(
                user="control_plane",
                password="r22_disposable_only",
                database="restored",
                host="127.0.0.1",
                port=port,
                timeout=1,
            )
        except (OSError, asyncpg.PostgresError, asyncio.TimeoutError):
            outage_observed = True
    finally:
        _run("docker", "unpause", container)
    if not outage_observed:
        raise RuntimeError("PostgreSQL outage was not observed")
    await _wait(port)
    recovered = await asyncpg.connect(
        user="control_plane",
        password="r22_disposable_only",
        database="restored",
        host="127.0.0.1",
        port=port,
    )
    try:
        if await recovered.fetchval("SELECT count(*) FROM jobs") != state_before:
            raise RuntimeError("durable state changed across PostgreSQL outage")
        maximum = int(await recovered.fetchval("SHOW max_connections"))
        if maximum < 20:
            raise RuntimeError("disposable server has an unusable connection budget")
    finally:
        await recovered.close()


async def main() -> int:
    container = f"r20r23-pg-{uuid4().hex[:12]}"
    if not SAFE_CONTAINER.fullmatch(container):
        raise RuntimeError("unsafe disposable container name")
    try:
        _run(
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container,
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_DB=postgres",
            "--env",
            "POSTGRES_USER=control_plane",
            "--env",
            "POSTGRES_PASSWORD=r22_disposable_only",
            IMAGE,
        )
        port_output = _run("docker", "port", container, "5432/tcp").stdout.strip()
        port = int(port_output.rsplit(":", 1)[-1])
        await _wait(port)
        await _exercise(container, port)
        print("R22 POSTGRESQL OPERATIONAL ACCEPTANCE: PASS")
        return 0
    finally:
        if SAFE_CONTAINER.fullmatch(container):
            _run("docker", "rm", "--force", container, check=False)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
