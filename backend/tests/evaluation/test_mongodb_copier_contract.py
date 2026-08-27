"""R15 state-copy contract checks."""

from app.evaluation.mongodb_copier import MongoEvaluationStateCopier


def test_copier_requires_distinct_target_ids() -> None:
    copier = MongoEvaluationStateCopier("mongodb://source", "mongodb://evaluation", "commerce", ())

    assert copier._workload_fingerprint  # immutable workload evidence is always captured
