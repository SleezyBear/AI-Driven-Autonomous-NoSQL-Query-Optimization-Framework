"""Recommendation-only query rewrites guarded by sandbox result equivalence."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class QueryRewriteStatus(str, Enum):
    """The only possible outcomes for a query-rewrite proposal."""

    RECOMMENDED = "RECOMMENDED"
    REJECTED_SAFETY_INVARIANT = "REJECTED_SAFETY_INVARIANT"


@dataclass(frozen=True)
class ResultDocument:
    """One result with a stable document identity and literal-safe canonical hash."""

    document_identity: str
    canonical_hash: str

    @classmethod
    def from_document(cls, document_identity: str, document: Mapping[str, object]) -> ResultDocument:
        """Hash a canonical document representation without retaining the document itself."""
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str)
        return cls(document_identity, hashlib.sha256(encoded.encode("utf-8")).hexdigest())


@dataclass(frozen=True)
class QueryResult:
    """A sandbox result whose ordering requirement is explicit evidence."""

    documents: tuple[ResultDocument, ...]
    ordering_required: bool


@dataclass(frozen=True)
class QueryRewriteRecommendation:
    """An advisory outcome; it contains no database command or mutation capability."""

    status: QueryRewriteStatus
    proposed_rewrite: str
    reason_codes: tuple[str, ...]


class QueryRewriteAdvisor:
    """Recommend a rewrite only after strict baseline/sandbox equivalence."""

    def recommend(
        self, proposed_rewrite: str, baseline: QueryResult, sandbox: QueryResult
    ) -> QueryRewriteRecommendation:
        """Return an advisory recommendation or the required safety-invariant rejection."""
        mismatches = _equivalence_mismatches(baseline, sandbox)
        if mismatches:
            return QueryRewriteRecommendation(
                QueryRewriteStatus.REJECTED_SAFETY_INVARIANT, proposed_rewrite, mismatches
            )
        return QueryRewriteRecommendation(QueryRewriteStatus.RECOMMENDED, proposed_rewrite, ())


def _equivalence_mismatches(baseline: QueryResult, sandbox: QueryResult) -> tuple[str, ...]:
    failures: list[str] = []
    if len(baseline.documents) != len(sandbox.documents):
        failures.append("COUNT_MISMATCH")
    if Counter(item.document_identity for item in baseline.documents) != Counter(
        item.document_identity for item in sandbox.documents
    ):
        failures.append("DOCUMENT_IDENTITY_MISMATCH")
    if Counter(item.canonical_hash for item in baseline.documents) != Counter(
        item.canonical_hash for item in sandbox.documents
    ):
        failures.append("CANONICAL_HASH_MISMATCH")
    if baseline.ordering_required != sandbox.ordering_required:
        failures.append("ORDERING_SEMANTICS_MISMATCH")
    elif baseline.ordering_required and baseline.documents != sandbox.documents:
        failures.append("ORDERING_MISMATCH")
    return tuple(failures)
