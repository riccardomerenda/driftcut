"""Configuration models and YAML loader for Driftcut."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    provider: str
    model: str
    api_key: str | None = None


class ModelsConfig(BaseModel):
    baseline: ModelConfig
    candidate: ModelConfig


class CorpusConfig(BaseModel):
    file: Path


class SamplingConfig(BaseModel):
    batch_size_per_category: int = Field(default=3, ge=1)
    max_batches: int = Field(default=5, ge=1)
    min_batches: int = Field(default=2, ge=1)


class RiskConfig(BaseModel):
    high_criticality_weight: float = Field(default=2.0, gt=0)
    stop_on_schema_break_rate: float = Field(default=0.25, ge=0, le=1)
    stop_on_high_criticality_failure_rate: float = Field(default=0.20, ge=0, le=1)
    proceed_if_overall_risk_below: float = Field(default=0.08, ge=0, le=1)


class EvaluationConfig(BaseModel):
    judge_strategy: Literal["none", "light", "tiered", "heavy"] = "tiered"
    judge_model_light: str = "openai/gpt-4.1-mini"
    judge_model_heavy: str = "openai/gpt-4.1"
    detect_failure_archetypes: bool = True


class LatencyConfig(BaseModel):
    track: bool = True
    regression_threshold_p50: float = Field(default=1.5, gt=0)
    regression_threshold_p95: float = Field(default=2.0, gt=0)


class OutputConfig(BaseModel):
    save_json: bool = True
    save_html: bool = True
    save_examples: bool = True
    show_thresholds: bool = True
    show_confidence: bool = True


class DriftcutConfig(BaseModel):
    name: str
    description: str = ""
    models: ModelsConfig
    corpus: CorpusConfig
    sampling: SamplingConfig = SamplingConfig()
    risk: RiskConfig = RiskConfig()
    evaluation: EvaluationConfig = EvaluationConfig()
    latency: LatencyConfig = LatencyConfig()
    output: OutputConfig = OutputConfig()


def load_config(path: Path) -> DriftcutConfig:
    """Load and validate a Driftcut config from a YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        msg = f"Config file must contain a YAML mapping, got {type(raw).__name__}"
        raise ValueError(msg)
    return DriftcutConfig(**raw)
