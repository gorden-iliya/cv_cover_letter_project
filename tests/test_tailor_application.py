import hashlib
from pathlib import Path

import pytest

from agent import client
from agent.config import Settings
from agent.output import job_dir_name, new_version_dir, slugify
from tools import TOOLS, tailor_application

EXAMPLE_CV = "cv/original_cv.example.md"
JOB = {"title": "Senior DevOps Engineer", "company": "Acme Corp!", "location": "Remote",
       "description": "We need Kubernetes and Terraform skills."}


PROFILE = "## Tone\nwarm\n\n## Language\nEnglish\n\n## Must mention\nopen to relocation\n"


def _settings(tmp_path, cv_path=EXAMPLE_CV, profile_path=None):
    return Settings("model-x", "eu-west-1", ("jobs.lever.co",), 500, 2, False,
                    cv_path, profile_path or str(tmp_path / "no_profile.md"), str(tmp_path / "out"))


@pytest.fixture
def fake_converse(monkeypatch):
    calls = []

    def fake(settings, messages, system=None, tool_config=None):
        calls.append({"settings": settings, "messages": messages, "system": system, "tool_config": tool_config})
        text = "Dear Acme Corp,\nLetter" if "cover letter" in system else "```markdown\n# Jane Doe\nTailored\n```"
        return {"stopReason": "end_turn",
                "output": {"message": {"role": "assistant", "content": [{"text": text}]}}}

    monkeypatch.setattr(client, "converse", fake)
    return calls


def test_tool_is_registered():
    assert tailor_application in TOOLS
    assert tailor_application.TOOL_SPEC["name"] == "tailor_application"


def test_cv_prompt_contains_original_cv_and_wrapped_job(tmp_path, fake_converse):
    result = tailor_application.handle(_settings(tmp_path), JOB)
    assert len(fake_converse) == 2  # CV generator, then letter generator
    call = fake_converse[0]
    prompt = call["messages"][0]["content"][0]["text"]
    original = Path(EXAMPLE_CV).read_text(encoding="utf-8")
    assert "<original_cv>\n" + original in prompt
    assert "<job_posting>" in prompt and "We need Kubernetes and Terraform skills." in prompt
    start, end = prompt.index("<job_posting>"), prompt.index("</job_posting>")
    assert start < prompt.index("We need Kubernetes") < end
    assert "Never invent" in call["system"]
    assert call["tool_config"] is None
    assert result["cv"] == "# Jane Doe\nTailored\n"  # code fences stripped


def test_feedback_and_fixes_are_in_prompt(tmp_path, fake_converse):
    tailor_application.generate_cv(_settings(tmp_path), "CV", JOB, feedback="shorter", fixes=["drop X"])
    prompt = fake_converse[0]["messages"][0]["content"][0]["text"]
    assert "<user_feedback>\nshorter" in prompt and "- drop X" in prompt


def test_saves_version_folder_and_keeps_original_cv(tmp_path, fake_converse):
    settings = _settings(tmp_path)
    before = hashlib.sha256(Path(EXAMPLE_CV).read_bytes()).hexdigest()
    r1 = tailor_application.handle(settings, JOB)
    r2 = tailor_application.handle(settings, JOB, feedback="more k8s", target="cv")
    v1, v2 = Path(r1["version_dir"]), Path(r2["version_dir"])
    assert v1 == tmp_path / "out" / "acme-corp_senior-devops-engineer" / "v1"
    assert v2.name == "v2"
    assert (v1 / "cv.md").read_text(encoding="utf-8") == "# Jane Doe\nTailored\n"
    assert (v1 / "cover_letter.md").read_text(encoding="utf-8") == "Dear Acme Corp,\nLetter\n"
    job_md = (v1 / "job.md").read_text(encoding="utf-8")
    for value in ("Senior DevOps Engineer", "Acme Corp!", "Remote", "We need Kubernetes"):
        assert value in job_md
    assert hashlib.sha256(Path(EXAMPLE_CV).read_bytes()).hexdigest() == before


def test_empty_description_rejected(tmp_path, fake_converse):
    with pytest.raises(ValueError):
        tailor_application.handle(_settings(tmp_path), {"description": "  "})
    assert fake_converse == []


def test_slugs():
    assert slugify("Acme, Inc.", "x") == "acme-inc"
    assert slugify(None, "unknown") == "unknown"
    assert job_dir_name({"description": "d"}) == "unknown-company_unknown-role"


def test_version_numbers_never_reuse(tmp_path):
    job = {"company": "A", "title": "B"}
    assert new_version_dir(str(tmp_path), job).name == "v1"
    (tmp_path / "a_b" / "v7").mkdir()
    assert new_version_dir(str(tmp_path), job).name == "v8"


def test_letter_prompt_contains_tailored_cv_job_and_profile(tmp_path, fake_converse):
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(PROFILE, encoding="utf-8")
    result = tailor_application.handle(_settings(tmp_path, profile_path=str(profile_path)), JOB)
    cv_call, letter_call = fake_converse
    assert "cover letter" in letter_call["system"] and "Never mention" in letter_call["system"]
    assert letter_call["settings"].bedrock_model_id == "model-x"
    prompt = letter_call["messages"][0]["content"][0]["text"]
    assert "<tailored_cv>\n# Jane Doe\nTailored\n" in prompt  # the generated CV, not the original
    assert "<original_cv>" not in prompt
    start, end = prompt.index("<job_posting>"), prompt.index("</job_posting>")
    assert start < prompt.index("company: Acme Corp!") < prompt.index("We need Kubernetes") < end
    assert "<profile>\n" + PROFILE.strip() + "\n</profile>" in prompt
    assert result["cover_letter"] == "Dear Acme Corp,\nLetter\n"


def test_missing_profile_means_no_constraints(tmp_path, fake_converse):
    tailor_application.handle(_settings(tmp_path), JOB)
    prompt = fake_converse[1]["messages"][0]["content"][0]["text"]
    assert "<profile>\n(no profile: no constraints)\n</profile>" in prompt


def test_letter_feedback_and_fixes_are_in_prompt(tmp_path, fake_converse):
    tailor_application.generate_letter(_settings(tmp_path), "CV", JOB, "", feedback="shorter", fixes=["name company"])
    prompt = fake_converse[0]["messages"][0]["content"][0]["text"]
    assert "<user_feedback>\nshorter" in prompt and "- name company" in prompt
