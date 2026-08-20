"""Structured Ollama and fake AI providers with no database execution authority."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StructuredOutput(BaseModel):
    """Strict output base: providers may return analysis, never executable commands."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Diagnosis(StructuredOutput):
    summary: str = Field(min_length=1)
    evidence: tuple[str, ...]


class CandidateRanking(StructuredOutput):
    candidate_ids: tuple[str, ...]
    rationale: str = Field(min_length=1)


class DecisionExplanation(StructuredOutput):
    explanation: str = Field(min_length=1)


class ExperienceEmbedding(StructuredOutput):
    vector: tuple[float, ...] = Field(min_length=1)


class AIProvider(ABC):
    """Typed advisory interface; it exposes no database credentials or execution method."""

    @abstractmethod
    async def diagnose(self, evidence: str) -> Diagnosis:
        """Return structured diagnostic analysis."""

    @abstractmethod
    async def rank_candidates(self, candidate_summaries: tuple[str, ...]) -> CandidateRanking:
        """Return a structured ranking of already-generated candidate IDs."""

    @abstractmethod
    async def explain_decision(self, decision: str) -> DecisionExplanation:
        """Return a structured explanation of a deterministic decision."""

    @abstractmethod
    async def embed_experience(self, experience: str) -> ExperienceEmbedding:
        """Return a numeric embedding for experience retrieval only."""


class OllamaAIProvider(AIProvider):
    """Ollama HTTP provider that requests strict JSON at temperature zero."""

    def __init__(self, client: httpx.AsyncClient, model: str, embedding_model: str, timeout_seconds: float = 30.0) -> None:
        self._client = client
        self._model = model
        self._embedding_model = embedding_model
        self._timeout_seconds = timeout_seconds

    async def diagnose(self, evidence: str) -> Diagnosis:
        return await self._structured("Diagnose this deterministic evidence:\n" + evidence, Diagnosis)

    async def rank_candidates(self, candidate_summaries: tuple[str, ...]) -> CandidateRanking:
        return await self._structured("Rank these candidate summaries by ID only:\n" + "\n".join(candidate_summaries), CandidateRanking)

    async def explain_decision(self, decision: str) -> DecisionExplanation:
        return await self._structured("Explain this deterministic decision:\n" + decision, DecisionExplanation)

    async def embed_experience(self, experience: str) -> ExperienceEmbedding:
        response = await self._client.post("/api/embed", json={"model": self._embedding_model, "input": experience}, timeout=self._timeout_seconds)
        response.raise_for_status()
        embeddings = response.json().get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != 1:
            raise ValueError("Ollama embedding response is malformed.")
        return ExperienceEmbedding(vector=tuple(embeddings[0]))

    async def _structured(self, prompt: str, output_type: type[StructuredOutput]) -> StructuredOutput:
        for attempt in range(2):
            response = await self._client.post("/api/generate", json={"model": self._model, "prompt": prompt, "stream": False, "format": "json", "options": {"temperature": 0}}, timeout=self._timeout_seconds)
            response.raise_for_status()
            raw_output = response.json().get("response")
            if isinstance(raw_output, str):
                try:
                    return cast(StructuredOutput, output_type.model_validate(json.loads(raw_output)))
                except (ValidationError, json.JSONDecodeError):
                    pass
            if attempt == 1:
                break
        raise ValueError("Ollama returned malformed structured output twice.")


class FakeAIProvider(AIProvider):
    """Deterministic structured provider for unit tests and offline development."""

    async def diagnose(self, evidence: str) -> Diagnosis:
        return Diagnosis(summary="fake diagnosis", evidence=(evidence,))

    async def rank_candidates(self, candidate_summaries: tuple[str, ...]) -> CandidateRanking:
        return CandidateRanking(candidate_ids=tuple(sorted(candidate_summaries)), rationale="deterministic fake ranking")

    async def explain_decision(self, decision: str) -> DecisionExplanation:
        return DecisionExplanation(explanation="fake explanation: " + decision)

    async def embed_experience(self, experience: str) -> ExperienceEmbedding:
        return ExperienceEmbedding(vector=(float(len(experience)),))
