import hashlib
import json
from pathlib import Path

import pytest

from agent import client
from agent.config import Settings
from agent.output import job_dir_name, new_version_dir, slugify
from agent.validator import ValidatorParseError, parse_validation
from tools import TOOLS, tailor_application

EXAMPLE_CV = "cv/original_cv.example.md"
JOB = {"title": "Senior DevOps Engineer", "company": "Acme Corp!", "location": "Remote",
       "description": "We need Kubernetes and Terraform skills."}


PROFILE = "## Tone\nwarm\n\n## Language\nEnglish\n\n## Must mention\nopen to relocation\n"

VALIDATION = {"verdict": "FAIL", "fit_score": 7,
              "issues": [{"doc": "letter", "type": "missing_keyword", "detail": "no Terraform",
                          "fix": "mention Terraform"}],
              "fit_summary": "Strong Kubernetes background.", "gaps": ["Go"]}
VALIDATION_REPLY = "```json\n" + json.dumps(VALIDATION) + "\n```"


def _settings(tmp_path, cv_path=EXAMPLE_CV, profile_path=None, rounds=1):
    # rounds=1 keeps single-round tests simple; critic-loop tests pass rounds explicitly.
    return Settings("model-x", "eu-west-1", ("jobs.lever.co",), 500, rounds, False,
                    cv_path, profile_path or str(tmp_path / "no_profile.md"), str(tmp_path / "out"))


@pytest.fixture
def fake_converse(monkeypatch):
    calls = []

    def fake(settings, messages, system=None, tool_config=None):
        calls.append({"settings": settings, "messages": messages, "system": system, "tool_config": tool_config})
        if "strict reviewer" in system:
            text = VALIDATION_REPLY
        elif "cover letter" in system:
            text = "Dear Acme Corp,\nLetter"
        else:
            text = "```markdown\n# Jane Doe\nTailored\n```"
        return {"stopReason": "end_turn",
                "output": {"message": {"role": "assistant", "content": [{"text": text}]}}}

    monkeypatch.setattr(client, "converse", fake)
    return calls


def test_tool_is_registered():
    assert tailor_application in TOOLS
    assert tailor_application.TOOL_SPEC["name"] == "tailor_application"


def test_cv_prompt_contains_original_cv_and_wrapped_job(tmp_path, fake_converse):
    result = tailor_application.handle(_settings(tmp_path), JOB)
    assert len(fake_converse) == 3  # CV generator, letter generator, validator
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


FETCHED_JOB = {"title": "Platform Engineer", "company": "Globex", "location": "Tel Aviv",
               "source_host": "jobs.lever.co", "final_url": "https://jobs.lever.co/globex/123",
               "description": "Run Kubernetes clusters.\nOn-call rotation."}


def test_job_md_records_every_job_field(tmp_path, fake_converse):
    result = tailor_application.handle(_settings(tmp_path), FETCHED_JOB)
    job_md = (Path(result["version_dir"]) / "job.md").read_text(encoding="utf-8")
    for key in ("title", "company", "location", "source_host", "final_url"):
        assert f"- {key}: {FETCHED_JOB[key]}\n" in job_md
    assert "## description\n\nRun Kubernetes clusters.\nOn-call rotation.\n" in job_md


def test_job_md_marks_missing_fields_for_pasted_text(tmp_path, fake_converse):
    result = tailor_application.handle(_settings(tmp_path), {"description": "Pasted job text"})
    job_md = (Path(result["version_dir"]) / "job.md").read_text(encoding="utf-8")
    for key in ("title", "company", "location", "source_host", "final_url"):
        assert f"- {key}: unknown\n" in job_md
    assert "Pasted job text" in job_md


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


def test_version_folder_contents_and_reprompt_keeps_v1(tmp_path, fake_converse):
    settings = _settings(tmp_path, rounds=2)  # fake validator always FAILs -> 2 rounds
    job = dict(FETCHED_JOB, company="ACME Corp. (EU)", title="Senior DevOps / SRE Engineer")
    r1 = tailor_application.handle(settings, job)
    v1 = Path(r1["version_dir"])
    folder = v1.parent.name
    assert folder == "acme-corp-eu_senior-devops-sre-engineer"
    assert folder == folder.lower() and all(c.isalnum() or c in "-_" for c in folder)
    assert sorted(p.name for p in v1.iterdir()) == [
        "cover_letter.md", "cv.md", "job.md", "validation_round_1.json", "validation_round_2.json"]
    assert len(r1["rounds"]) == 2
    snapshot = {p.name: p.read_bytes() for p in v1.iterdir()}

    r2 = tailor_application.handle(settings, job, feedback="make the cover letter shorter", target="letter")
    v2 = Path(r2["version_dir"])
    assert v2 == v1.parent / "v2"
    assert {"cv.md", "cover_letter.md", "job.md", "validation_round_1.json"} <= {p.name for p in v2.iterdir()}
    assert {p.name: p.read_bytes() for p in v1.iterdir()} == snapshot  # v1 untouched


