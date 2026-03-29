"""Deterministic quality checks for sampled prompt results."""

from __future__ import annotations

import json

from driftcut.models import PromptEvaluation, PromptResult, ResponseEvaluation

_STRUCTURED_OUTPUT_TYPES = {"json", "labels"}


def has_structured_expectation(expected_output_type: str) -> bool:
    """Whether the prompt expects a machine-structured response."""
    return expected_output_type in _STRUCTURED_OUTPUT_TYPES


def evaluate_prompt_result(result: PromptResult) -> PromptEvaluation:
    """Run deterministic checks for both baseline and candidate responses."""
    baseline_eval = _evaluate_response(result, result.baseline)
    candidate_eval = _evaluate_response(result, result.candidate)

    return PromptEvaluation(
        baseline=baseline_eval,
        candidate=candidate_eval,
        candidate_failed=not candidate_eval.passed,
        candidate_regressed=baseline_eval.passed and not candidate_eval.passed,
        candidate_improved=(not baseline_eval.passed) and candidate_eval.passed,
        schema_break=(
            has_structured_expectation(result.expected_output_type)
            and baseline_eval.structure_valid
            and not candidate_eval.structure_valid
        ),
    )


def _evaluate_response(result: PromptResult, response: object) -> ResponseEvaluation:
    from driftcut.models import ModelResponse

    if not isinstance(response, ModelResponse):
        msg = f"expected ModelResponse, got {type(response).__name__}"
        raise TypeError(msg)

    reasons: list[str] = []
    archetype: str | None = None
    structure_valid = True

    if response.is_error:
        return ResponseEvaluation(
            passed=False,
            structure_valid=False,
            reasons=[response.error or "Model call failed"],
            archetype="api_error",
        )

    output = response.output.strip()
    if not output:
        return ResponseEvaluation(
            passed=False,
            structure_valid=False,
            reasons=["Response output is empty"],
            archetype="empty_output",
        )

    if result.expected_output_type == "json":
        parsed_json = _parse_json(output)
        if parsed_json is None:
            return ResponseEvaluation(
                passed=False,
                structure_valid=False,
                reasons=["Output is not valid JSON"],
                archetype="json_invalid",
            )
        if isinstance(parsed_json, dict):
            missing_keys = [key for key in result.json_required_keys if key not in parsed_json]
        else:
            missing_keys = list(result.json_required_keys)
        if missing_keys:
            reasons.append(f"Missing JSON keys: {', '.join(missing_keys)}")
            archetype = archetype or "missing_json_keys"
    elif result.expected_output_type == "labels":
        labels = _parse_labels(output)
        if not labels:
            return ResponseEvaluation(
                passed=False,
                structure_valid=False,
                reasons=["Output does not contain any labels"],
                archetype="invalid_labels",
            )

    missing_required = [
        phrase for phrase in result.required_substrings if phrase.lower() not in output.lower()
    ]
    if missing_required:
        reasons.append(f"Missing required content: {', '.join(missing_required)}")
        archetype = archetype or "missing_required_content"

    forbidden_matches = [
        phrase for phrase in result.forbidden_substrings if phrase.lower() in output.lower()
    ]
    if forbidden_matches:
        reasons.append(f"Forbidden content present: {', '.join(forbidden_matches)}")
        archetype = archetype or "forbidden_content"

    if result.max_output_chars is not None and len(output) > result.max_output_chars:
        reasons.append(
            f"Output length {len(output)} exceeds max_output_chars={result.max_output_chars}"
        )
        archetype = archetype or "overlong_output"

    return ResponseEvaluation(
        passed=not reasons,
        structure_valid=structure_valid,
        reasons=reasons,
        archetype=archetype,
    )


def _parse_json(output: str) -> dict[str, object] | list[object] | None:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict | list):
        return parsed
    return None


def _parse_labels(output: str) -> list[str]:
    parsed_json = _parse_json(output)
    if isinstance(parsed_json, list):
        labels = [str(item).strip() for item in parsed_json if str(item).strip()]
        return labels

    separators = ["\n", ",", ";", "|"]
    for separator in separators:
        if separator in output:
            labels = [item.strip() for item in output.split(separator) if item.strip()]
            if labels:
                return labels

    stripped = output.strip()
    if not stripped:
        return []
    return [stripped]
