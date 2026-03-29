"""Serialization and HTML reporting for Driftcut runs."""

from __future__ import annotations

import html
import json
from pathlib import Path

from driftcut.config import DriftcutConfig
from driftcut.models import BatchResult, DecisionMetrics, PromptResult, RunDecision
from driftcut.runner import RunResult


def save_run_outputs(config_path: Path, config: DriftcutConfig, result: RunResult) -> list[Path]:
    """Persist enabled output artifacts for a completed run."""
    output_dir = config_path.parent / "driftcut-results"
    output_dir.mkdir(exist_ok=True)

    written_files: list[Path] = []
    if config.output.save_json:
        json_path = output_dir / "results.json"
        _write_json(json_path, config, result)
        written_files.append(json_path)
    if config.output.save_html:
        html_path = output_dir / "report.html"
        html_path.write_text(render_html_report(config, result), encoding="utf-8")
        written_files.append(html_path)
    return written_files


def _write_json(path: Path, config: DriftcutConfig, result: RunResult) -> None:
    data: dict[str, object] = {
        "name": result.config_name,
        "total_prompts": result.total_prompts,
        "total_batches": result.total_batches,
        "stopped_early": result.stopped_early,
        "cost": {
            "baseline_usd": result.cost.summary.baseline_usd,
            "candidate_usd": result.cost.summary.candidate_usd,
            "judge_usd": result.cost.summary.judge_usd,
            "total_usd": result.cost.summary.total_usd,
        },
        "decision": _decision_dict(result.final_decision, config.output.show_confidence),
        "decision_history": [
            _decision_dict(decision, config.output.show_confidence)
            for decision in result.decision_history
        ],
        "batches": [
            _batch_dict(batch, save_examples=config.output.save_examples)
            for batch in result.batches
        ],
    }

    with open(path, "w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, indent=2)


def _decision_dict(decision: RunDecision | None, show_confidence: bool) -> dict[str, object]:
    if decision is None:
        return {}
    data: dict[str, object] = {
        "outcome": decision.outcome,
        "reason": decision.reason,
        "metrics": _metrics_dict(decision.metrics),
    }
    if show_confidence:
        data["confidence"] = round(decision.confidence, 4)
    return data


def _metrics_dict(metrics: DecisionMetrics) -> dict[str, object]:
    return {
        "prompts_evaluated": metrics.prompts_evaluated,
        "batches_evaluated": metrics.batches_evaluated,
        "structured_prompts": metrics.structured_prompts,
        "high_criticality_prompts": metrics.high_criticality_prompts,
        "ambiguous_prompts": metrics.ambiguous_prompts,
        "judged_prompts": metrics.judged_prompts,
        "candidate_failure_rate": round(metrics.candidate_failure_rate, 4),
        "candidate_regression_rate": round(metrics.candidate_regression_rate, 4),
        "schema_break_rate": round(metrics.schema_break_rate, 4),
        "high_criticality_failure_rate": round(metrics.high_criticality_failure_rate, 4),
        "judge_worse_rate": round(metrics.judge_worse_rate, 4),
        "judge_equivalent_rate": round(metrics.judge_equivalent_rate, 4),
        "judge_better_rate": round(metrics.judge_better_rate, 4),
        "judge_average_confidence": round(metrics.judge_average_confidence, 4),
        "overall_risk": round(metrics.overall_risk, 4),
        "latency_p50_ratio": round(metrics.latency_p50_ratio, 4),
        "latency_p95_ratio": round(metrics.latency_p95_ratio, 4),
        "archetypes": dict(metrics.archetypes),
    }


def _batch_dict(batch: BatchResult, *, save_examples: bool) -> dict[str, object]:
    return {
        "batch_number": batch.batch_number,
        "size": batch.size,
        "total_cost_usd": batch.total_cost_usd,
        "results": [
            _prompt_result_dict(prompt, save_examples=save_examples) for prompt in batch.results
        ],
    }


def _prompt_result_dict(prompt: PromptResult, *, save_examples: bool) -> dict[str, object]:
    baseline_data: dict[str, object] = {
        "latency_ms": round(prompt.baseline.latency_ms, 1),
        "cost_usd": prompt.baseline.cost_usd,
        "cost_error": prompt.baseline.cost_error,
        "error": prompt.baseline.error,
    }
    candidate_data: dict[str, object] = {
        "latency_ms": round(prompt.candidate.latency_ms, 1),
        "cost_usd": prompt.candidate.cost_usd,
        "cost_error": prompt.candidate.cost_error,
        "error": prompt.candidate.error,
    }
    data: dict[str, object] = {
        "prompt_id": prompt.prompt_id,
        "category": prompt.category,
        "criticality": prompt.criticality,
        "expected_output_type": prompt.expected_output_type,
        "baseline": baseline_data,
        "candidate": candidate_data,
    }
    if prompt.evaluation is not None:
        evaluation_data: dict[str, object] = {
            "candidate_failed": prompt.evaluation.candidate_failed,
            "candidate_regressed": prompt.evaluation.candidate_regressed,
            "candidate_improved": prompt.evaluation.candidate_improved,
            "schema_break": prompt.evaluation.schema_break,
            "needs_judge": prompt.evaluation.needs_judge,
            "baseline_passed": prompt.evaluation.baseline.passed,
            "candidate_passed": prompt.evaluation.candidate.passed,
            "baseline_reasons": list(prompt.evaluation.baseline.reasons),
            "candidate_reasons": list(prompt.evaluation.candidate.reasons),
            "failure_archetype": prompt.evaluation.candidate.archetype,
        }
        if prompt.evaluation.judge is not None:
            evaluation_data["judge"] = {
                "model": prompt.evaluation.judge.model,
                "verdict": prompt.evaluation.judge.verdict,
                "confidence": round(prompt.evaluation.judge.confidence, 4),
                "rationale": prompt.evaluation.judge.rationale,
                "latency_ms": round(prompt.evaluation.judge.latency_ms, 1),
                "cost_usd": prompt.evaluation.judge.cost_usd,
                "cost_error": prompt.evaluation.judge.cost_error,
                "error": prompt.evaluation.judge.error,
            }
        data["evaluation"] = evaluation_data
    if save_examples:
        data["prompt_text"] = prompt.prompt_text
        baseline_data["output"] = prompt.baseline.output
        candidate_data["output"] = prompt.candidate.output
    return data


def render_html_report(config: DriftcutConfig, result: RunResult) -> str:
    """Render a lightweight HTML report for one run."""
    decision = result.final_decision
    cost = result.cost.summary
    baseline_latency = result.latency.baseline_stats()
    candidate_latency = result.latency.candidate_stats()
    metrics = decision.metrics if decision is not None else DecisionMetrics()
    decision_outcome = decision.outcome if decision is not None else "CONTINUE"
    decision_reason = decision.reason if decision is not None else "No decision available."
    decision_color = _decision_color(decision)
    confidence_line = ""
    if decision is not None and config.output.show_confidence:
        confidence_line = f"<p><strong>Confidence:</strong> {decision.confidence:.0%}</p>"

    example_rows = _render_examples(config, result)
    thresholds = _render_thresholds(config)
    archetypes = _render_archetypes(metrics)

    examples_section = ""
    if example_rows:
        examples_section = (
            "<section><h2>Examples</h2>"
            "<table><thead><tr>"
            "<th>Prompt</th><th>Category</th><th>Criticality</th>"
            "<th>Candidate issues</th><th>Candidate output</th>"
            "</tr></thead>"
            f"<tbody>{example_rows}</tbody></table></section>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(result.config_name)} - Driftcut report</title>
  <style>
    :root {{
      --bg: #0b0e11;
      --panel: #121821;
      --line: #263243;
      --text: #e5edf5;
      --muted: #9aa9bb;
      --accent: #ff4747;
      --good: #2dd4a8;
      --warn: #fbbf24;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #0b0e11 0%, #101722 100%);
      color: var(--text);
      line-height: 1.6;
    }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 48px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    section {{
      background: rgba(18, 24, 33, 0.94);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px;
      margin-bottom: 18px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      align-items: start;
    }}
    .decision {{
      font-size: 28px;
      font-weight: 700;
      color: {decision_color};
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: rgba(255, 255, 255, 0.02);
    }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    pre {{
      white-space: pre-wrap;
      margin: 0;
      font-family: "Cascadia Code", monospace;
      color: #dce7f3;
    }}
    ul {{ margin: 0; padding-left: 18px; }}
  </style>
</head>
<body>
  <main>
    <section>
      <div class="hero">
        <div>
          <div class="label">Run</div>
          <h1>{html.escape(result.config_name)}</h1>
          <div class="decision">{html.escape(decision_outcome)}</div>
          <p>{html.escape(decision_reason)}</p>
          {confidence_line}
        </div>
        <div class="card">
          <div class="label">Coverage</div>
          <div>{result.total_prompts} prompts across {result.total_batches} batches</div>
          <div>Total cost: ${cost.total_usd:.4f}</div>
          <div>Judge cost: ${cost.judge_usd:.4f}</div>
          <div>Stopped early: {"yes" if result.stopped_early else "no"}</div>
        </div>
        <div class="card">
          <div class="label">Latency</div>
          <div>p50: {baseline_latency.p50_ms:.0f}ms -> {candidate_latency.p50_ms:.0f}ms</div>
          <div>p95: {baseline_latency.p95_ms:.0f}ms -> {candidate_latency.p95_ms:.0f}ms</div>
        </div>
      </div>
    </section>

    <section>
      <h2>Decision Metrics</h2>
      <table>
        <tbody>
          <tr><th>Overall risk</th><td>{metrics.overall_risk:.1%}</td></tr>
          <tr><th>Candidate failure rate</th><td>{metrics.candidate_failure_rate:.1%}</td></tr>
          <tr>
            <th>Candidate regression rate</th>
            <td>{metrics.candidate_regression_rate:.1%}</td>
          </tr>
          <tr>
            <th>High-criticality failure rate</th>
            <td>{metrics.high_criticality_failure_rate:.1%}</td>
          </tr>
          <tr><th>Schema break rate</th><td>{metrics.schema_break_rate:.1%}</td></tr>
          <tr>
            <th>Judged prompts</th>
            <td>{metrics.judged_prompts}/{metrics.ambiguous_prompts}</td>
          </tr>
          <tr><th>Judge worse rate</th><td>{metrics.judge_worse_rate:.1%}</td></tr>
          <tr><th>Judge average confidence</th><td>{metrics.judge_average_confidence:.0%}</td></tr>
          <tr><th>Latency p50 ratio</th><td>{metrics.latency_p50_ratio:.2f}x</td></tr>
          <tr><th>Latency p95 ratio</th><td>{metrics.latency_p95_ratio:.2f}x</td></tr>
        </tbody>
      </table>
    </section>

    {thresholds}

    <section>
      <h2>Failure Archetypes</h2>
      <ul>{archetypes}</ul>
    </section>

    {examples_section}
  </main>
</body>
</html>
"""


def _render_examples(config: DriftcutConfig, result: RunResult) -> str:
    if not config.output.save_examples:
        return ""

    rows: list[str] = []
    for prompt in _top_examples(result):
        candidate_reasons = []
        if prompt.evaluation is not None:
            candidate_reasons = prompt.evaluation.candidate.reasons
        judge_text = ""
        if prompt.evaluation is not None and prompt.evaluation.judge is not None:
            judge = prompt.evaluation.judge
            judge_text = f" Judge: {judge.verdict} ({judge.confidence:.0%})"
            if judge.rationale:
                judge_text += f" - {judge.rationale}"
        issues_text = ", ".join(candidate_reasons) or "No deterministic failures"
        issues_text += judge_text
        rows.append(
            "<tr>"
            f"<td>{html.escape(prompt.prompt_id)}</td>"
            f"<td>{html.escape(prompt.category)}</td>"
            f"<td>{html.escape(prompt.criticality)}</td>"
            f"<td>{html.escape(issues_text)}</td>"
            f"<td><pre>{html.escape(prompt.candidate.output[:800])}</pre></td>"
            "</tr>"
        )
    return "".join(rows)


def _render_thresholds(config: DriftcutConfig) -> str:
    if not config.output.show_thresholds:
        return ""

    rows = [
        (
            "High-criticality stop",
            f"{config.risk.stop_on_high_criticality_failure_rate:.0%}",
        ),
        ("Schema stop", f"{config.risk.stop_on_schema_break_rate:.0%}"),
        ("Proceed risk", f"<= {config.risk.proceed_if_overall_risk_below:.0%}"),
        (
            "Latency p50 threshold",
            f"{config.latency.regression_threshold_p50:.2f}x",
        ),
        (
            "Latency p95 threshold",
            f"{config.latency.regression_threshold_p95:.2f}x",
        ),
    ]
    row_html = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
        for label, value in rows
    )
    return "<section><h2>Thresholds</h2><table><tbody>" + row_html + "</tbody></table></section>"


def _render_archetypes(metrics: DecisionMetrics) -> str:
    if not metrics.archetypes:
        return "<li>No deterministic failures observed.</li>"
    return "".join(
        f"<li>{html.escape(name)}: {count}</li>"
        for name, count in metrics.archetypes.items()
    )


def _decision_color(decision: RunDecision | None) -> str:
    if decision is None:
        return "var(--warn)"
    if decision.outcome == "PROCEED":
        return "var(--good)"
    if decision.outcome == "STOP":
        return "var(--accent)"
    return "var(--warn)"


def _top_examples(result: RunResult, *, limit: int = 8) -> list[PromptResult]:
    prompts = [prompt for batch in result.batches for prompt in batch.results]
    prompts.sort(
        key=lambda prompt: (
            prompt.evaluation is None,
            not prompt.evaluation.candidate_failed if prompt.evaluation is not None else True,
            prompt.criticality != "high",
            prompt.prompt_id,
        )
    )
    return prompts[:limit]
