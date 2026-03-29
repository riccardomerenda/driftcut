"""Tests for run output reporting."""

from pathlib import Path

from driftcut.config import (
    CorpusConfig,
    DriftcutConfig,
    ModelConfig,
    ModelsConfig,
    OutputConfig,
    SamplingConfig,
)
from driftcut.models import (
    BatchResult,
    DecisionMetrics,
    ModelResponse,
    PromptEvaluation,
    PromptResult,
    ResponseEvaluation,
    RunDecision,
)
from driftcut.reporting import save_run_outputs
from driftcut.runner import RunResult


def _config() -> DriftcutConfig:
    return DriftcutConfig(
        name="Report run",
        models=ModelsConfig(
            baseline=ModelConfig(provider="openai", model="gpt-4o"),
            candidate=ModelConfig(provider="anthropic", model="claude-haiku"),
        ),
        corpus=CorpusConfig(file=Path("prompts.csv")),
        sampling=SamplingConfig(batch_size_per_category=1, max_batches=2, min_batches=1),
        output=OutputConfig(save_json=True, save_html=True, save_examples=True),
    )


def test_save_run_outputs_writes_json_and_html(tmp_path: Path) -> None:
    config = _config()
    result = RunResult(config_name=config.name)
    prompt = PromptResult(
        prompt_id="p1",
        category="support",
        criticality="high",
        prompt_text="Help me",
        expected_output_type="free_text",
        baseline=ModelResponse(output="All good", latency_ms=100.0, cost_usd=0.01),
        candidate=ModelResponse(output="All good", latency_ms=80.0, cost_usd=0.005),
        evaluation=PromptEvaluation(
            baseline=ResponseEvaluation(passed=True, structure_valid=True),
            candidate=ResponseEvaluation(passed=True, structure_valid=True),
            candidate_failed=False,
            candidate_regressed=False,
            candidate_improved=False,
            schema_break=False,
        ),
    )
    result.batches.append(BatchResult(batch_number=1, results=[prompt]))
    result.cost.record(prompt)
    result.latency.record(prompt)
    result.final_decision = RunDecision(
        outcome="PROCEED",
        reason="Risk is low.",
        confidence=0.8,
        metrics=DecisionMetrics(prompts_evaluated=1, batches_evaluated=1),
    )
    result.decision_history.append(result.final_decision)

    config_path = tmp_path / "migration.yaml"
    config_path.write_text("name: test\n", encoding="utf-8")

    written = save_run_outputs(config_path, config, result)

    assert {path.name for path in written} == {"results.json", "report.html"}
    json_text = (tmp_path / "driftcut-results" / "results.json").read_text(encoding="utf-8")
    html_text = (tmp_path / "driftcut-results" / "report.html").read_text(encoding="utf-8")
    assert '"outcome": "PROCEED"' in json_text
    assert "Report run - Driftcut report" in html_text
