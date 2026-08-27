"""R4 integration coverage against the actual PostgreSQL control plane."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import jwt
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

os.environ.setdefault("JWT_SIGNING_KEY", "r4-test-signing-key-that-is-long-enough")

from app.auth.security import PasswordService, Role  # noqa: E402
from app.db import models  # noqa: E402
from app.db.runtime import create_control_plane_engine  # noqa: E402
from app.main import app  # noqa: E402


PASSWORD = "correct horse battery staple"


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest_asyncio.fixture(autouse=True)
async def database_cleanup() -> None:
    engine = create_control_plane_engine()
    async with engine.begin() as connection:
        await connection.execute(delete(models.RefreshToken.__table__))
        await connection.execute(delete(models.AuditEvent.__table__).where(models.AuditEvent.event_type.like("AUTH_%")))
        await connection.execute(delete(models.User.__table__).where(models.User.email.like("r4-%@example.com")))
    yield
    async with engine.begin() as connection:
        await connection.execute(delete(models.RefreshToken.__table__))
        await connection.execute(delete(models.AuditEvent.__table__).where(models.AuditEvent.event_type.like("AUTH_%")))
        await connection.execute(delete(models.User.__table__).where(models.User.email.like("r4-%@example.com")))
    await engine.dispose()


async def create_user(email: str, *, status: str = "ACTIVE") -> str:
    engine = create_control_plane_engine()
    user_id = uuid4()
    now = datetime.now(timezone.utc)
    async with engine.begin() as connection:
        await connection.execute(models.User.__table__.insert().values(id=user_id, created_at=now, updated_at=now, email=email, password_hash=PasswordService().hash_password(PASSWORD), role="OPERATOR", status=status, failed_login_count=0))
    await engine.dispose()
    return str(user_id)


@pytest.mark.asyncio
async def test_login_rotation_logout_and_disabled_user(client: TestClient) -> None:
    user_id = await create_user("r4-login@example.com")
    login = client.post("/auth/login", json={"email": "r4-login@example.com", "password": PASSWORD})
    assert login.status_code == 200
    payload = login.json()
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {payload['access_token']}"}).json()["user_id"] == user_id
    # A fresh application lifespan models a process restart: the configured
    # signer remains stable, while no generated in-memory key is involved.
    with TestClient(app) as restarted_client:
        assert restarted_client.get("/auth/me", headers={"Authorization": f"Bearer {payload['access_token']}"}).status_code == 200
    rotated = client.post("/auth/refresh", json={"refresh_token": payload["refresh_token"]})
    assert rotated.status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": payload["refresh_token"]}).status_code == 401
    assert client.post("/auth/logout", json={"refresh_token": rotated.json()["refresh_token"]}).status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]}).status_code == 401
    engine = create_control_plane_engine()
    async with engine.begin() as connection:
        await connection.execute(update(models.User.__table__).where(models.User.id == UUID(user_id)).values(status="DISABLED"))
    await engine.dispose()
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {rotated.json()['access_token']}"}).status_code == 401


@pytest.mark.asyncio
async def test_expired_or_refresh_token_cannot_access_and_five_failures_lock(client: TestClient) -> None:
    await create_user("r4-lock@example.com")
    now = datetime.now(timezone.utc)
    expired = jwt.encode({"sub": str(uuid4()), "role": Role.OPERATOR.value, "token_type": "access", "iat": now - timedelta(minutes=2), "exp": now - timedelta(minutes=1)}, os.environ["JWT_SIGNING_KEY"], algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    login = client.post("/auth/login", json={"email": "r4-lock@example.com", "password": PASSWORD}).json()
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {login['refresh_token']}"}).status_code == 401
    for _ in range(5):
        assert client.post("/auth/login", json={"email": "r4-lock@example.com", "password": "not-the-correct-password"}).status_code == 401
    assert client.post("/auth/login", json={"email": "r4-lock@example.com", "password": PASSWORD}).status_code == 401
