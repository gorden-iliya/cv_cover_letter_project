from types import SimpleNamespace

import pytest

import main
from agent.chat import GREETING, MAX_TOOL_TURNS, ChatAgent
from agent.config import Settings
from agent.cv import MissingCVError


def _settings(cv_path="cv/original_cv.example.md"):
    return Settings("model-x", "eu-west-1", ("jobs.lever.co",), 500, 2, False,
                    cv_path, "cv/profile.md", "output")


def _text_reply(text):
    return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [{"text": text}]}}}


def _tool_reply(name, tool_input, tid="t1"):
    return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
        {"toolUse": {"toolUseId": tid, "name": name, "input": tool_input}}]}}}


class FakeConverse:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, settings, messages, system=None, tool_config=None):
        self.calls.append({"messages": [dict(m) for m in messages], "system": system, "tool_config": tool_config})
        return self.replies.pop(0)


def _fake_tool(name, handle):
    spec = {"name": name, "description": "d", "inputSchema": {"json": {"type": "object"}}}
    return SimpleNamespace(TOOL_SPEC=spec, handle=handle)


def test_no_job_text_gets_model_reply_without_tools():
    fake = FakeConverse([_text_reply("Please paste a job URL or the job text.")])
    agent = ChatAgent(_settings(), [], converse=fake)
    assert agent.send("hi") == "Please paste a job URL or the job text."
    call = fake.calls[0]
    assert "ask them for a job URL or the job text" in call["system"]
    assert call["tool_config"] is None


def test_tool_use_round_trip():
    seen = {}

    def handle(settings, **kw):
        seen.update(kw)
        return {"ok": True}

    fake = FakeConverse([_tool_reply("my_tool", {"a": 1}), _text_reply("done")])
    agent = ChatAgent(_settings(), [_fake_tool("my_tool", handle)], converse=fake)
    assert agent.send("go") == "done"
    assert seen == {"a": 1}
    assert fake.calls[0]["tool_config"] == {"tools": [{"toolSpec": agent.tools["my_tool"].TOOL_SPEC}]}
    result = agent.messages[2]["content"][0]["toolResult"]
    assert result == {"toolUseId": "t1", "content": [{"json": {"ok": True}}], "status": "success"}


def test_tool_error_and_unknown_tool_reported_to_model():
    def boom(settings, **kw):
        raise RuntimeError("bad")

    fake = FakeConverse([_tool_reply("boom", {}), _tool_reply("nope", {}, "t2"), _text_reply("ok")])
    agent = ChatAgent(_settings(), [_fake_tool("boom", boom)], converse=fake)
    agent.send("go")
    r1 = agent.messages[2]["content"][0]["toolResult"]
    r2 = agent.messages[4]["content"][0]["toolResult"]
    assert r1["status"] == "error" and "bad" in r1["content"][0]["json"]["message"]
    assert r2["status"] == "error" and "Unknown tool" in r2["content"][0]["json"]["message"]


def test_tool_turn_cap():
    fake = FakeConverse([_tool_reply("t", {}, f"id{i}") for i in range(MAX_TOOL_TURNS)])
    agent = ChatAgent(_settings(), [_fake_tool("t", lambda s, **k: {})], converse=fake)
    assert "too many tool steps" in agent.send("go")
    assert len(fake.calls) == MAX_TOOL_TURNS


def test_chat_loop_greets_and_exits():
    out = []
    inputs = iter(["", "hello", "exit"])
    agent = SimpleNamespace(send=lambda t: f"echo {t}")
    main.chat_loop(agent, read=lambda prompt: next(inputs), write=out.append)
    assert out[0] == GREETING
    assert "job URL" in GREETING and "job posting text" in GREETING
    assert out[1:] == ["\nagent> echo hello"]


def test_chat_loop_handles_eof():
    def read(prompt):
        raise EOFError

    out = []
    main.chat_loop(SimpleNamespace(send=None), read=read, write=out.append)
    assert out == [GREETING, ""]


def test_missing_cv_stops_before_any_model_call(tmp_path):
    missing = str(tmp_path / "nope.md")
    fake = FakeConverse([])
    agent = ChatAgent(_settings(missing), [], converse=fake)
    with pytest.raises(MissingCVError) as err:
        agent.send("https://jobs.lever.co/acme/123")
    assert missing in str(err.value)
    assert fake.calls == []


