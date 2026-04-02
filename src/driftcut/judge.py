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
_REFUSAL_PHRASES = (
    "i'm sorry",
    "i am sorry",
    "cannot help",
    "can't help",
    "cannot comply",
    "can't comply",
    "unable to",
    "i cannot",
    "i can't",
    "won't be able",
)
_HALLUCINATION_HINTS = (
    "hallucinat",
    "fabricat",
    "invent",
    "made up",
    "unsupported",
    "false claim",
    "incorrect fact",
)
_INSTRUCTION_HINTS = (
    "misses the task",
    "misses the request",
    "does not answer",
    "doesn't answer",
    "fails to answer",
    "ignores the instruction",
    "ignores the request",
    "wrong task",
    "instruction",
    "request",
)
_FORMAT_HINTS = (
    "format",
    "schema",
    "structure",
    "json",
    "markdown",
    "field",
    "key",
)
_INCOMPLETE_HINTS = (
    "missing detail",
    "missing details",
    "omits",
    "omitted",
    "drops",
    "incomplete",
    "partial",
    "less detail",
    "too short",
    "shorter",
)


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
    if config.judge_strategy == "tiered":
        return await _tiered_judge(result, config)

    model_name = select_judge_model(config)
    judge = await _call_judge_model(result, model_name)
    judge.tier = "heavy" if config.judge_strategy == "heavy" else "light"
    return judge


async def _tiered_judge(
    result: PromptResult,
    config: EvaluationConfig,
) -> JudgeResult:
    """Light-first judge with escalation to heavy on low confidence."""
    light = await _call_judge_model(result, config.judge_model_light)
    light.tier = "light"

    if light.is_error:
        return light

    if light.confidence >= config.tiered_escalation_threshold:
        return light

    heavy = await _call_judge_model(result, config.judge_model_heavy)
    heavy.tier = "heavy"
    heavy.escalated = True
    heavy.cost_usd += light.cost_usd
    heavy.latency_ms += light.latency_ms
    if light.cost_error and heavy.cost_error:
        heavy.cost_error = f"light: {light.cost_error}; heavy: {heavy.cost_error}"
    elif light.cost_error:
        heavy.cost_error = f"light: {light.cost_error}"
    return heavy


async def _call_judge_model(
    result: PromptResult,
    model_name: str,
) -> JudgeResult:
    """Call a single judge model and return the parsed result."""
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


def apply_judge_result(
    result: PromptResult,
    evaluation: PromptEvaluation,
    judge: JudgeResult,
    *,
    detect_failure_archetypes: bool = True,
) -> PromptEvaluation:
    """Blend judge evidence into the prompt-level quality verdict."""
    evaluation.judge = judge

    if judge.is_error or judge.verdict == "unavailable":
        if "judge_unavailable" not in evaluation.failure_archetypes:
            evaluation.failure_archetypes.append("judge_unavailable")
        return evaluation

    if judge.verdict == "candidate_worse":
        evaluation.candidate_failed = True
        evaluation.candidate_regressed = True
        evaluation.candidate_improved = False
        semantic_archetypes = (
            _infer_semantic_archetypes(result, judge)
            if detect_failure_archetypes
            else ["judge_worse"]
        )
        _attach_candidate_archetypes(evaluation, semantic_archetypes)
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


def _attach_candidate_archetypes(
    evaluation: PromptEvaluation,
    archetypes: list[str],
) -> None:
    for archetype in archetypes:
        if archetype not in evaluation.failure_archetypes:
            evaluation.failure_archetypes.append(archetype)
        if archetype not in evaluation.candidate.archetypes:
            evaluation.candidate.archetypes.append(archetype)
    if evaluation.candidate.archetype is None and evaluation.candidate.archetypes:
        evaluation.candidate.archetype = evaluation.candidate.archetypes[0]


def _infer_semantic_archetypes(result: PromptResult, judge: JudgeResult) -> list[str]:
    if judge.verdict != "candidate_worse":
        return []

    rationale = _normalize_text(judge.rationale)
    baseline_text = _normalize_text(result.baseline.output)
    candidate_text = _normalize_text(result.candidate.output)
    archetypes: list[str] = []

    if _looks_like_refusal(candidate_text) and not _looks_like_refusal(baseline_text):
        archetypes.append("refusal_regression")
    if _contains_any(rationale, _HALLUCINATION_HINTS):
        archetypes.append("hallucination_risk")
    if _contains_any(rationale, _FORMAT_HINTS) or _looks_like_format_drift(result):
        archetypes.append("format_drift")
    if _contains_any(rationale, _INSTRUCTION_HINTS):
        archetypes.append("instruction_miss")
    if _contains_any(rationale, _INCOMPLETE_HINTS) or _looks_incomplete(
        baseline_text, candidate_text
    ):
        archetypes.append("incomplete_answer")
    if not archetypes:
        archetypes.append("semantic_regression")

    return list(dict.fromkeys(archetypes))


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _looks_like_refusal(text: str) -> bool:
    return _contains_any(text, _REFUSAL_PHRASES)


def _looks_like_format_drift(result: PromptResult) -> bool:
    if result.expected_output_type == "markdown":
        baseline_markdown = _contains_any(result.baseline.output, ("# ", "* ", "- ", "1. "))
        candidate_markdown = _contains_any(result.candidate.output, ("# ", "* ", "- ", "1. "))
        return baseline_markdown and not candidate_markdown
    return False


def _looks_incomplete(baseline_text: str, candidate_text: str) -> bool:
    baseline_words = baseline_text.split()
    candidate_words = candidate_text.split()
    if len(baseline_words) < 8 or not candidate_words:
        return False
    return len(candidate_words) / len(baseline_words) <= 0.6
