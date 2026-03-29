"""Result models for migration execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ModelResponse:
    """Raw response from a single model call."""

    output: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_error: str | None = None
    error: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


@dataclass
class ResponseEvaluation:
    """Deterministic quality assessment for one model response."""

    passed: bool
    structure_valid: bool
    reasons: list[str] = field(default_factory=list)
    archetype: str | None = None


@dataclass
class PromptEvaluation:
    """Deterministic quality comparison for one prompt."""

    baseline: ResponseEvaluation
    candidate: ResponseEvaluation
    candidate_failed: bool
    candidate_regressed: bool
    candidate_improved: bool
    schema_break: bool


@dataclass
class DecisionMetrics:
    """Aggregated metrics used for run-level decisions."""

    prompts_evaluated: int = 0
    batches_evaluated: int = 0
    structured_prompts: int = 0
    high_criticality_prompts: int = 0
    candidate_failure_rate: float = 0.0
    candidate_regression_rate: float = 0.0
    schema_break_rate: float = 0.0
    high_criticality_failure_rate: float = 0.0
    overall_risk: float = 0.0
    latency_p50_ratio: float = 1.0
    latency_p95_ratio: float = 1.0
    archetypes: dict[str, int] = field(default_factory=dict)


@dataclass
class RunDecision:
    """Decision snapshot after one or more sampled batches."""

    outcome: Literal["STOP", "CONTINUE", "PROCEED"]
    reason: str
    confidence: float
    metrics: DecisionMetrics


@dataclass
class PromptResult:
    """Comparison result for one prompt across baseline and candidate."""

    prompt_id: str
    category: str
    criticality: str
    prompt_text: str
    expected_output_type: str
    baseline: ModelResponse
    candidate: ModelResponse
    notes: str = ""
    required_substrings: list[str] = field(default_factory=list)
    forbidden_substrings: list[str] = field(default_factory=list)
    json_required_keys: list[str] = field(default_factory=list)
    max_output_chars: int | None = None
    evaluation: PromptEvaluation | None = None


@dataclass
class BatchResult:
    """Aggregated results for a single batch."""

    batch_number: int
    results: list[PromptResult] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.results)

    @property
    def baseline_errors(self) -> int:
        return sum(1 for r in self.results if r.baseline.is_error)

    @property
    def candidate_errors(self) -> int:
        return sum(1 for r in self.results if r.candidate.is_error)

    @property
    def total_cost_usd(self) -> float:
        return sum(r.baseline.cost_usd + r.candidate.cost_usd for r in self.results)

    @property
    def total_latency_ms(self) -> float:
        return sum(r.baseline.latency_ms + r.candidate.latency_ms for r in self.results)