def test_letter_prompt_contains_tailored_cv_job_and_profile(tmp_path, fake_converse):
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(PROFILE, encoding="utf-8")
    result = tailor_application.handle(_settings(tmp_path, profile_path=str(profile_path)), JOB)
    cv_call, letter_call, _ = fake_converse
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


FULL_PROFILE = ("## Tone\nwarm\n\n## Language\nEnglish\n\n## Length limits\nletter <= 150 words\n\n"
                "## Must mention\nopen to relocation\n\n## Never mention\nsalary\n\n"
                "## Target roles\nDevOps\n\n## Companies to avoid\nInitech\n")


@pytest.mark.parametrize("profile", [FULL_PROFILE, FULL_PROFILE.replace("## Length limits\nletter <= 150 words\n\n", "")])
def test_all_profile_sections_reach_letter_and_missing_section_still_works(tmp_path, fake_converse, profile):
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(profile, encoding="utf-8")
    result = tailor_application.handle(_settings(tmp_path, profile_path=str(profile_path)), JOB)
    letter_call = fake_converse[1]
    prompt = letter_call["messages"][0]["content"][0]["text"]
    assert "<profile>\n" + profile.strip() + "\n</profile>" in prompt
    assert "Must mention" in letter_call["system"] and "missing or empty means no constraint" in letter_call["system"]
    assert result["cover_letter"]


def test_validator_is_separate_call_with_all_inputs(tmp_path, fake_converse):
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(PROFILE, encoding="utf-8")
    result = tailor_application.handle(_settings(tmp_path, profile_path=str(profile_path)), JOB)
    cv_call, letter_call, val_call = fake_converse
    assert val_call["system"] not in (cv_call["system"], letter_call["system"])
    assert val_call["settings"].bedrock_model_id == "model-x"
    prompt = val_call["messages"][0]["content"][0]["text"]
    assert "<tailored_cv>\n# Jane Doe\nTailored\n" in prompt
    assert "<cover_letter>\nDear Acme Corp,\nLetter\n" in prompt
    assert "<original_cv>\n" + Path(EXAMPLE_CV).read_text(encoding="utf-8") in prompt
    start, end = prompt.index("<job_posting>"), prompt.index("</job_posting>")
    assert start < prompt.index("We need Kubernetes") < end
    assert "<profile>\n" + PROFILE.strip() + "\n</profile>" in prompt
    assert result["validation"] == VALIDATION
    assert result["rounds"] == [{"round": 1, "verdict": "FAIL", "issue_count": 1, "fit_score": 7}]
    assert result["passed"] is False
    saved = json.loads((Path(result["version_dir"]) / "validation_round_1.json").read_text(encoding="utf-8"))
    assert saved == VALIDATION


def test_parse_validation_accepts_schema_and_drops_extra_keys():
    data = dict(VALIDATION, extra="x")
    data["issues"] = [dict(VALIDATION["issues"][0], severity="high")]
    parsed = parse_validation("Here you go:\n" + json.dumps(data))
    assert parsed == VALIDATION


@pytest.mark.parametrize("reply", [
    "not json",
    "{broken",
    json.dumps(dict(VALIDATION, verdict="MAYBE")),
    json.dumps(dict(VALIDATION, fit_score=11)),
    json.dumps(dict(VALIDATION, fit_score="7")),
    json.dumps(dict(VALIDATION, issues=[{"doc": "email", "type": "tone", "detail": "d", "fix": "f"}])),
    json.dumps(dict(VALIDATION, issues=[{"doc": "cv", "type": "spelling", "detail": "d", "fix": "f"}])),
    json.dumps(dict(VALIDATION, gaps="Go")),
    json.dumps({k: v for k, v in VALIDATION.items() if k != "fit_summary"}),
])
def test_parse_validation_rejects_off_schema(reply):
    with pytest.raises(ValidatorParseError):
        parse_validation(reply)


