"""Phase 17 acceptance tests for append-only hash chaining."""

from dataclasses import replace

from app.ledger.chain import AppendOnlyLedger, GENESIS_HASH


def _append(ledger: AppendOnlyLedger, name: str) -> None:
    ledger.append({"index": name}, {"index": name}, {"index": name}, {"type": "CREATE_INDEX"}, {"type": "DROP_INDEX"}, "evidence-hash", "operator-1")


def test_append_only_entries_include_required_evidence_and_chain() -> None:
    ledger = AppendOnlyLedger()
    _append(ledger, "first")
    _append(ledger, "second")

    first, second = ledger.entries
    assert first.previous_ledger_hash == GENESIS_HASH
    assert second.previous_ledger_hash == first.current_ledger_hash
    assert first.created_at.tzinfo is not None
    assert AppendOnlyLedger.verify(ledger.entries)


def test_tampering_with_recorded_state_is_detected() -> None:
    ledger = AppendOnlyLedger()
    _append(ledger, "first")
    tampered = replace(ledger.entries[0], after_state={"index": "tampered"})

    assert not AppendOnlyLedger.verify((tampered,))
