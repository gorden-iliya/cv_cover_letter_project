"""fetch_job with a fake MCP browser and fake Bedrock (no Chrome, no real model)."""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from agent import browser, client
from agent.config import Settings
from agent.urls import NOT_ALLOWED_MESSAGE
from tools import TOOLS, fetch_job

JOB_URL = "https://jobs.lever.co/acme/123"
DESCRIPTION = "We are hiring a DevOps engineer. " * 10
SNAPSHOT = ('## Latest page snapshot\nuid=1_0 RootWebArea "DevOps Engineer - Acme" url="https://jobs.lever.co/acme/123"\n'
            '  uid=1_1 heading "DevOps Engineer" level="2"\n  uid=1_2 "Kubernetes, Terraform"\n'
            '  uid=1_3 link "Apply for this job" url="https://jobs.lever.co/acme/123/apply"\n')
SNAPSHOT_MORE = SNAPSHOT + '  uid=1_9 button "Show more"\n'


def _settings(sites=("jobs.lever.co",), headless=False):
    return Settings("model-x", "eu-west-1", sites, 500, 2, headless, "cv/original_cv.example.md", "p.md", "out")


def _pages(url):
    return f"## Pages\n1: about:blank\n2: Acme ({url}) [selected]"


class FakeBrowser:
    def __init__(self, snapshots=(SNAPSHOT,), final_url=JOB_URL, wait_error=False, fail_on=None):
        self.calls = []
        self.snapshots = list(snapshots)
        self.final_url = final_url
        self.wait_error = wait_error
        self.fail_on = fail_on

    async def call(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        if name == self.fail_on:
            raise browser.BrowserToolError(f"{name} failed")
        if name == "new_page":
            return _pages(arguments["url"])
        if name == "wait_for":
            if self.wait_error:
                raise browser.BrowserToolError("Timed out")
            return "found"
        if name == "take_snapshot":
            return self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]
        if name == "list_pages":
            return _pages(self.final_url)
        return "ok"

    @property
    def names(self):
        return [c[0] for c in self.calls]


def _opener(fake):
    opened = []

    @asynccontextmanager
    async def opener(settings):
        opened.append(settings)
        yield fake
    opener.opened = opened
    return opener


@pytest.fixture
def extraction(monkeypatch):
    state = {"reply": {"page": "job", "title": "DevOps Engineer", "company": "Acme", "location": "Remote",
                       "description": DESCRIPTION}, "calls": []}

    def fake(settings, messages, system=None, tool_config=None):
        state["calls"].append({"messages": messages, "system": system, "tool_config": tool_config})
        reply = state["reply"]
        text = reply if isinstance(reply, str) else "```json\n" + json.dumps(reply) + "\n```"
        return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [{"text": text}]}}}

    monkeypatch.setattr(client, "converse", fake)
    return state


def _run(fake, url=JOB_URL, settings=None):
    opener = _opener(fake)
    result = asyncio.run(fetch_job.fetch(settings or _settings(), url, opener=opener))
    return result, opener


def test_tool_is_registered_with_url_input():
    assert fetch_job in TOOLS
    spec = fetch_job.TOOL_SPEC
    assert spec["name"] == "fetch_job"
    assert spec["inputSchema"]["json"]["required"] == ["url"]


def test_success_returns_all_job_fields(extraction):
    fake = FakeBrowser()
    result, _ = _run(fake)
    assert result == {"ok": True, "job": {
        "title": "DevOps Engineer", "company": "Acme", "location": "Remote", "source_host": "jobs.lever.co",
        "final_url": JOB_URL, "description": DESCRIPTION.strip()}}


def test_fixed_sequence_and_page_id(extraction):
    fake = FakeBrowser()
    _run(fake)
    assert fake.names == ["new_page", "wait_for", "take_snapshot", "list_pages"]
    assert fake.calls[0][1]["url"] == JOB_URL
    wait = fake.calls[1][1]
    assert wait["pageId"] == 2 and wait["text"] == fetch_job.WAIT_TEXTS and wait["timeout"] == 10_000
    assert fake.calls[2][1] == {"pageId": 2}


def test_show_more_clicked_once_then_second_snapshot(extraction):
    fake = FakeBrowser(snapshots=(SNAPSHOT_MORE, SNAPSHOT))
    _run(fake)
    assert fake.names == ["new_page", "wait_for", "take_snapshot", "click", "take_snapshot", "list_pages"]
    assert fake.calls[3][1] == {"pageId": 2, "uid": "1_9"}


