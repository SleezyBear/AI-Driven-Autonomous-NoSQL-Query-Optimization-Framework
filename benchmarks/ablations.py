"""R28 ablation execution wiring for the frozen B0-B5 matrix.

The frozen ``AblationConfiguration`` values live in
``app.ablations.experiments``.  This module is the missing runtime consumer:
it turns a mode into a concrete, executable candidate plan so B0-B5 differ in
the code path they execute rather than only in an experiment label.

B0 has no candidate.  B1/B3 select the frozen deterministic index.  B2/B4/B5
additionally consult the accepted LLM ranking boundary.  B3/B4/B5 enable the
frozen statistical admission gate.  B5 invokes accepted experience retrieval.
B1/B2 remain structurally sandbox-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from pymongo.database import Database

from app.ablations.experiments import ABLATION_CONFIGURATIONS, AblationConfiguration, AblationMode
from app.candidates.index_generator import DeterministicIndexGenerator, FindQueryShape

_MODE_TO_CONFIGURATION: dict[AblationMode, AblationConfiguration] = {
    configuration.mode: configuration for configuration in ABLATION_CONFIGURATIONS
}

_DATABASE_NAME = "commercebench"

_FROZEN_QUERY_SHAPES: tuple[tuple[str, str, tuple[str, ...], tuple[tuple[str, int], ...]], ...] = (
    # (label, collection, equality_fields, sort_fields) in frozen priority order.
    ("orders_by_customer", "orders", ("customer_id",), (("_id", -1),)),
    ("product_by_category", "products", ("category",), ()),
    ("inventory_by_product", "inventory", ("product_id",), ()),
)


@dataclass(frozen=True)
class PlannedIndex:
    """A concrete index the candidate arm may create."""

    label: str
    collection: str
    keys: tuple[tuple[str, int], ...]
    name: str

    @property
    def safe_summary(self) -> str:
        """Literal-free summary safe to send to the advisory ranking boundary."""
        fields = ", ".join(f"{field}:{direction}" for field, direction in self.keys)
        return f"CREATE_INDEX on collection {self.collection} with fields [{fields}]"


@dataclass(frozen=True)
class AblationPlan:
    """The executable semantics resolved for one frozen mode."""

    mode: AblationMode
    deterministic_candidates: bool
    llm_ranking: bool
    safety_gate: bool
    experience_memory: bool
    sandbox_only: bool
    candidates: tuple[PlannedIndex, ...]
    ranking_order: tuple[str, ...]
    experience_invoked: bool

    @property
    def selected_index(self) -> PlannedIndex | None:
        """The highest-ranked candidate, or ``None`` for the native baseline."""
        if not self.candidates:
            return None
        by_label = {candidate.label: candidate for candidate in self.candidates}
        for label in self.ranking_order:
            if label in by_label:
                return by_label[label]
        return self.candidates[0]


def configuration_for(mode: AblationMode) -> AblationConfiguration:
    """Return the frozen capability declaration for a mode."""
    try:
        return _MODE_TO_CONFIGURATION[mode]
    except KeyError as error:  # pragma: no cover - enum exhaustiveness guard
        raise ValueError(f"unknown ablation mode: {mode}") from error


def deterministic_candidates() -> tuple[PlannedIndex, ...]:
    """Generate the frozen deterministic candidate set via the accepted generator."""
    generator = DeterministicIndexGenerator()
    planned: list[PlannedIndex] = []
    for index, (label, collection, equality, sort) in enumerate(_FROZEN_QUERY_SHAPES, start=1):
        shape = FindQueryShape(
            query_shape_hash=f"commercebench:{label}",
            database=_DATABASE_NAME,
            collection=collection,
            equality_fields=equality,
            sort_fields=sort,
            range_fields=(),
        )
        for candidate in generator.generate(shape):
            action = candidate.action
            planned.append(
                PlannedIndex(
                    label=f"C{index}",
                    collection=action.collection,
                    keys=tuple((field.field, field.direction) for field in action.fields),
                    name=action.index_name,
                )
            )
    return tuple(planned)


def _validate_permutation(order: Iterable[str], candidates: tuple[PlannedIndex, ...]) -> tuple[str, ...]:
    candidates_order = tuple(order)
    labels = tuple(candidate.label for candidate in candidates)
    if sorted(candidates_order) != sorted(labels):
        raise ValueError("ranking must return each candidate handle exactly once")
    return candidates_order


def resolve_plan(
    mode: AblationMode,
    *,
    ranker: Callable[[tuple[PlannedIndex, ...]], Iterable[str]] | None = None,
    prioritize: Callable[[tuple[str, ...]], Iterable[str]] | None = None,
) -> AblationPlan:
    """Resolve a mode into concrete execution semantics.

    ``ranker`` is the LLM-assisted ranking boundary; ``prioritize`` is the
    accepted experience-memory boundary.  Both are optional so the plan can be
    constructed deterministically without external services.
    """
    configuration = configuration_for(mode)
    if not configuration.deterministic_candidates:
        return AblationPlan(
            mode=mode,
            deterministic_candidates=False,
            llm_ranking=False,
            safety_gate=configuration.safety_gate,
            experience_memory=False,
            sandbox_only=configuration.sandbox_only,
            candidates=(),
            ranking_order=(),
            experience_invoked=False,
        )
    candidates = deterministic_candidates()
    order = tuple(candidate.label for candidate in candidates)
    if configuration.llm_ranking and ranker is not None:
        order = _validate_permutation(ranker(candidates), candidates)
    experience_invoked = False
    if configuration.experience_memory and prioritize is not None:
        order = _validate_permutation(prioritize(order), candidates)
        experience_invoked = True
    return AblationPlan(
        mode=mode,
        deterministic_candidates=True,
        llm_ranking=configuration.llm_ranking,
        safety_gate=configuration.safety_gate,
        experience_memory=configuration.experience_memory,
        sandbox_only=configuration.sandbox_only,
        candidates=candidates,
        ranking_order=order,
        experience_invoked=experience_invoked,
    )


def candidate_setup_for(plan: AblationPlan) -> Callable[[Database], None] | None:
    """Build the candidate-arm setup callable, or ``None`` for the native mode."""
    selected = plan.selected_index
    if selected is None:
        return None

    def _setup(database: Database) -> None:
        database[selected.collection].create_index(list(selected.keys), name=selected.name)

    return _setup
