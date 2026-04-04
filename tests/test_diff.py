"""Tests for driftcut diff command and comparison logic."""

import json
from pathlib import Path

from typer.testing import CliRunner

from driftcut.cli import app
from driftcut.diff import diff_results, load_result

runner = CliRunner()


def _make_result(
    *,
    name: str = "test run",
    outcome: str = "STOP",
    reason: str = "test reason",
    overall_risk: float = 0.5,
    failure_rate: float = 0.3,
    regression_rate: float = 0.2,
    schema_break_rate: float = 0.0,
    high_crit_rate: float = 0.4,
    judge_worse_rate: float = 0.0,
    latency_p50: float = 1.0,
    latency_p95: float = 1.0,
    total_prompts: int = 10,
    total_batches: int = 2,
    total_cost: float = 0.50,
    archetypes: dict[str, int] | None = None,
    category_scores: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "total_prompts": total_prompts,
        "total_batches": total_batches,
        "cost": {"total_usd": total_cost},
        "decision": {
            "outcome": outcome,
            "reason": reason,
            "metrics": {
                "overall_risk": overall_risk,
                "candidate_failure_rate": failure_rate,
                "candidate_regression_rate": regression_rate,
                "schema_break_rate": schema_break_rate,
                "high_criticality_failure_rate": high_crit_rate,
                "judge_worse_rate": judge_worse_rate,
                "latency_p50_ratio": latency_p50,
                "latency_p95_ratio": latency_p95,
                "archetypes": archetypes or {},
                "category_scores": category_scores or [],
            },
        },
    }


# ── diff_results logic ──


def test_diff_captures_decision_change() -> None:
    before = _make_result(outcome="STOP", overall_risk=0.5)
    after = _make_result(outcome="PROCEED", overall_risk=0.05)
    result = diff_results(before, after)
    assert result.before_decision == "STOP"
    assert result.after_decision == "PROCEED"


def test_diff_captures_metric_deltas() -> None:
    before = _make_result(overall_risk=0.30, failure_rate=0.25)
    after = _make_result(overall_risk=0.10, failure_rate=0.05)
    result = diff_results(before, after)

    risk_metric = next(m for m in result.metrics if m.name == "Overall risk")
    assert risk_metric.before == 0.30
    assert risk_metric.after == 0.10
    assert risk_metric.delta < 0
    assert risk_metric.improved

    fail_metric = next(m for m in result.metrics if m.name == "Candidate failure rate")
    assert fail_metric.before == 0.25
    assert fail_metric.after == 0.05


def test_diff_captures_cost_delta() -> None:
    before = _make_result(total_cost=1.50)
    after = _make_result(total_cost=0.80)
    result = diff_results(before, after)
    assert result.before_cost == 1.50
    assert result.after_cost == 0.80


def test_diff_captures_archetype_changes() -> None:
    before = _make_result(archetypes={"json_invalid": 3, "missing_required_content": 1})
    after = _make_result(archetypes={"json_invalid": 2, "refusal_regression": 1})
    result = diff_results(before, after)
    assert "refusal_regression" in result.archetypes_added
    assert "missing_required_content" in result.archetypes_removed


def test_diff_captures_category_deltas() -> None:
    before = _make_result(
        category_scores=[
            {"category": "support", "overall_risk": 0.30, "archetypes": {}},
            {"category": "extraction", "overall_risk": 0.50, "archetypes": {}},
        ]
    )
    after = _make_result(
        category_scores=[
            {"category": "support", "overall_risk": 0.10, "archetypes": {}},
            {"category": "extraction", "overall_risk": 0.40, "archetypes": {}},
            {"category": "classification", "overall_risk": 0.05, "archetypes": {}},
        ]
    )
    result = diff_results(before, after)
    cats = {c.category: c for c in result.categories}
    assert cats["support"].risk_delta < 0
    assert cats["extraction"].risk_delta < 0
    assert "classification" in cats  # new category


def test_diff_latency_improvement_is_detected() -> None:
    before = _make_result(latency_p50=1.8, latency_p95=2.5)
    after = _make_result(latency_p50=1.2, latency_p95=1.6)
    result = diff_results(before, after)
    p50 = next(m for m in result.metrics if "p50" in m.name)
    p95 = next(m for m in result.metrics if "p95" in m.name)
    assert p50.improved
    assert p95.improved


def test_diff_identical_runs() -> None:
    run = _make_result()
    result = diff_results(run, run)
    assert result.before_decision == result.after_decision
    assert not result.archetypes_added
    assert not result.archetypes_removed


# ── File loading ──


def test_load_result_valid(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text(json.dumps(_make_result()))
    data = load_result(path)
    assert "decision" in data


def test_load_result_not_json_object(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([1, 2, 3]))
    try:
        load_result(path)
        assert False, "should have raised"  # noqa: B011
    except ValueError as exc:
        assert "not a JSON object" in str(exc)


def test_load_result_missing_decision(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"name": "oops"}))
    try:
        load_result(path)
        assert False, "should have raised"  # noqa: B011
    except ValueError as exc:
        assert "missing 'decision'" in str(exc)


# ── CLI command ──


def test_diff_command_runs(tmp_path: Path) -> None:
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(json.dumps(_make_result(outcome="STOP", overall_risk=0.5)))
    after_path.write_text(json.dumps(_make_result(outcome="PROCEED", overall_risk=0.04)))

    result = runner.invoke(
        app,
        ["diff", "--before", str(before_path), "--after", str(after_path)],
    )
    assert result.exit_code == 0
    assert "STOP" in result.stdout
    assert "PROCEED" in result.stdout


def test_diff_command_shows_categories(tmp_path: Path) -> None:
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(
        json.dumps(
            _make_result(
                category_scores=[
                    {"category": "support", "overall_risk": 0.30, "archetypes": {}},
                ]
            )
        )
    )
    after_path.write_text(
        json.dumps(
            _make_result(
                category_scores=[
                    {"category": "support", "overall_risk": 0.10, "archetypes": {}},
                ]
            )
        )
    )

    result = runner.invoke(
        app,
        ["diff", "--before", str(before_path), "--after", str(after_path)],
    )
    assert result.exit_code == 0
    assert "support" in result.stdout


def test_diff_command_bad_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_make_result()))

    result = runner.invoke(
        app,
        ["diff", "--before", str(bad), "--after", str(good)],
    )
    assert result.exit_code == 1
    assert "Load error" in result.stdout