def test_missing_cv_inside_tool_is_not_swallowed():
    def handle(settings, **kw):
        raise MissingCVError("gone.md")

    fake = FakeConverse([_tool_reply("t", {})])
    agent = ChatAgent(_settings(), [_fake_tool("t", handle)], converse=fake)
    with pytest.raises(MissingCVError):
        agent.send("go")


def test_main_exits_with_message_naming_missing_cv(tmp_path, monkeypatch, capsys):
    missing = str(tmp_path / "missing_cv.md")
    monkeypatch.setattr(main, "load_settings", lambda: _settings(missing))
    loop = main.chat_loop
    monkeypatch.setattr(main, "chat_loop", lambda agent: loop(
        agent, read=lambda prompt: "https://jobs.lever.co/acme/123", write=lambda s: None))
    assert main.main() == 1
    err = capsys.readouterr().err
    assert "Original CV not found" in err and missing in err


def test_tool_config_sent_to_bedrock_has_exactly_the_two_spec_tools(monkeypatch):
    from agent.browser import ALLOWED_MCP_TOOLS
    from tools import TOOLS

    fake = FakeConverse([_text_reply("Paste a job URL.")])
    # main() builds the agent with tools.TOOLS; capture that exact agent.
    monkeypatch.setattr(main, "load_settings", _settings)
    monkeypatch.setattr(main, "chat_loop", lambda agent: agent.send("hi"))
    monkeypatch.setattr(main, "ChatAgent", lambda s, tools, **kw: ChatAgent(s, tools, converse=fake, **kw))
    main.main()

    sent = fake.calls[0]["tool_config"]
    assert list(sent) == ["tools"]
    names = [t["toolSpec"]["name"] for t in sent["tools"]]
    assert sorted(names) == ["fetch_job", "tailor_application"]
    assert sent == {"tools": [{"toolSpec": t.TOOL_SPEC} for t in TOOLS]}
    assert not set(names) & ALLOWED_MCP_TOOLS
    assert not set(names) & {"fill", "fill_form", "press_key", "evaluate_script", "navigate_page", "take_snapshot"}


def test_fetch_failure_reaches_model_then_pasted_text_is_tailored():
    from agent.chat import CHAT_SYSTEM

    fail = {"ok": False, "reason": "login_required", "message": "The page asks you to log in."}
    tailored = []
    fetch = _fake_tool("fetch_job", lambda s, **kw: fail)
    tailor = _fake_tool("tailor_application", lambda s, **kw: tailored.append(kw) or {"version_dir": "v1"})
    pasted = "Senior DevOps Engineer at Acme. Requirements: Kubernetes, Terraform."
    fake = FakeConverse([
        _tool_reply("fetch_job", {"url": "https://jobs.lever.co/acme/1"}),
        _text_reply("The page needs a login. Please paste the job text."),
        _tool_reply("tailor_application", {"job": {"description": pasted, "company": "Acme"}}, "t2"),
        _text_reply("Saved to v1."),
    ])
    agent = ChatAgent(_settings(), [fetch, tailor], converse=fake)

    reply = agent.send("https://jobs.lever.co/acme/1")
    assert "paste the job text" in reply
    result = agent.messages[2]["content"][0]["toolResult"]
    assert result["status"] == "success" and result["content"][0]["json"] == fail  # model sees the reason
    assert "If fetching a job fails, explain the reason in one sentence and ask the user to paste the job text" in CHAT_SYSTEM

    agent.send(pasted)
    assert tailored == [{"job": {"description": pasted, "company": "Acme"}}]


def test_not_allowed_site_prints_exact_message_and_never_opens_browser(monkeypatch):
    from agent.urls import NOT_ALLOWED_MESSAGE
    from tools import TOOLS, fetch_job

    opened = []
    monkeypatch.setattr(fetch_job, "open_browser", lambda *a, **k: opened.append(a))
    out = []
    fake = FakeConverse([_tool_reply("fetch_job", {"url": "https://www.linkedin.com/jobs/view/1"}),
                         _text_reply("That site is not allowed. Please paste the job text.")])
    agent = ChatAgent(_settings(), TOOLS, converse=fake, on_tool_result=main.result_printer(out.append))
    agent.send("https://www.linkedin.com/jobs/view/1")

    result = agent.messages[2]["content"][0]["toolResult"]["content"][0]["json"]
    assert result == {"ok": False, "reason": "not_allowed", "message": NOT_ALLOWED_MESSAGE}
    assert out == ["\n" + NOT_ALLOWED_MESSAGE]
    assert opened == []


