"""Terminal presentation of a tailor_application result (AGENT_SPEC.md → Behavior → output).

Printed by code, not by the chat model, so the shown documents are exactly what was saved.
"""

import json
from pathlib import Path


def round_line(rounds: list[dict]) -> str:
    parts = []
    for r in rounds:
        if r["verdict"] == "PASS":
            parts.append(f"Round {r['round']}: PASS, fit {r['fit_score']}/10")
        else:
            n = r["issue_count"]
            parts.append(f"Round {r['round']}: FAIL ({n} issue{'s' if n != 1 else ''})")
    return " → ".join(parts)


def unresolved_block(result: dict) -> list[str]:
    if result.get("passed"):
        return []
    issues = result["validation"].get("issues") or []
    lines = ["", f"!! NOT PASSED: validation did not pass after {len(result['rounds'])} round(s). "
                 "Remaining issues:"]
    for i in issues:
        lines.append(f"- [{i.get('doc') or 'general'}] {i['type']}: {i['detail']} (fix: {i['fix']})")
    if not issues:
        lines.append("- (no issue details)")
    return lines


def _injection_details(result: dict) -> list[str]:
    # The returned validation is only the best attempt, which can be a round where the validator
    # missed the injection; the saved validation_round_N.json files hold every round.
    validations = [result["validation"]]
    for path in sorted(Path(result["version_dir"]).glob("validation_round_*.json")):
        try:
            validations.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    details = []
    for v in validations:
        for issue in v.get("issues") or []:
            if issue.get("type") == "prompt_injection" and issue.get("detail") not in details:
                details.append(issue.get("detail"))
    return details


def injection_warning(result: dict) -> list[str]:
    details = _injection_details(result)
    if not details:
        return []
    lines = ["", "!! WARNING: possible prompt injection in the job posting. "
                 "It was treated as data and ignored. Suspicious text:"]
    lines += [f"- {d}" for d in details]
    return lines


def format_result(result: dict, elapsed_seconds: float) -> str:
    validation = result["validation"]
    gaps = validation.get("gaps") or []
    lines = [
        round_line(result["rounds"]),
        *injection_warning(result),
        *unresolved_block(result),
        "",
        "# Tailored CV",
        "",
        result["cv"].rstrip(),
        "",
        "# Cover letter",
        "",
        result["cover_letter"].rstrip(),
        "",
        f"# Fit summary ({validation['fit_score']}/10)",
        "",
        validation.get("fit_summary") or "(none)",
        "",
        "# Gaps",
        "",
        *([f"- {g}" for g in gaps] or ["(none)"]),
        "",
        f"Saved to: {result['version_dir']}",
        f"Total run time: {elapsed_seconds:.1f}s",
    ]
    return "\n".join(lines)