@pytest.mark.parametrize("issue_type", ["invented_fact", "profile_rule", "prompt_injection"])
def test_pass_with_blocking_issue_is_overridden_to_fail(issue_type):
    issue = {"doc": "cv", "type": issue_type, "detail": "d", "fix": "f"}
    parsed = parse_validation(json.dumps(dict(VALIDATION, verdict="PASS", issues=[issue])))
    assert parsed["verdict"] == "FAIL"


@pytest.mark.parametrize("issue_type", ["missing_keyword", "tone", "length"])
def test_pass_with_minor_issue_stays_pass(issue_type):
    issue = {"doc": "letter", "type": issue_type, "detail": "d", "fix": "f"}
    parsed = parse_validation(json.dumps(dict(VALIDATION, verdict="PASS", issues=[issue])))
    assert parsed["verdict"] == "PASS"


def test_overridden_verdict_reaches_result_and_saved_file(tmp_path, monkeypatch):
    reply = json.dumps(dict(VALIDATION, verdict="PASS", issues=[
        {"doc": "cv", "type": "invented_fact", "detail": "employer 'Initech' not in original", "fix": "remove"}]))

    def fake(settings, messages, system=None, tool_config=None):
        text = reply if "strict reviewer" in system else "text"
        return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}}

    monkeypatch.setattr(client, "converse", fake)
    result = tailor_application.handle(_settings(tmp_path), JOB)
    assert result["passed"] is False and result["rounds"][0]["verdict"] == "FAIL"
    saved = json.loads((Path(result["version_dir"]) / "validation_round_1.json").read_text(encoding="utf-8"))
    assert saved["verdict"] == "FAIL"


def _validator_replies(monkeypatch, replies):
    """Fake converse: generators return text; validator calls return `replies` in order."""
    validator_calls = []

    def fake(settings, messages, system=None, tool_config=None):
        if "strict reviewer" in system:
            validator_calls.append(messages)
            text = replies[len(validator_calls) - 1]
        else:
            text = "text"
        return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}}

    monkeypatch.setattr(client, "converse", fake)
    return validator_calls


def test_invalid_validator_json_is_retried_once(tmp_path, monkeypatch):
    calls = _validator_replies(monkeypatch, ["not json at all", VALIDATION_REPLY])
    result = tailor_application.handle(_settings(tmp_path), JOB)
    assert len(calls) == 2
    assert calls[0] == calls[1]  # same prompt re-sent
    assert result["validation"] == VALIDATION


def test_two_invalid_validator_replies_make_fail_round(tmp_path, monkeypatch):
    calls = _validator_replies(monkeypatch, ["not json", "{broken}"])
    result = tailor_application.handle(_settings(tmp_path), JOB)
    assert len(calls) == 2
    v = result["validation"]
    assert v["verdict"] == "FAIL" and v["fit_score"] == 1
    assert v["fit_summary"] == "" and v["gaps"] == []
    assert len(v["issues"]) == 1
    issue = v["issues"][0]
    assert issue["doc"] is None and issue["type"] == "validator_error"
    assert "invalid JSON" in issue["detail"] and issue["fix"] == "re-run the validator"
    assert result["rounds"] == [{"round": 1, "verdict": "FAIL", "issue_count": 1, "fit_score": 1}]
    assert result["passed"] is False
    saved = json.loads((Path(result["version_dir"]) / "validation_round_1.json").read_text(encoding="utf-8"))
    assert saved == v


def test_model_cannot_return_validator_error():
    issue = {"doc": None, "type": "validator_error", "detail": "d", "fix": "f"}
    with pytest.raises(ValidatorParseError):
        parse_validation(json.dumps(dict(VALIDATION, issues=[issue])))


def test_letter_feedback_and_fixes_are_in_prompt(tmp_path, fake_converse):
    tailor_application.generate_letter(_settings(tmp_path), "CV", JOB, "", feedback="shorter", fixes=["name company"])
    prompt = fake_converse[0]["messages"][0]["content"][0]["text"]
    assert "<user_feedback>\nshorter" in prompt and "- name company" in prompt


# --- critic loop (F18) ---

def _issue(doc, n=1):
    return [{"doc": doc, "type": "missing_keyword", "detail": f"d{i}", "fix": f"fix {doc} {i}"} for i in range(n)]


