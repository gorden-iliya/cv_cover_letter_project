"""tailor_application tool (AGENT_SPEC.md → Tools → 2).

Fixed pipeline in code. Built so far: CV generator, letter generator, version folder (slices 1-2).
Validator/critic loop (slices 3-4) and re-prompt targets (slice 8) come next.
"""

import re

from agent import client
from agent.config import Settings
from agent.cv import read_original_cv
from agent.output import job_markdown, new_version_dir, write_text
from agent.profile import read_profile
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


def handle(settings: Settings, job: dict, feedback: str | None = None, target: str = "both") -> dict:
    if not (job or {}).get("description", "").strip():
        raise ValueError("job.description is empty: ask the user for the job text.")
    original_cv = read_original_cv(settings)
    profile = read_profile(settings)
    cv = generate_cv(settings, original_cv, job, feedback)
    letter = generate_letter(settings, cv, job, profile, feedback)

    version_dir = new_version_dir(settings.output_dir, job)
    write_text(version_dir, "job.md", job_markdown(job))
    write_text(version_dir, "cv.md", cv)
    write_text(version_dir, "cover_letter.md", letter)
    return {"version_dir": str(version_dir), "cv": cv, "cover_letter": letter}
