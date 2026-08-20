"""Phase 37 acceptance tests for sandbox-equivalent rewrite recommendations."""

from app.recommendations.query_rewrite import (
    QueryResult,
    QueryRewriteAdvisor,
    QueryRewriteStatus,
    ResultDocument,
)


def _result(*documents: ResultDocument, ordered: bool = False) -> QueryResult:
    return QueryResult(documents, ordered)


def _document(identity: str, amount: int) -> ResultDocument:
    return ResultDocument.from_document(identity, {"_id": identity, "amount": amount})


def test_recommends_only_for_equivalent_unordered_sandbox_results() -> None:
    baseline = _result(_document("a", 10), _document("b", 20))
    sandbox = _result(_document("b", 20), _document("a", 10))
    advisor = QueryRewriteAdvisor()

    recommendation = advisor.recommend("Use a covered projection", baseline, sandbox)

    assert recommendation.status is QueryRewriteStatus.RECOMMENDED
    assert recommendation.reason_codes == ()
    assert not hasattr(advisor, "apply")


def test_rejects_any_count_identity_or_canonical_hash_mismatch() -> None:
    baseline = _result(_document("a", 10), _document("b", 20))
    sandbox = _result(_document("a", 11))

    recommendation = QueryRewriteAdvisor().recommend("Use a covered projection", baseline, sandbox)

    assert recommendation.status is QueryRewriteStatus.REJECTED_SAFETY_INVARIANT
    assert set(recommendation.reason_codes) == {
        "COUNT_MISMATCH",
        "DOCUMENT_IDENTITY_MISMATCH",
        "CANONICAL_HASH_MISMATCH",
    }


def test_rejects_reordered_results_when_ordering_is_semantically_required() -> None:
    first, second = _document("a", 10), _document("b", 20)
    baseline = _result(first, second, ordered=True)
    sandbox = _result(second, first, ordered=True)

    recommendation = QueryRewriteAdvisor().recommend("Add deterministic sort", baseline, sandbox)

    assert recommendation.status is QueryRewriteStatus.REJECTED_SAFETY_INVARIANT
    assert recommendation.reason_codes == ("ORDERING_MISMATCH",)
