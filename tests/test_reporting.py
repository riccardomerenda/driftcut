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
    CategoryScore,
    DecisionMetrics,
    JudgeResult,
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
    result = RunResult(config_name=config.name, memory_backend="redis")
    result.baseline_cache_hits = 1
    prompt = PromptResult(
        prompt_id="p1",
        category="support",
        criticality="high",
        prompt_text="Help me",
        expected_output_type="free_text",
        baseline=ModelResponse(
            output="All good",
            latency_ms=0.0,
            retry_count=0,
            cost_usd=0.0,
            cache_hit=True,
            historical_latency_ms=100.0,
            historical_cost_usd=0.01,
        ),
        candidate=ModelResponse(output="All good", latency_ms=80.0, retry_count=2, cost_usd=0.005),
        evaluation=PromptEvaluation(
            baseline=ResponseEvaluation(passed=True, structure_valid=True),
            candidate=ResponseEvaluation(passed=True, structure_valid=True),
            candidate_failed=False,
            candidate_regressed=False,
            candidate_improved=False,
            schema_break=False,
            needs_judge=True,
            judge=JudgeResult(
                model="openai/gpt-4.1-mini",
                verdict="equivalent",
                confidence=0.9,
                rationale="Both answers solve the same task.",
                cost_usd=0.002,
            ),
        ),
    )
    result.batches.append(BatchResult(batch_number=1, results=[prompt]))
    result.cost.record(prompt)
    result.latency.record(prompt)
    result.final_decision = RunDecision(
        outcome="PROCEED",
        reason="Risk is low.",
        confidence=0.8,
        metrics=DecisionMetrics(
            prompts_evaluated=1,
            batches_evaluated=1,
            ambiguous_prompts=1,
            judged_prompts=1,
            judge_average_confidence=0.9,
            category_scores=[
                CategoryScore(
                    category="support",
                    prompts_evaluated=1,
                    high_criticality_prompts=1,
                    judged_prompts=1,
                    overall_risk=0.04,
                    latency_p95_ratio=0.8,
                    archetypes={"semantic_regression": 1},
                )
            ],
        ),
    )
    result.decision_history.append(result.final_decision)

    config_path = tmp_path / "migration.yaml"
    config_path.write_text("name: test\n", encoding="utf-8")

    written = save_run_outputs(config_path, config, result)

    assert {path.name for path in written} == {"results.json", "report.html"}
    json_text = (tmp_path / "driftcut-results" / "results.json").read_text(encoding="utf-8")
    html_text = (tmp_path / "driftcut-results" / "report.html").read_text(encoding="utf-8")
    assert '"mode": "live"' in json_text
    assert '"outcome": "PROCEED"' in json_text
    assert '"memory_backend": "redis"' in json_text
    assert '"baseline_hits": 1' in json_text
    assert '"retry_count": 2' in json_text
    assert '"cache_hit": true' in json_text
    assert '"judge_usd": 0.002' in json_text
    assert '"baseline_cache_saved_usd": 0.01' in json_text
    assert '"verdict": "equivalent"' in json_text
    assert '"failure_archetypes": []' in json_text
    assert '"category_scores": [' in json_text
    assert '"tier": "light"' in json_text
    assert '"escalated": false' in json_text
    assert '"escalated_prompts": 0' in json_text
    assert "Report run - Driftcut report" in html_text
    assert "Live mode" in html_text
    assert "Category Scorecards" in html_text
    assert "support" in html_text
    assert "Judge cost: $0.0020" in html_text
    assert "Baseline cache saved: $0.0100" in html_text
    assert "Memory backend: redis" in html_text
    assert "Baseline cache: 1 hit(s) / 0 miss(es)" in html_text


def test_save_run_outputs_labels_replay_mode(tmp_path: Path) -> None:
    config = _config()
    result = RunResult(
        config_name=config.name,
        mode="replay",
        historical_metrics_present={"latency": True, "cost": True},
    )
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

    config_path = tmp_path / "replay.yaml"
    config_path.write_text("name: replay\n", encoding="utf-8")

    save_run_outputs(config_path, config, result)

    json_text = (tmp_path / "driftcut-results" / "results.json").read_text(encoding="utf-8")
    html_text = (tmp_path / "driftcut-results" / "report.html").read_text(encoding="utf-8")
    assert '"mode": "replay"' in json_text
    assert '"historical_metrics_present"' in json_text
    assert "Replay mode" in html_text
    assert "Historical model cost: $0.0150" in html_text