def test_bedrock_runs_only_after_browser_sequence(extraction, monkeypatch):
    # The browser steps never wait on a model reply: the single extraction call comes after list_pages.
    events = []
    fake = FakeBrowser(snapshots=(SNAPSHOT_MORE, SNAPSHOT))
    real_call, real_converse = fake.call, client.converse

    async def call(name, arguments=None):
        events.append(name)
        return await real_call(name, arguments)

    def converse(*args, **kwargs):
        events.append("bedrock")
        return real_converse(*args, **kwargs)

    fake.call = call
    monkeypatch.setattr(client, "converse", converse)
    _run(fake)
    assert events == ["new_page", "wait_for", "take_snapshot", "click", "take_snapshot", "list_pages", "bedrock"]


def test_read_more_button_detected():
    assert fetch_job.show_more_uid('uid=3_4 button "Read More about the role"') == "3_4"
    assert fetch_job.show_more_uid('uid=3_4 link "Read more"') is None
    assert fetch_job.show_more_uid(SNAPSHOT) is None


def test_wait_for_timeout_is_not_a_failure(extraction):
    fake = FakeBrowser(wait_error=True)
    result, _ = _run(fake)
    assert result["ok"] is True
    assert "take_snapshot" in fake.names


def test_one_extraction_call_with_wrapped_page_text_and_no_tools(extraction):
    _run(FakeBrowser())
    assert len(extraction["calls"]) == 1
    call = extraction["calls"][0]
    assert call["tool_config"] is None  # the model never chooses MCP tools
    prompt = call["messages"][0]["content"][0]["text"]
    assert prompt.startswith("<job_posting>\n") and "\n</job_posting>" in prompt
    assert "Kubernetes, Terraform" in prompt
    assert "uid=" not in prompt and 'url="' not in prompt


def test_two_sites_one_extraction_call_each(extraction):
    gh_url = "https://boards.greenhouse.io/globex/jobs/42"
    gh_snapshot = ('uid=2_0 RootWebArea "Job Application for SRE at Globex"\n'
                   '  uid=2_1 heading "Site Reliability Engineer"\n  uid=2_2 "Globex, Berlin"\n')
    settings = _settings(sites=("jobs.lever.co", "boards.greenhouse.io"))
    results = []
    for url, snap in ((JOB_URL, SNAPSHOT), (gh_url, gh_snapshot)):
        before = len(extraction["calls"])
        result, _ = _run(FakeBrowser(snapshots=(snap,), final_url=url), url=url, settings=settings)
        assert len(extraction["calls"]) == before + 1
        prompt = extraction["calls"][-1]["messages"][0]["content"][0]["text"]
        assert prompt.startswith("<job_posting>\n") and "\n</job_posting>" in prompt
        results.append(result)
    assert [r["job"]["source_host"] for r in results] == ["jobs.lever.co", "boards.greenhouse.io"]
    for r in results:
        assert r["ok"] is True
        assert set(r["job"]) == {"title", "company", "location", "source_host", "final_url", "description"}
        assert all(r["job"].values())
    # Both sites share the same system prompt (generic, no per-site branch).
    assert extraction["calls"][0]["system"] == extraction["calls"][1]["system"]


def test_no_site_specific_code():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    code = "".join((root / p).read_text(encoding="utf-8").lower()
                   for p in ("tools/fetch_job.py", "prompts/job_extractor.py", "agent/browser.py"))
    for site in ("lever", "greenhouse", "comeet", "linkedin", "workday"):
        assert site not in code


@pytest.mark.parametrize("url", ["https://www.linkedin.com/jobs/view/1", "file:///C:/secret.txt",
                                 "chrome://settings", "javascript:alert(1)", "not a url"])
def test_disallowed_url_rejected_before_browser(extraction, url):
    fake = FakeBrowser()
    result, opener = _run(fake, url=url)
    assert result == {"ok": False, "reason": "not_allowed", "message": NOT_ALLOWED_MESSAGE}
    assert opener.opened == [] and fake.calls == [] and extraction["calls"] == []


@pytest.mark.parametrize("url", ["file://jobs.lever.co/C:/secret.txt", "ftp://jobs.lever.co/acme/1",
                                 "chrome://jobs.lever.co/settings", "view-source:https://jobs.lever.co/acme/1"])
def test_non_http_scheme_rejected_even_with_allowed_host(extraction, url):
    fake = FakeBrowser()
    result, opener = _run(fake, url=url)
    assert result["reason"] == "not_allowed"
    assert opener.opened == [] and fake.calls == [] and extraction["calls"] == []


def test_subdomain_of_allowed_host_accepted(extraction):
    result, _ = _run(FakeBrowser(final_url="https://eu.jobs.lever.co/acme/1"), url="https://eu.jobs.lever.co/acme/1")
    assert result["ok"] is True and result["job"]["source_host"] == "eu.jobs.lever.co"


def test_lookalike_host_rejected(extraction):
    result, _ = _run(FakeBrowser(), url="https://evil-jobs.lever.co.attacker.com/x")
    assert result["reason"] == "not_allowed"


