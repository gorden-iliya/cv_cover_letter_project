"""tailor_application tool (AGENT_SPEC.md → Tools → 2).

Fixed pipeline in code: CV generator → letter generator → validator, looped until PASS or
MAX_VALIDATION_ROUNDS, then the version folder. Re-prompt targets (slice 8) come next.
"""

import json
import re

from agent import client
from agent.config import Settings
from agent.cv import read_original_cv
from agent.output import job_markdown, new_version_dir, write_text
from agent.profile import read_profile
from agent.validator import validate
from prompts.cv_generator import CV_GENERATOR_SYSTEM, build_cv_prompt
from prompts.letter_generator import LETTER_GENERATOR_SYSTEM, build_letter_prompt

TOOL_SPEC = {
    "name": "tailor_application",
    "description": (
        "Generate (or regenerate) the tailored CV and cover letter for a job, validate them and "
        "save them to a new version folder. Use it once you have a job (from fetch_job or pasted text)."
    ),
    "inputSchema": {"json": {
        "type": "object",
        "additionalProperties": False,
        "required": ["job"],
        "properties": {
            "job": {
                "type": "object",
                "description": "The job from fetch_job, or {\"description\": \"<pasted text>\"} plus any "
                               "fields the user gave. Copy pasted job text verbatim into description.",
                "required": ["description"],
                "properties": {
                    "title": {"type": "string", "description": "Job title"},
                    "company": {"type": "string", "description": "Company name"},
                    "location": {"type": "string", "description": "Job location"},
                    "source_host": {"type": "string", "description": "Host the job came from"},
                    "final_url": {"type": "string", "description": "URL of the job page after redirects"},
                    "description": {"type": "string", "description": "Full job posting text"},
                },
            },
            "feedback": {"type": "string", "description": "The user's refinement request, if any"},
            "target": {"type": "string", "enum": ["cv", "letter", "both"],
                       "description": "Which document(s) to regenerate. Default both."},
        },
    }},
}


def _strip_fences(text: str) -> str:
    # Models sometimes wrap markdown output in ``` fences despite instructions.
    match = re.fullmatch(r"\s*```[a-zA-Z]*\n(.*?)\n```\s*", text, re.DOTALL)
    return (match.group(1) if match else text).strip() + "\n"


def generate_cv(settings: Settings, original_cv: str, job: dict, feedback: str | None = None,
                fixes: list[str] | None = None) -> str:
    prompt = build_cv_prompt(original_cv, job, feedback, fixes)
    response = client.converse(settings, [{"role": "user", "content": [{"text": prompt}]}],
                               system=CV_GENERATOR_SYSTEM)
    return _strip_fences(client.response_text(response))


def generate_letter(settings: Settings, tailored_cv: str, job: dict, profile: str,
                    feedback: str | None = None, fixes: list[str] | None = None) -> str:
    prompt = build_letter_prompt(tailored_cv, job, profile, feedback, fixes)
    response = client.converse(settings, [{"role": "user", "content": [{"text": prompt}]}],
                               system=LETTER_GENERATOR_SYSTEM)
    return _strip_fences(client.response_text(response))


def _fixes_for(validation: dict, doc: str) -> list[str]:
    return [i["fix"] for i in validation["issues"] if i["doc"] == doc]


def _best_attempt(attempts: list[dict]) -> dict:
    # Fewest issues, then highest fit_score; ties keep the earliest round (min is stable).
    return min(attempts, key=lambda a: (len(a["validation"]["issues"]), -a["validation"]["fit_score"]))


def handle(settings: Settings, job: dict, feedback: str | None = None, target: str = "both") -> dict:
    if not (job or {}).get("description", "").strip():
        raise ValueError("job.description is empty: ask the user for the job text.")
    original_cv = read_original_cv(settings)
    profile = read_profile(settings)

    attempts = []
    cv = letter = None
    cv_fixes = letter_fixes = None
    regen_cv = regen_letter = True
    for round_no in range(1, settings.max_validation_rounds + 1):
        if regen_cv:
            cv = generate_cv(settings, original_cv, job, feedback, cv_fixes)
        if regen_letter or regen_cv:  # the letter follows any CV change
            letter = generate_letter(settings, cv, job, profile, feedback, letter_fixes)
        validation = validate(settings, cv, letter, job, original_cv, profile)
        attempts.append({"round": round_no, "cv": cv, "cover_letter": letter, "validation": validation})
        if validation["verdict"] == "PASS":
            break
        # Regenerate only the documents named in the issues. A validator_error issue (doc None)
        # names none, so the next round just re-validates the same CV and letter.
        cv_fixes, letter_fixes = _fixes_for(validation, "cv"), _fixes_for(validation, "letter")
        regen_cv, regen_letter = bool(cv_fixes), bool(letter_fixes)

    final = attempts[-1] if attempts[-1]["validation"]["verdict"] == "PASS" else _best_attempt(attempts)
    rounds = [{"round": a["round"], "verdict": a["validation"]["verdict"],
               "issue_count": len(a["validation"]["issues"]), "fit_score": a["validation"]["fit_score"]}
              for a in attempts]

    version_dir = new_version_dir(settings.output_dir, job)
    write_text(version_dir, "job.md", job_markdown(job))
    write_text(version_dir, "cv.md", final["cv"])
    write_text(version_dir, "cover_letter.md", final["cover_letter"])
    for a in attempts:
        write_text(version_dir, f"validation_round_{a['round']}.json",
                   json.dumps(a["validation"], indent=2, ensure_ascii=False))
    return {"version_dir": str(version_dir), "cv": final["cv"], "cover_letter": final["cover_letter"],
            "validation": final["validation"], "rounds": rounds,
            "passed": final["validation"]["verdict"] == "PASS"}
