"""Semantic judge support for ambiguous prompt comparisons."""

from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher
from typing import Any, Literal

import litellm

from driftcut.config import EvaluationConfig
from driftcut.models import JudgeResult, PromptEvaluation, PromptResult

_MAX_OUTPUT_CHARS = 3500
type JudgeVerdict = Literal["candidate_worse", "equivalent", "candidate_better"]


def judge_strategy_enabled(config: EvaluationConfig) -> bool:
    """Whether the runtime should issue judge calls for this strategy."""
    return config.judge_strategy != "none"


def select_judge_model(config: EvaluationConfig) -> str:
    """Choose the active judge model for the configured strategy."""
    if config.judge_strategy == "heavy":
        return config.judge_model_heavy
    return config.judge_model_light


def prompt_needs_judge(result: PromptResult) -> bool:
    """Whether this prompt is ambiguous enough to justify a semantic judge."""
    evaluation = result.evaluation
    if evaluation is None:
        msg = f"Prompt {result.prompt_id} is missing deterministic evaluation"
        raise ValueError(msg)

    if not evaluation.baseline.passed or not evaluation.candidate.passed:
        return False

    baseline_text = _normalize_text(result.baseline.output)
    candidate_text = _normalize_text(result.candidate.output)
    if not baseline_text or not candidate_text:
        return False
    if baseline_text == candidate_text:
        return False

    if result.expected_output_type == "json":
        return _canonical_json(result.baseline.output) != _canonical_json(result.candidate.output)
    if result.expected_output_type == "labels":
        return _normalized_labels(result.baseline.output) != _normalized_labels(
            result.candidate.output
        )

    similarity = SequenceMatcher(None, baseline_text, candidate_text).ratio()
    if result.criticality == "low":
        return similarity < 0.90
    return similarity < 0.97


async def judge_prompt_result(
    result: PromptResult,
    config: EvaluationConfig,
) -> JudgeResult:
    """Compare baseline and candidate outputs with a judge model."""
    model_name = select_judge_model(config)
    start = time.perf_counter()
    try:
        response = await litellm.acompletion(
            model=model_name,
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _judge_prompt(result)},
            ],
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        content = response.choices[0].message.content or ""
        verdict, confidence, rationale = _parse_judge_response(content)

        cost = 0.0
        cost_error: str | None = None
        try:
            cost = litellm.completion_cost(completion_response=response)
        except Exception as exc:  # pragma: no cover - covered by executor analogue
            cost_error = str(exc)

        return JudgeResult(
            model=model_name,
            verdict=verdict,
            confidence=confidence,
            rationale=rationale,
            latency_ms=elapsed_ms,
            cost_usd=cost,
            cost_error=cost_error,
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return JudgeResult(
            model=model_name,
            verdict="unavailable",
            latency_ms=elapsed_ms,
            error=str(exc),
        )


def apply_judge_result(evaluation: PromptEvaluation, judge: JudgeResult) -> PromptEvaluation:
    """Blend judge evidence into the prompt-level quality verdict."""
    evaluation.judge = judge

    if judge.is_error or judge.verdict == "unavailable":
        return evaluation

    if judge.verdict == "candidate_worse":
        evaluation.candidate_failed = True
        evaluation.candidate_regressed = True
        evaluation.candidate_improved = False
    elif judge.verdict == "candidate_better":
        evaluation.candidate_failed = False
        evaluation.candidate_regressed = False
        evaluation.candidate_improved = True
    else:
        evaluation.candidate_failed = False
        evaluation.candidate_regressed = False
        evaluation.candidate_improved = False

    return evaluation


def _system_prompt() -> str:
    return (
        "You are an impartial migration judge for LLM outputs. "
        "Compare the candidate answer against the baseline for the same user prompt. "
        "Prefer 'equivalent' when differences are stylistic but equally useful. "
        "Return JSON only with keys verdict, confidence, rationale."
    )


def _judge_prompt(result: PromptResult) -> str:
    notes = result.notes.strip() or "None"
    constraints = {
        "required_substrings": result.required_substrings,
        "forbidden_substrings": result.forbidden_substrings,
        "json_required_keys": result.json_required_keys,
        "max_output_chars": result.max_output_chars,
    }
    payload = {
        "task": "Compare baseline and candidate outputs for migration suitability.",
        "expected_output_type": result.expected_output_type,
        "criticality": result.criticality,
        "notes": notes,
        "deterministic_constraints": constraints,
        "prompt": result.prompt_text,
        "baseline_output": result.baseline.output[:_MAX_OUTPUT_CHARS],
        "candidate_output": result.candidate.output[:_MAX_OUTPUT_CHARS],
        "response_schema": {
            "verdict": "candidate_worse | equivalent | candidate_better",
            "confidence": "0.0-1.0",
            "rationale": "short explanation",
        },
    }
    return json.dumps(payload, ensure_ascii=True, indent=2)


def _parse_judge_response(
    content: str,
) -> tuple[
    JudgeVerdict,
    float,
    str,
]:
    payload = _extract_judge_payload(content)
    if payload is None:
        msg = "Judge did not return parseable JSON"
        raise ValueError(msg)

    verdict = _normalize_verdict(payload.get("verdict"))
    confidence = _clamp_confidence(payload.get("confidence"))
    rationale = str(payload.get("rationale") or payload.get("reason") or "").strip()
    return verdict, confidence, rationale


def _extract_judge_payload(content: str) -> dict[str, Any] | None:
    content = content.strip()
    if not content:
        return None

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", content)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_verdict(value: object) -> JudgeVerdict:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    mapping: dict[str, JudgeVerdict] = {
        "candidate_worse": "candidate_worse",
        "worse": "candidate_worse",
        "baseline_better": "candidate_worse",
        "equivalent": "equivalent",
        "same": "equivalent",
        "tie": "equivalent",
        "candidate_better": "candidate_better",
        "better": "candidate_better",
    }
    if normalized not in mapping:
        msg = f"Unsupported judge verdict: {value}"
        raise ValueError(msg)
    return mapping[normalized]


def _clamp_confidence(value: object) -> float:
    if not isinstance(value, str | int | float):
        return 0.5
    try:
        numeric = float(value)
    except ValueError:
        return 0.5
    return max(0.0, min(1.0, numeric))


def _canonical_json(output: str) -> str:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return output.strip()
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def _normalized_labels(output: str) -> tuple[str, ...]:
    separators = ["\n", ",", ";", "|"]
    for separator in separators:
        if separator in output:
            labels = [item.strip().lower() for item in output.split(separator) if item.strip()]
            return tuple(sorted(labels))
    stripped = output.strip().lower()
    return (stripped,) if stripped else ()


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())