def test_redirect_off_allowlist_rejected_and_no_job_text_used(extraction):
    fake = FakeBrowser(final_url="https://evil.example.com/phish")
    result, _ = _run(fake)
    assert fake.names[-1] == "list_pages"
    assert result == {"ok": False, "reason": "not_allowed", "message": NOT_ALLOWED_MESSAGE}
    assert extraction["calls"] == []


def test_redirect_check_uses_list_pages_url_not_requested_url(extraction):
    # new_page reports the requested (allowed) URL; only list_pages shows where the page ended up.
    fake = FakeBrowser(final_url="http://127.0.0.1:8000/landing")
    result, _ = _run(fake, settings=_settings(sites=("jobs.lever.co",)))
    assert fake.calls[0] == ("new_page", {"url": JOB_URL, "timeout": fetch_job.NAVIGATION_TIMEOUT_MS})
    assert result["reason"] == "not_allowed" and "job" not in result


def test_redirect_within_allowlist_reports_final_url(extraction):
    final = "https://eu.jobs.lever.co/acme/123"
    result, _ = _run(FakeBrowser(final_url=final))
    assert result["ok"] is True
    assert result["job"]["final_url"] == final and result["job"]["source_host"] == "eu.jobs.lever.co"


@pytest.mark.parametrize("page",["captcha", "login_required", "empty_page"])
def test_blocked_pages_return_reason(extraction, page):
    extraction["reply"] = {"page": page, "title": "", "company": "", "location": "", "description": ""}
    result, _ = _run(FakeBrowser())
    assert result["ok"] is False and result["reason"] == page and result["message"]


def test_near_empty_description_is_empty_page(extraction):
    extraction["reply"] = {"page": "job", "title": "X", "company": "Y", "location": "", "description": "Apply"}
    result, _ = _run(FakeBrowser())
    assert result["reason"] == "empty_page"


def test_browser_error_is_fetch_failed(extraction):
    result, _ = _run(FakeBrowser(fail_on="new_page"))
    assert result["ok"] is False and result["reason"] == "fetch_failed"
    assert extraction["calls"] == []


def test_invalid_extraction_json_is_fetch_failed(extraction):
    extraction["reply"] = "sorry, no json"
    result, _ = _run(FakeBrowser())
    assert result["reason"] == "fetch_failed"


def test_selected_page_parsing():
    assert fetch_job.selected_page(_pages("https://a.b/c?x=1")) == (2, "https://a.b/c?x=1")
    assert fetch_job.selected_page("## Pages\n1: about:blank [selected]") == (1, "about:blank")
    assert fetch_job.selected_page("## Pages\n3: Job (Senior) (https://x.y/z) [selected]") == (3, "https://x.y/z")


# --- MCP client wrapper and server start command ---

class FakeSession:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append(name)

        class Block:
            text = "result"

        class Result:
            content = [Block()]
            is_error = False
        return Result()


@pytest.mark.parametrize("name", ["fill", "fill_form", "press_key", "evaluate_script", "take_screenshot"])
def test_wrapper_rejects_tools_outside_allowlist(name):
    session = FakeSession()
    wrapper = browser.BrowserSession(session)
    with pytest.raises(browser.DisallowedToolError):
        asyncio.run(wrapper.call(name, {}))
    assert session.calls == []


def test_wrapper_allowlist_is_exact():
    assert browser.ALLOWED_MCP_TOOLS == {"navigate_page", "new_page", "take_snapshot", "click", "wait_for",
                                        "list_pages"}
    session = FakeSession()
    assert asyncio.run(browser.BrowserSession(session).call("list_pages")) == "result"
    assert session.calls == ["list_pages"]


@pytest.mark.parametrize("name", sorted(browser.ALLOWED_MCP_TOOLS))
def test_wrapper_forwards_every_allowed_tool(name):
    session = FakeSession()
    assert asyncio.run(browser.BrowserSession(session).call(name, {})) == "result"
    assert session.calls == [name]


def test_server_flags_and_headless():
    args = browser.server_params(_settings(headless=False)).args
    assert "chrome-devtools-mcp@latest" in args
    for flag in ("--isolated", "--no-usage-statistics", "--no-category-network", "--no-category-performance",
                 "--no-category-emulation", "--no-javascript-evaluation"):
        assert flag in args
    assert "--no-category-debugging" not in args  # it would remove take_snapshot
    assert "--headless" not in args
    assert "--headless" in browser.server_params(_settings(headless=True)).args


def test_handle_runs_real_open_browser_path(monkeypatch, extraction):
    fake = FakeBrowser()
    monkeypatch.setattr(fetch_job, "open_browser", _opener(fake))
    # fetch's default opener was bound at def time; handle must still use a patchable opener
    result = fetch_job.handle(_settings(), JOB_URL)
    assert result["ok"] is True and fake.names[0] == "new_page"
