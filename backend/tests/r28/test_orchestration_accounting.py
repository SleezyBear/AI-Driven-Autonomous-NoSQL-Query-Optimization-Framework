"""R28: fail-closed orchestration accounting and authoritative interpreter use."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.orchestration import (
    AUTHORITATIVE_PYTHON_RELATIVE,
    INVALID_CLASSIFICATION,
    Constituent,
    ConstituentState,
    authoritative_python,
    is_authoritative_interpreter,
    is_authoritative_pass,
    overall_status,
    provision_bench_environment,
    require_environment,
    status_for_returncode,
)

ROOT = Path(__file__).resolve().parents[3]


def _constituent(name: str, status: ConstituentState, *, required: bool = True) -> Constituent:
    return Constituent(name=name, kind="test", required=required, status=status)


def test_nonzero_return_code_is_failed_even_with_evidence() -> None:
    assert status_for_returncode(1, evidence_present=True) is ConstituentState.FAILED
    assert status_for_returncode(0, evidence_present=True) is ConstituentState.PASSED
    assert status_for_returncode(0, evidence_present=False) is ConstituentState.FAILED


def test_top_level_fails_when_a_required_constituent_fails() -> None:
    constituents = [
        _constituent("ok", ConstituentState.PASSED),
        _constituent("failed", ConstituentState.FAILED),
    ]
    assert overall_status(constituents) is ConstituentState.FAILED


def test_overall_passes_only_when_all_required_constituents_pass() -> None:
    assert overall_status([_constituent("a", ConstituentState.PASSED), _constituent("b", ConstituentState.PASSED)]) is ConstituentState.PASSED
    assert overall_status([_constituent("a", ConstituentState.RUNNING)]) is ConstituentState.RUNNING
    assert overall_status([_constituent("a", ConstituentState.PENDING)]) is ConstituentState.RUNNING


def test_invalid_evidence_is_never_an_authoritative_pass() -> None:
    assert is_authoritative_pass({"status": "PASSED"}) is True
    assert is_authoritative_pass({"status": "FAILED"}) is False
    assert is_authoritative_pass({"status": "PASSED", "classification": INVALID_CLASSIFICATION}) is False
    assert overall_status([_constituent("a", ConstituentState.INVALID)]) is ConstituentState.FAILED


def test_authoritative_interpreter_is_project_owned() -> None:
    interpreter = authoritative_python(ROOT)
    assert interpreter == str(ROOT / AUTHORITATIVE_PYTHON_RELATIVE)
    assert interpreter.endswith("nosql/bin/python")
    assert ".venv_r28" not in interpreter


def test_ephemeral_interpreter_is_not_authoritative() -> None:
    assert is_authoritative_interpreter([".venv_r28/bin/python", "scripts/x.py"]) is False
    assert is_authoritative_interpreter(["./nosql/bin/python", "scripts/x.py"]) is True


def test_missing_required_environment_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="fail-closed"):
        require_environment({})
    with pytest.raises(RuntimeError, match="fail-closed"):
        require_environment({"JWT_SIGNING_KEY": ""})


def test_provisioned_environment_is_disposable_and_complete(tmp_path: Path) -> None:
    environment = provision_bench_environment(secret_dir=tmp_path)
    require_environment(environment)
    assert environment["JWT_SIGNING_KEY"]
    assert (tmp_path / "control_plane_master_key").exists()
    assert (tmp_path / "mongodb_replica_keyfile").exists()
