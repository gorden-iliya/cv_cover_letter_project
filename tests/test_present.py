from types import SimpleNamespace

import main
from agent.chat import ChatAgent
from agent.present import format_result, round_line
from tests.test_chat import FakeConverse, _fake_tool, _settings, _text_reply, _tool_reply


def _result(rounds=None, gaps=("Go",)):
    rounds = rounds or [{"round": 1, "verdict": "FAIL", "issue_count": 2, "fit_score": 6},
                        {"round": 2, "verdict": "PASS", "issue_count": 0, "fit_score": 8}]
    return {"version_dir": "output/acme_sre/v1", "cv": "CV TEXT\n", "cover_letter": "LETTER TEXT\n",
            "validation": {"verdict": "PASS", "fit_score": 8, "issues": [],
                           "fit_summary": "Strong AWS match.", "gaps": list(gaps)},
            "rounds": rounds, "passed": True}


def test_round_line_matches_spec_example():
    assert round_line(_result()["rounds"]) == "Round 1: FAIL (2 issues) → Round 2: PASS, fit 8/10"


def test_round_line_singular_issue():
    assert round_line([{"round": 1, "verdict": "FAIL", "issue_count": 1, "fit_score": 3}]) == \
        "Round 1: FAIL (1 issue)"


def test_format_result_has_all_parts_in_order():
    out = format_result(_result(), 42.25)
    parts = ["Round 1: FAIL (2 issues) → Round 2: PASS, fit 8/10", "CV TEXT", "LETTER TEXT",
             "Strong AWS match.", "- Go", "Saved to: output/acme_sre/v1", "Total run time: 42.2s"]
    positions = [out.index(p) for p in parts]
    assert positions == sorted(positions)
    assert "8/10" in out.split("CV TEXT")[0]


def test_format_result_no_gaps():
    assert "(none)" in format_result(_result(gaps=()), 1.0).split("# Gaps")[1]


def test_passed_result_has_no_not_passed_notice():
    assert "NOT PASSED" not in format_result(_result(), 1.0)


def test_unresolved_issues_listed_above_documents():
    res = _result(rounds=[{"round": 1, "verdict": "FAIL", "issue_count": 2, "fit_score": 6}])
    res["passed"] = False
    res["validation"].update(verdict="FAIL", issues=[
        {"doc": "cv", "type": "invented_fact", "detail": "claims Go", "fix": "remove Go"},
        {"doc": None, "type": "validator_error", "detail": "bad JSON", "fix": "re-run the validator"}])
    out = format_result(res, 1.0)
    head = out.split("# Tailored CV")[0]
    assert "NOT PASSED" in head and "1 round(s)" in head
    assert "- [cv] invented_fact: claims Go (fix: remove Go)" in head
    assert "- [general] validator_error: bad JSON" in head


# F23 end to end: real tailor_application loop with the validator mocked to always FAIL, then the printer.
def test_always_fail_run_prints_remaining_issues_above_documents(tmp_path, monkeypatch):
    from tests.test_tailor_application import JOB, VALIDATION, _loop_fake
    from tests.test_tailor_application import _settings as tailor_settings
    from tools import tailor_application
    _loop_fake(monkeypatch, [dict(VALIDATION, issues=[
        {"doc": "letter", "type": "length", "detail": "too long", "fix": "cut to 200 words"}])])
    result = tailor_application.handle(tailor_settings(tmp_path, rounds=2), JOB)
    out = []
    main.result_printer(write=out.append)("tailor_application", result, 2.0)
    text = out[0]
    assert text.lstrip().startswith("Round 1: FAIL (1 issue) → Round 2: FAIL (1 issue)")
    notice = text.index("NOT PASSED")
    assert notice < text.index("- [letter] length: too long (fix: cut to 200 words)") < text.index("# Tailored CV")
    assert text.index("# Tailored CV") < text.index("cv-") and text.index("# Cover letter") < text.index("letter-")


def test_chat_agent_reports_tool_result_with_elapsed_time():
    seen = []
    tool = _fake_tool("tailor_application", lambda s, **k: _result())
    fake = FakeConverse([_tool_reply("tailor_application", {"job": {"description": "x"}}), _text_reply("ok")])
    agent = ChatAgent(_settings(), [tool], converse=fake,
                      on_tool_result=lambda name, res, t: seen.append((name, res, t)))
    agent.send("job text")
    assert len(seen) == 1
    assert seen[0][0] == "tailor_application" and seen[0][1]["version_dir"] == "output/acme_sre/v1"
    assert seen[0][2] >= 0


def test_failed_tool_is_not_reported():
    seen = []

    def boom(settings, **kw):
        raise RuntimeError("bad")

    fake = FakeConverse([_tool_reply("tailor_application", {}), _text_reply("ok")])
    agent = ChatAgent(_settings(), [_fake_tool("tailor_application", boom)], converse=fake,
                      on_tool_result=lambda *a: seen.append(a))
    agent.send("go")
    assert seen == []


def test_result_printer_prints_only_tailor_application():
    out = []
    printer = main.result_printer(write=out.append)
    printer("fetch_job", {"ok": True}, 1.0)
    assert out == []
    printer("tailor_application", _result(), 3.0)
    assert len(out) == 1 and "Saved to: output/acme_sre/v1" in out[0] and "Total run time: 3.0s" in out[0]