def test_result_printer_ignores_other_fetch_outcomes():
    out = []
    printer = main.result_printer(out.append)
    printer("fetch_job", {"ok": False, "reason": "captcha", "message": "m"}, 1.0)
    printer("fetch_job", {"ok": True, "job": {}}, 1.0)
    assert out == []


def test_new_job_url_in_same_chat_fetches_again_and_starts_new_job_folder(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from agent import client
    from agent.chat import CHAT_SYSTEM
    from tools import tailor_application

    jobs = {
        "https://jobs.lever.co/acme/1": {"title": "DevOps Engineer", "company": "Acme", "location": "Remote",
                                         "source_host": "jobs.lever.co", "final_url": "https://jobs.lever.co/acme/1",
                                         "description": "Acme needs Kubernetes."},
        "https://jobs.lever.co/globex/2": {"title": "SRE", "company": "Globex", "location": "Berlin",
                                           "source_host": "jobs.lever.co", "final_url": "https://jobs.lever.co/globex/2",
                                           "description": "Globex needs Terraform."},
    }
    fetched = []
    fetch = _fake_tool("fetch_job", lambda s, url: fetched.append(url) or {"ok": True, "job": jobs[url]})
    passed = json.dumps({"verdict": "PASS", "fit_score": 8, "issues": [], "fit_summary": "fits", "gaps": []})
    prompts = []

    def model(settings, messages, system=None, tool_config=None):
        prompt = messages[0]["content"][0]["text"]
        prompts.append(prompt)
        kind = "validator" if "strict reviewer" in system else "letter" if "cover letter" in system else "cv"
        text = passed if kind == "validator" else f"{kind} for {'Globex' if 'Globex' in prompt else 'Acme'}"
        return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}}

    monkeypatch.setattr(client, "converse", model)
    settings = Settings("model-x", "eu-west-1", ("jobs.lever.co",), 500, 1, False,
                        "cv/original_cv.example.md", str(tmp_path / "no_profile.md"), str(tmp_path / "out"))
    a, b = jobs["https://jobs.lever.co/acme/1"], jobs["https://jobs.lever.co/globex/2"]
    fake = FakeConverse([
        _tool_reply("fetch_job", {"url": "https://jobs.lever.co/acme/1"}, "a1"),
        _tool_reply("tailor_application", {"job": a}, "a2"), _text_reply("Saved."),
        _tool_reply("tailor_application", {"job": a, "feedback": "make the cover letter shorter",
                                           "target": "letter"}, "a3"), _text_reply("Saved."),
        _tool_reply("fetch_job", {"url": "https://jobs.lever.co/globex/2"}, "b1"),
        _tool_reply("tailor_application", {"job": b}, "b2"), _text_reply("Saved."),
    ])
    agent = ChatAgent(settings, [fetch, tailor_application], converse=fake)

    agent.send("https://jobs.lever.co/acme/1")
    agent.send("make the cover letter shorter")
    n_prompts = len(prompts)
    agent.send("https://jobs.lever.co/globex/2")

    assert fetched == ["https://jobs.lever.co/acme/1", "https://jobs.lever.co/globex/2"]  # job B fetched again
    out = Path(settings.output_dir)
    assert sorted(p.name for p in (out / "acme_devops-engineer").iterdir()) == ["v1", "v2"]
    assert sorted(p.name for p in (out / "globex_sre").iterdir()) == ["v1"]  # new folder, starts at v1
    assert "Globex" in (out / "globex_sre" / "v1" / "job.md").read_text(encoding="utf-8")
    # job B is a fresh full run: CV + letter + validator, nothing carried over from job A
    assert len(prompts) - n_prompts == 3
    assert all("<previous_" not in p and "Acme" not in p for p in prompts[n_prompts:])
    assert "A new job URL (or new job text) in the same chat starts a new job" in CHAT_SYSTEM


def test_model_cannot_call_an_mcp_tool_directly():
    from tools import TOOLS

    called = []
    fake = FakeConverse([_tool_reply("navigate_page", {"url": "https://evil.example"}), _text_reply("ok")])
    agent = ChatAgent(_settings(), TOOLS, converse=fake)
    import agent.browser as browser
    orig = browser.open_browser
    browser.open_browser = lambda *a, **k: called.append(a)  # would record any browser start
    try:
        agent.send("go")
    finally:
        browser.open_browser = orig
    result = agent.messages[2]["content"][0]["toolResult"]
    assert result["status"] == "error" and "Unknown tool: navigate_page" in result["content"][0]["json"]["message"]
    assert called == []
