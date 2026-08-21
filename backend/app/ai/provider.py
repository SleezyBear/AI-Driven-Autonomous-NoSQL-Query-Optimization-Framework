"""Structured Ollama and fake AI providers with no database execution authority."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.isolation.lock import BenchmarkOllamaIsolationLock, shared_measurement_lock
from app.security.privacy import PrivacyBoundary, PrivacyMode


DEFAULT_AI_PROVIDER = "ollama"


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

    def __init__(self, client: httpx.AsyncClient, model: str, embedding_model: str, timeout_seconds: float = 30.0, isolation_lock: BenchmarkOllamaIsolationLock = shared_measurement_lock, privacy_boundary: PrivacyBoundary | None = None) -> None:
        self._client = client
        self._model = model
        self._embedding_model = embedding_model
        self._timeout_seconds = timeout_seconds
        self._isolation_lock = isolation_lock
        self._privacy_boundary = privacy_boundary or PrivacyBoundary(PrivacyMode.LOCAL_NORMALIZED)

    async def diagnose(self, evidence: str) -> Diagnosis:
        return await self._structured("Diagnose this deterministic evidence:\n" + evidence, Diagnosis)

    async def rank_candidates(self, candidate_summaries: tuple[str, ...]) -> CandidateRanking:
        return await self._structured("Rank these candidate summaries by ID only:\n" + "\n".join(candidate_summaries), CandidateRanking)

    async def explain_decision(self, decision: str) -> DecisionExplanation:
        return await self._structured("Explain this deterministic decision:\n" + decision, DecisionExplanation)

    async def embed_experience(self, experience: str) -> ExperienceEmbedding:
        async with self._isolation_lock.ollama_request():
            response = await self._client.post("/api/embed", json={"model": self._embedding_model, "input": self._privacy_boundary.sanitize_prompt_text(experience)}, timeout=self._timeout_seconds)
            response.raise_for_status()
            embeddings = response.json().get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != 1:
            raise ValueError("Ollama embedding response is malformed.")
        return ExperienceEmbedding(vector=tuple(embeddings[0]))

    async def _structured(self, prompt: str, output_type: type[StructuredOutput]) -> StructuredOutput:
        prompt = self._privacy_boundary.sanitize_prompt_text(prompt)
        for attempt in range(2):
            async with self._isolation_lock.ollama_request():
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


class OpenAICompatibleAIProvider(AIProvider):
    """OpenAI-compatible local HTTP provider with the same advisory-only contract as Ollama."""

    def __init__(self, client: httpx.AsyncClient, model: str, embedding_model: str, timeout_seconds: float = 30.0, isolation_lock: BenchmarkOllamaIsolationLock = shared_measurement_lock, privacy_boundary: PrivacyBoundary | None = None) -> None:
        self._client = client
        self._model = model
        self._embedding_model = embedding_model
        self._timeout_seconds = timeout_seconds
        self._isolation_lock = isolation_lock
        self._privacy_boundary = privacy_boundary or PrivacyBoundary(PrivacyMode.LOCAL_NORMALIZED)

    async def diagnose(self, evidence: str) -> Diagnosis:
        return await self._structured("Diagnose this deterministic evidence:\n" + evidence, Diagnosis)

    async def rank_candidates(self, candidate_summaries: tuple[str, ...]) -> CandidateRanking:
        return await self._structured("Rank these candidate summaries by ID only:\n" + "\n".join(candidate_summaries), CandidateRanking)

    async def explain_decision(self, decision: str) -> DecisionExplanation:
        return await self._structured("Explain this deterministic decision:\n" + decision, DecisionExplanation)

    async def embed_experience(self, experience: str) -> ExperienceEmbedding:
        payload = {"model": self._embedding_model, "input": self._privacy_boundary.sanitize_prompt_text(experience)}
        async with self._isolation_lock.ollama_request():
            response = await self._client.post("/v1/embeddings", json=payload, timeout=self._timeout_seconds)
            response.raise_for_status()
            data = response.json().get("data")
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict) or not isinstance(data[0].get("embedding"), list):
            raise ValueError("OpenAI-compatible embedding response is malformed.")
        return ExperienceEmbedding(vector=tuple(data[0]["embedding"]))

    async def _structured(self, prompt: str, output_type: type[StructuredOutput]) -> StructuredOutput:
        prompt = self._privacy_boundary.sanitize_prompt_text(prompt)
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        for attempt in range(2):
            async with self._isolation_lock.ollama_request():
                response = await self._client.post("/v1/chat/completions", json=payload, timeout=self._timeout_seconds)
                response.raise_for_status()
                choices = response.json().get("choices")
            if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    try:
                        return cast(StructuredOutput, output_type.model_validate(json.loads(message["content"])))
                    except (ValidationError, json.JSONDecodeError):
                        pass
            if attempt == 1:
                break
        raise ValueError("OpenAI-compatible provider returned malformed structured output twice.")


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
