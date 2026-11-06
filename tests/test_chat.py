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