def _loop_fake(monkeypatch, validations):
    """Generators return numbered text (cv-1, letter-1, ...); validator returns `validations` in order,
    repeating the last one if the loop asks for more."""
    log = []

    def fake(settings, messages, system=None, tool_config=None):
        kind = "validator" if "strict reviewer" in system else "letter" if "cover letter" in system else "cv"
        log.append(kind)
        n = log.count(kind)
        if kind == "validator":
            text = json.dumps(validations[min(n, len(validations)) - 1])
        else:
            text = f"{kind}-{n}"
        return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}}

    monkeypatch.setattr(client, "converse", fake)
    return log


@pytest.mark.parametrize("cap", [1, 2, 3])
def test_loop_runs_exactly_cap_rounds_when_validator_always_fails(tmp_path, monkeypatch, cap):
    log = _loop_fake(monkeypatch, [dict(VALIDATION, issues=_issue("cv"))])
    result = tailor_application.handle(_settings(tmp_path, rounds=cap), JOB)
    assert log.count("validator") == cap
    assert len(result["rounds"]) == cap and result["passed"] is False
    files = sorted(p.name for p in Path(result["version_dir"]).glob("validation_round_*.json"))
    assert files == [f"validation_round_{i}.json" for i in range(1, cap + 1)]


def test_cap_returns_best_attempt_fewest_issues(tmp_path, monkeypatch):
    _loop_fake(monkeypatch, [dict(VALIDATION, fit_score=9, issues=_issue("cv", 1)),
                             dict(VALIDATION, fit_score=9, issues=_issue("cv", 3))])
    result = tailor_application.handle(_settings(tmp_path, rounds=2), JOB)
    assert result["passed"] is False
    assert result["cv"] == "cv-1\n" and result["cover_letter"] == "letter-1\n"
    assert len(result["validation"]["issues"]) == 1
    assert [r["issue_count"] for r in result["rounds"]] == [1, 3]
    saved = Path(result["version_dir"])
    assert (saved / "cv.md").read_text(encoding="utf-8") == "cv-1\n"


def test_cap_tie_on_issues_picks_highest_fit_score(tmp_path, monkeypatch):
    _loop_fake(monkeypatch, [dict(VALIDATION, fit_score=5, issues=_issue("cv", 2)),
                             dict(VALIDATION, fit_score=8, issues=_issue("cv", 2))])
    result = tailor_application.handle(_settings(tmp_path, rounds=2), JOB)
    assert result["cv"] == "cv-2\n" and result["validation"]["fit_score"] == 8
    assert result["rounds"] == [{"round": 1, "verdict": "FAIL", "issue_count": 2, "fit_score": 5},
                                {"round": 2, "verdict": "FAIL", "issue_count": 2, "fit_score": 8}]


def test_loop_stops_at_first_pass(tmp_path, monkeypatch):
    log = _loop_fake(monkeypatch, [dict(VALIDATION, issues=_issue("letter")),
                                   dict(VALIDATION, verdict="PASS", fit_score=8, issues=[])])
    result = tailor_application.handle(_settings(tmp_path, rounds=3), JOB)
    assert log.count("validator") == 2 and result["passed"] is True
    assert [r["verdict"] for r in result["rounds"]] == ["FAIL", "PASS"]
    assert result["cover_letter"] == "letter-2\n"


def test_fixes_from_failed_round_reach_next_generator(tmp_path, monkeypatch):
    prompts = []
    log = _loop_fake(monkeypatch, [dict(VALIDATION, issues=_issue("cv"))])
    original = client.converse

    def spy(settings, messages, system=None, tool_config=None):
        prompts.append(messages[0]["content"][0]["text"])
        return original(settings, messages, system, tool_config)

    monkeypatch.setattr(client, "converse", spy)
    tailor_application.handle(_settings(tmp_path, rounds=2), JOB)
    assert log == ["cv", "letter", "validator", "cv", "letter", "validator"]
    assert "fix cv 0" not in prompts[0] and "fix cv 0" in prompts[3]


def _spy_prompts(monkeypatch):
    prompts = []
    original = client.converse

    def spy(settings, messages, system=None, tool_config=None):
        prompts.append(messages[0]["content"][0]["text"])
        return original(settings, messages, system, tool_config)

    monkeypatch.setattr(client, "converse", spy)
    return prompts


def test_letter_only_issues_regenerate_letter_not_cv(tmp_path, monkeypatch):
    log = _loop_fake(monkeypatch, [dict(VALIDATION, issues=_issue("letter"))])
    prompts = _spy_prompts(monkeypatch)
    result = tailor_application.handle(_settings(tmp_path, rounds=2), JOB)
    assert log == ["cv", "letter", "validator", "letter", "validator"]
    assert "fix letter 0" in prompts[3] and "<tailored_cv>\ncv-1" in prompts[3]  # letter 2 built on the kept CV
    assert "cv-1\n" in prompts[4] and "letter-2\n" in prompts[4]  # round 2 validates kept CV + new letter
    assert len(result["rounds"]) == 2


