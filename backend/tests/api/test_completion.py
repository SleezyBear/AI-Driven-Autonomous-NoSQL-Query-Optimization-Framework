"""Phase 44 acceptance tests for the versioned OpenAPI contract."""

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import ApiGroup
from app.main import app


ROOT = Path(__file__).resolve().parents[3]
client = TestClient(app)


@pytest.mark.parametrize("group", tuple(ApiGroup), ids=lambda group: group.value)
def test_every_required_api_group_has_a_truthful_read_only_endpoint(group: ApiGroup) -> None:
    response = client.get(f"/api/v1/{group.value}")

    assert response.status_code == 200
    assert response.json() == {"group": group.value, "status": "not_configured", "records": []}


def test_openapi_documents_every_required_group_and_generated_types_are_current() -> None:
    paths = app.openapi()["paths"]
    assert {f"/api/v1/{group.value}" for group in ApiGroup}.issubset(paths)

    result = subprocess.run(
        [sys.executable, "scripts/generate_openapi_types.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
