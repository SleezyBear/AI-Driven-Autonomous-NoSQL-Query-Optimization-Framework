"""Canonical SHA-256 hash-chained action ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4


GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class LedgerEntry:
    """Immutable evidence for one production-relevant intended action."""

    entry_id: str
    created_at: datetime
    before_state: Mapping[str, Any]
    intended_state: Mapping[str, Any]
    after_state: Mapping[str, Any]
    forward_action: Mapping[str, Any]
    inverse_action: Mapping[str, Any]
    evidence_hash: str
    actor: str
    previous_ledger_hash: str
    current_ledger_hash: str


class AppendOnlyLedger:
    """Append entries only and detect any history tampering by recomputing the chain."""

    def __init__(self) -> None:
        self._entries: tuple[LedgerEntry, ...] = ()

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        """Expose an immutable sequence of ledger evidence."""
        return self._entries

    def append(
        self,
        before_state: Mapping[str, Any],
        intended_state: Mapping[str, Any],
        after_state: Mapping[str, Any],
        forward_action: Mapping[str, Any],
        inverse_action: Mapping[str, Any],
        evidence_hash: str,
        actor: str,
    ) -> LedgerEntry:
        """Append a canonical, hash-linked entry without a mutation API."""
        previous_hash = self._entries[-1].current_ledger_hash if self._entries else GENESIS_HASH
        entry = LedgerEntry(
            entry_id=str(uuid4()),
            created_at=datetime.now(timezone.utc),
            before_state=_freeze_mapping(before_state),
            intended_state=_freeze_mapping(intended_state),
            after_state=_freeze_mapping(after_state),
            forward_action=_freeze_mapping(forward_action),
            inverse_action=_freeze_mapping(inverse_action),
            evidence_hash=evidence_hash,
            actor=actor,
            previous_ledger_hash=previous_hash,
            current_ledger_hash="",
        )
        entry = LedgerEntry(**{**entry.__dict__, "current_ledger_hash": self._hash(entry)})
        self._entries += (entry,)
        return entry

    @staticmethod
    def verify(entries: tuple[LedgerEntry, ...]) -> bool:
        """Return false for broken links or altered canonical entry content."""
        previous_hash = GENESIS_HASH
        for entry in entries:
            if entry.previous_ledger_hash != previous_hash or entry.current_ledger_hash != AppendOnlyLedger._hash(entry):
                return False
            previous_hash = entry.current_ledger_hash
        return True

    @staticmethod
    def _hash(entry: LedgerEntry) -> str:
        payload = {
            "entry_id": entry.entry_id,
            "created_at": entry.created_at.astimezone(timezone.utc).isoformat(),
            "before_state": entry.before_state,
            "intended_state": entry.intended_state,
            "after_state": entry.after_state,
            "forward_action": entry.forward_action,
            "inverse_action": entry.inverse_action,
            "evidence_hash": entry.evidence_hash,
            "actor": entry.actor,
            "previous_ledger_hash": entry.previous_ledger_hash,
        }
        serialized = json.dumps(payload, default=dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Copy JSON-shaped state so later caller mutation cannot change ledger evidence."""
    copied = json.loads(json.dumps(value, sort_keys=True))
    return MappingProxyType(_freeze_value(copied))


def _freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    return value
