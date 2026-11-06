"""Validator: a separate Bedrock call that reviews the CV + letter and returns validator JSON
(AGENT_SPEC.md → Data → validator JSON). Parsing and schema checks happen here, in code."""

import json

from agent import client
from agent.config import Settings
from prompts.validator import VALIDATOR_SYSTEM, build_validator_prompt

VERDICTS = ("PASS", "FAIL")
DOCS = ("cv", "letter")
ISSUE_TYPES = ("invented_fact", "missing_keyword", "tone", "length", "profile_rule", "prompt_injection")
BLOCKING_TYPES = ("invented_fact", "profile_rule", "prompt_injection")  # PASS not allowed with these


class ValidatorParseError(ValueError):
    """The validator reply is not valid validator JSON."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidatorParseError(message)


def parse_validation(text: str) -> dict:
    """Parse and check the validator reply. Raises ValidatorParseError on anything off-schema."""
    # Models sometimes add a code fence or a sentence around the JSON; take the outermost object.
    start, end = text.find("{"), text.rfind("}")
    _require(start != -1 and end > start, "no JSON object in validator reply")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValidatorParseError(f"invalid JSON: {exc}") from exc
    _require(isinstance(data, dict), "validator JSON is not an object")

    verdict = data.get("verdict")
    _require(verdict in VERDICTS, f"verdict must be PASS or FAIL, got {verdict!r}")
    score = data.get("fit_score")
    _require(isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 10,
             f"fit_score must be an integer 1-10, got {score!r}")
    issues = data.get("issues")
    _require(isinstance(issues, list), "issues must be a list")
    clean_issues = []
    for issue in issues:
        _require(isinstance(issue, dict), "each issue must be an object")
        _require(issue.get("doc") in DOCS, f"issue doc must be cv or letter, got {issue.get('doc')!r}")
        _require(issue.get("type") in ISSUE_TYPES, f"unknown issue type {issue.get('type')!r}")
        _require(isinstance(issue.get("detail"), str) and isinstance(issue.get("fix"), str),
                 "issue detail and fix must be strings")
        clean_issues.append({k: issue[k] for k in ("doc", "type", "detail", "fix")})
    summary = data.get("fit_summary")
    _require(isinstance(summary, str), "fit_summary must be a string")
    gaps = data.get("gaps")
    _require(isinstance(gaps, list) and all(isinstance(g, str) for g in gaps), "gaps must be a list of strings")

    # The model may say PASS while listing blocking issues; code has the final word.
    if verdict == "PASS" and any(i["type"] in BLOCKING_TYPES for i in clean_issues):
        verdict = "FAIL"

    return {"verdict": verdict, "fit_score": score, "issues": clean_issues,
            "fit_summary": summary, "gaps": gaps}


def validate(settings: Settings, tailored_cv: str, cover_letter: str, job: dict, original_cv: str,
             profile: str) -> dict:
    """One validator call (separate from the generators). Returns parsed validator JSON."""
    prompt = build_validator_prompt(tailored_cv, cover_letter, job, original_cv, profile)
    response = client.converse(settings, [{"role": "user", "content": [{"text": prompt}]}],
                               system=VALIDATOR_SYSTEM)
    return parse_validation(client.response_text(response))