def test_cv_only_issues_regenerate_cv_and_letter(tmp_path, monkeypatch):
    log = _loop_fake(monkeypatch, [dict(VALIDATION, issues=_issue("cv"))])
    prompts = _spy_prompts(monkeypatch)
    tailor_application.handle(_settings(tmp_path, rounds=2), JOB)
    assert log == ["cv", "letter", "validator", "cv", "letter", "validator"]
    assert "fix cv 0" in prompts[3]
    assert "cv-2" in prompts[4] and "fix cv 0" not in prompts[4]  # new letter from new CV; CV fixes stay with the CV
    assert "cv-2\n" in prompts[5] and "letter-2\n" in prompts[5]


def test_mixed_issues_send_each_fix_to_its_own_generator(tmp_path, monkeypatch):
    log = _loop_fake(monkeypatch, [dict(VALIDATION, issues=_issue("cv") + _issue("letter"))])
    prompts = _spy_prompts(monkeypatch)
    tailor_application.handle(_settings(tmp_path, rounds=2), JOB)
    assert log == ["cv", "letter", "validator", "cv", "letter", "validator"]
    assert "fix cv 0" in prompts[3] and "fix letter 0" not in prompts[3]
    assert "fix letter 0" in prompts[4] and "fix cv 0" not in prompts[4]


def test_validator_error_round_regenerates_nothing(tmp_path, monkeypatch):
    calls = _validator_replies(monkeypatch, ["bad", "bad", VALIDATION_REPLY])
    result = tailor_application.handle(_settings(tmp_path, rounds=2), JOB)
    assert len(calls) == 3  # 2 attempts in round 1, 1 in round 2, same prompt (no regeneration)
    assert calls[0] == calls[2]
    assert [r["issue_count"] for r in result["rounds"]] == [1, 1]


# --- re-prompts (F20) ---

PASSED = dict(VALIDATION, verdict="PASS", fit_score=8, issues=[])


def test_reprompt_letter_keeps_cv_and_revalidates(tmp_path, monkeypatch):
    log = _loop_fake(monkeypatch, [PASSED])
    prompts = _spy_prompts(monkeypatch)
    settings = _settings(tmp_path)
    first = tailor_application.handle(settings, JOB)
    n_log, n_prompts = len(log), len(prompts)
    second = tailor_application.handle(settings, JOB, feedback="make the cover letter shorter", target="letter")
    assert log[n_log:] == ["letter", "validator"]  # CV not regenerated, validation runs again
    assert second["cv"] == first["cv"] == "cv-1\n"
    assert second["cover_letter"] == "letter-2\n"
    assert "<previous_letter>\nletter-1" in prompts[n_prompts + 0] and "make the cover letter shorter" in prompts[n_prompts + 0]
    assert "<tailored_cv>\ncv-1" in prompts[n_prompts + 0]
    assert "cv-1\n" in prompts[n_prompts + 1] and "letter-2\n" in prompts[n_prompts + 1]
    assert (Path(second["version_dir"]) / "cv.md").read_text(encoding="utf-8") == "cv-1\n"
    assert Path(second["version_dir"]).name == "v2"


def test_reprompt_cv_regenerates_cv_from_previous_and_letter_follows(tmp_path, monkeypatch):
    log = _loop_fake(monkeypatch, [PASSED])
    prompts = _spy_prompts(monkeypatch)
    settings = _settings(tmp_path)
    tailor_application.handle(settings, JOB)
    n_log, n_prompts = len(log), len(prompts)
    feedback = "emphasize my Kubernetes experience in the CV"
    result = tailor_application.handle(settings, JOB, feedback=feedback, target="cv")
    assert log[n_log:] == ["cv", "letter", "validator"]
    assert "<previous_cv>\ncv-1" in prompts[n_prompts + 0] and feedback in prompts[n_prompts + 0]
    assert "<original_cv>" in prompts[n_prompts + 0]  # facts still come from the original CV
    assert "<tailored_cv>\ncv-2" in prompts[n_prompts + 1] and "<previous_letter>\nletter-1" in prompts[n_prompts + 1]
    assert result["cv"] == "cv-2\n" and result["cover_letter"] == "letter-2\n"


