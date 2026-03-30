"""Replay input models and loader for historical Driftcut backtests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from driftcut.config import DriftcutConfig
from driftcut.corpus import Corpus, PromptRecord
from driftcut.models import ModelResponse


class ReplayResponseInput(BaseModel):
    """Historical response payload for one side of a replay record."""

    output: str | None = None
    latency_ms: float | None = None
    cost_usd: float | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> ReplayResponseInput:
        if self.output is None and self.error is None:
            msg = "Either output or error is required"
            raise ValueError(msg)
        if self.latency_ms is not None and self.latency_ms < 0:
            msg = "latency_ms must be non-negative"
            raise ValueError(msg)
        if self.cost_usd is not None and self.cost_usd < 0:
            msg = "cost_usd must be non-negative"
            raise ValueError(msg)
        return self

    @property
    def has_latency(self) -> bool:
        return self.latency_ms is not None

    @property
    def has_cost(self) -> bool:
        return self.cost_usd is not None

    def to_model_response(
        self,
        *,
        prompt_id: str,
        side: str,
        require_latency: bool,
    ) -> ModelResponse:
        if require_latency and self.latency_ms is None:
            msg = f"Replay record {prompt_id} is missing {side}.latency_ms"
            raise ValueError(msg)
        return ModelResponse(
            output=self.output or "",
            latency_ms=self.latency_ms or 0.0,
            cost_usd=self.cost_usd or 0.0,
            error=self.error,
        )


class ReplayRecordInput(PromptRecord):
    """Canonical replay record with paired baseline and candidate outputs."""

    model_config = ConfigDict(extra="forbid")

    baseline: ReplayResponseInput
    candidate: ReplayResponseInput

    def to_prompt_record(self) -> PromptRecord:
        return PromptRecord(
            id=self.id,
            category=self.category,
            prompt=self.prompt,
            criticality=self.criticality,
            expected_output_type=self.expected_output_type,
            notes=self.notes,
            required_substrings=list(self.required_substrings),
            forbidden_substrings=list(self.forbidden_substrings),
            json_required_keys=list(self.json_required_keys),
            max_output_chars=self.max_output_chars,
        )


class ReplayPayload(BaseModel):
    """Versioned top-level replay payload."""

    format_version: Literal[1]
    records: list[ReplayRecordInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_records(self) -> ReplayPayload:
        if not self.records:
            msg = "Replay payload must contain at least one record"
            raise ValueError(msg)
        ids = [record.id for record in self.records]
        if len(ids) != len(set(ids)):
            msg = "Replay payload contains duplicate record ids"
            raise ValueError(msg)
        return self


@dataclass(frozen=True)
class ReplayPair:
    """Paired prompt metadata and historical outputs for replay."""

    prompt: PromptRecord
    baseline: ModelResponse
    candidate: ModelResponse


@dataclass
class ReplayDataset:
    """Validated replay dataset materialized into Driftcut-native types."""

    corpus: Corpus
    pairs_by_id: dict[str, ReplayPair]
    historical_metrics_present: dict[str, bool]

    def pair_for(self, prompt: PromptRecord) -> ReplayPair:
        try:
            return self.pairs_by_id[prompt.id]
        except KeyError as exc:
            msg = f"Replay record for prompt {prompt.id} is missing"
            raise KeyError(msg) from exc


def load_replay_dataset(path: Path, config: DriftcutConfig) -> ReplayDataset:
    """Load a canonical replay JSON file and materialize native replay objects."""
    with open(path, encoding="utf-8") as file_obj:
        raw: Any = json.load(file_obj)
    try:
        payload = ReplayPayload.model_validate(raw)
    except ValidationError as exc:
        msg = f"Replay input is invalid: {exc}"
        raise ValueError(msg) from exc

    prompt_records: list[PromptRecord] = []
    pairs_by_id: dict[str, ReplayPair] = {}
    historical_latency_present = True
    historical_cost_present = False

    for record in payload.records:
        prompt = record.to_prompt_record()
        prompt_records.append(prompt)

        if not record.baseline.has_latency or not record.candidate.has_latency:
            historical_latency_present = False
        if record.baseline.has_cost or record.candidate.has_cost:
            historical_cost_present = True

        baseline = record.baseline.to_model_response(
            prompt_id=record.id,
            side="baseline",
            require_latency=config.latency.track,
        )
        candidate = record.candidate.to_model_response(
            prompt_id=record.id,
            side="candidate",
            require_latency=config.latency.track,
        )
        pairs_by_id[prompt.id] = ReplayPair(
            prompt=prompt,
            baseline=baseline,
            candidate=candidate,
        )

    return ReplayDataset(
        corpus=Corpus(prompt_records),
        pairs_by_id=pairs_by_id,
        historical_metrics_present={
            "latency": historical_latency_present,
            "cost": historical_cost_present,
        },
    )
