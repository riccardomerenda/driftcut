"""Result models for migration execution."""

from __future__ import annotations

from dataclasses import dataclass, field


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
class PromptResult:
    """Comparison result for one prompt across baseline and candidate."""

    prompt_id: str
    category: str
    criticality: str
    prompt_text: str
    expected_output_type: str
    baseline: ModelResponse
    candidate: ModelResponse


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