def test_reprompt_both_starts_from_previous_documents(tmp_path, monkeypatch):
    log = _loop_fake(monkeypatch, [PASSED])
    prompts = _spy_prompts(monkeypatch)
    settings = _settings(tmp_path)
    tailor_application.handle(settings, JOB)
    n_log, n_prompts = len(log), len(prompts)
    tailor_application.handle(settings, JOB, feedback="more formal")
    assert log[n_log:] == ["cv", "letter", "validator"]
    assert "<previous_cv>\ncv-1" in prompts[n_prompts + 0] and "<previous_letter>\nletter-1" in prompts[n_prompts + 1]


def test_reprompt_base_is_best_attempt_of_previous_call(tmp_path, monkeypatch):
    log = _loop_fake(monkeypatch, [dict(VALIDATION, issues=_issue("cv", 1)),
                                   dict(VALIDATION, issues=_issue("cv", 3)), PASSED])
    prompts = _spy_prompts(monkeypatch)
    settings = _settings(tmp_path, rounds=2)
    first = tailor_application.handle(settings, JOB)
    assert first["cv"] == "cv-1\n"  # best attempt, not the last
    n_prompts = len(prompts)
    tailor_application.handle(settings, JOB, feedback="shorter letter", target="letter")
    assert "<previous_letter>\nletter-1" in prompts[n_prompts + 0] and "<tailored_cv>\ncv-1" in prompts[n_prompts + 0]


def test_reprompt_fix_rounds_keep_previous_base(tmp_path, monkeypatch):
    log = _loop_fake(monkeypatch, [PASSED, dict(VALIDATION, issues=_issue("letter")), PASSED])
    prompts = _spy_prompts(monkeypatch)
    settings = _settings(tmp_path, rounds=2)
    tailor_application.handle(settings, JOB)
    n_log, n_prompts = len(log), len(prompts)
    result = tailor_application.handle(settings, JOB, feedback="shorter", target="letter")
    assert log[n_log:] == ["letter", "validator", "letter", "validator"]
    assert "<previous_letter>\nletter-1" in prompts[n_prompts + 2] and "fix letter 0" in prompts[n_prompts + 2]
    assert result["passed"] is True and result["cv"] == "cv-1\n"


def test_first_call_has_no_previous_documents(tmp_path, monkeypatch):
    _loop_fake(monkeypatch, [PASSED])
    prompts = _spy_prompts(monkeypatch)
    tailor_application.handle(_settings(tmp_path), JOB, feedback="shorter", target="letter")
    # nothing to start from yet: both documents are generated, without previous blocks
    assert len(prompts) == 3
    assert all("<previous_" not in p for p in prompts)


def test_other_job_does_not_reuse_previous_documents(tmp_path, monkeypatch):
    log = _loop_fake(monkeypatch, [PASSED])
    prompts = _spy_prompts(monkeypatch)
    settings = _settings(tmp_path)
    tailor_application.handle(settings, JOB)
    n_log, n_prompts = len(log), len(prompts)
    tailor_application.handle(settings, FETCHED_JOB, feedback="shorter", target="letter")
    assert log[n_log:] == ["cv", "letter", "validator"]
    assert all("<previous_" not in p for p in prompts)


def test_original_cv_unchanged_after_full_run_and_two_reprompts(tmp_path, monkeypatch):
    cv = tmp_path / "cv" / "original_cv.md"
    cv.parent.mkdir()
    cv.write_bytes(Path(EXAMPLE_CV).read_bytes())
    before = (hashlib.sha256(cv.read_bytes()).hexdigest(), cv.stat().st_mtime_ns)
    log = _loop_fake(monkeypatch, [dict(VALIDATION, issues=_issue("cv")), PASSED])
    settings = _settings(tmp_path, cv_path=str(cv), rounds=2)
    tailor_application.handle(settings, JOB)
    tailor_application.handle(settings, JOB, feedback="make the cover letter shorter", target="letter")
    tailor_application.handle(settings, JOB, feedback="emphasize my Kubernetes experience in the CV", target="cv")
    assert log.count("cv") >= 3  # the CV generator really ran (fix round + cv re-prompt)
    assert (hashlib.sha256(cv.read_bytes()).hexdigest(), cv.stat().st_mtime_ns) == before
    assert sorted(p.name for p in cv.parent.iterdir()) == ["original_cv.md"]  # nothing written next to it


def test_invalid_target_rejected(tmp_path, fake_converse):
    with pytest.raises(ValueError):
        tailor_application.handle(_settings(tmp_path), JOB, target="email")
    assert fake_converse == []
