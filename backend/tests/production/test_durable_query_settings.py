from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.actions.schemas import SetQuerySettingsIndexHintAction
from app.adapters.contracts import IndexSpec, Namespace, QuerySettingsIndexHint
from app.adapters.fake import FakeDatabaseAdapter
from app.production.query_settings_durable import (
    DurableQuerySettingsDeploymentService,
    DurableQuerySettingsError,
)


@pytest.mark.asyncio
async def test_durable_query_setting_is_idempotent_exactly_reversible_and_human_safe(
    disposable_worker_database: str,
) -> None:
    engine = create_async_engine(disposable_worker_database)
    adapter = FakeDatabaseAdapter((Namespace("orders"),))
    await adapter.create_index(Namespace("orders"), IndexSpec("optimizer_owned", (("customer_id", 1),)))
    user, target = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users "
                "(id,created_at,updated_at,email,password_hash,role,status,failed_login_count) "
                "VALUES (:id,:now,:now,:email,'hash','OPERATOR','ACTIVE',0)"
            ),
            {"id": user, "now": now, "email": f"query-settings-{user}@example.test"},
        )
        await connection.execute(
            text(
                "INSERT INTO targets "
                "(id,created_at,updated_at,owner_user_id,name,deployment_mode,state,connection_label,is_active) "
                "VALUES (:id,:now,:now,:owner,:name,'FULL_AUTONOMOUS','ACTIVE','test',true)"
            ),
            {"id": target, "now": now, "owner": user, "name": f"target-{target}"},
        )
    action = SetQuerySettingsIndexHintAction(
        database="commerce",
        collection="orders",
        query_shape_hash="shape-owned",
        allowed_indexes=("optimizer_owned",),
    )
    service = DurableQuerySettingsDeploymentService(engine, adapter)
    try:
        first = await service.deploy(target_id=target, action=action, evidence_hash="evidence")
        repeated = await service.deploy(target_id=target, action=action, evidence_hash="evidence")
        assert first["id"] == repeated["id"] and repeated["status"] == "APPLIED"
        assert await adapter.get_query_settings_index_hint(Namespace("orders"), "shape-owned") == QuerySettingsIndexHint(("optimizer_owned",))

        rollback = await service.rollback(first["id"], evidence_hash="evidence")
        repeated_rollback = await service.rollback(first["id"], evidence_hash="evidence")
        assert rollback["status"] == repeated_rollback["status"] == "ROLLED_BACK"
        assert await adapter.get_query_settings_index_hint(Namespace("orders"), "shape-owned") is None

        await adapter.set_query_settings_index_hint(
            Namespace("orders"), "shape-human", QuerySettingsIndexHint(("_id_",))
        )
        human = SetQuerySettingsIndexHintAction(
            database="commerce",
            collection="orders",
            query_shape_hash="shape-human",
            allowed_indexes=("optimizer_owned",),
            previous_allowed_indexes=("_id_",),
        )
        with pytest.raises(DurableQuerySettingsError, match="HUMAN_QUERY_SETTINGS_PRESENT"):
            await service.deploy(target_id=target, action=human, evidence_hash="evidence-human")
        assert await adapter.get_query_settings_index_hint(Namespace("orders"), "shape-human") == QuerySettingsIndexHint(("_id_",))
    finally:
        await engine.dispose()
