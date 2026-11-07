"""fetch_job tool (AGENT_SPEC.md → Tools → 1).

Fixed browser sequence in code (the model never picks MCP tools):
URL check → new_page → wait_for → take_snapshot → [click "Show more"/"Read more" → take_snapshot]
→ list_pages (final URL re-check) → one Bedrock extraction call.
"""

import asyncio
import json
import re

from agent import client
from agent.browser import open_browser
from agent.config import Settings
from agent.urls import NOT_ALLOWED_MESSAGE, host_of, is_allowed_url
from prompts.job_extractor import JOB_EXTRACTOR_SYSTEM, build_extractor_prompt

TOOL_SPEC = {
    "name": "fetch_job",
    "description": (
        "Fetch and extract a job posting from a public job page URL. Returns ok=true with the job, "
        "or ok=false with a reason; then ask the user to paste the job text."
    ),
    "inputSchema": {"json": {
        "type": "object",
        "additionalProperties": False,
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "description": "The job posting URL exactly as the user gave it"},
        },
    }},
}

WAIT_TEXTS = ["Apply", "Job", "Description", "Requirements", "Responsibilities"]
WAIT_TIMEOUT_MS = 10_000
NAVIGATION_TIMEOUT_MS = 30_000
MAX_PAGE_CHARS = 60_000      # keeps the extraction prompt bounded on huge pages
MIN_DESCRIPTION_CHARS = 100  # below this the posting counts as "near-empty"

_SHOW_MORE = re.compile(r'uid=(\S+) button "(?:show|read) more\b', re.IGNORECASE)
_SELECTED = re.compile(r"^(\d+): (.*?)\s*\[selected\]\s*$", re.MULTILINE)
_UID = re.compile(r"\buid=\S+ ?")
_URL_ATTR = re.compile(r' url="[^"]*"')

MESSAGES = {
    "fetch_failed": "Could not load the job page.",
    "captcha": "The page shows a CAPTCHA / bot check.",
    "login_required": "The page asks you to log in.",
    "empty_page": "The page has no readable job posting.",
}


class FetchError(Exception):
    def __init__(self, reason: str, message: str | None = None):
        super().__init__(message or MESSAGES.get(reason, reason))
        self.reason = reason


def _fail(reason: str, message: str | None = None) -> dict:
    return {"ok": False, "reason": reason, "message": message or MESSAGES.get(reason, reason)}


def selected_page(pages_text: str) -> tuple[int, str]:
    """Parse the [selected] line of new_page/list_pages output → (page id, page URL)."""
    match = _SELECTED.search(pages_text)
    if not match:
        raise FetchError("fetch_failed", "Could not read the open page from the browser.")
    rest = match.group(2)
    # Lines look like "2: Title (https://final/url)"; about:blank has no title.
    url = re.search(r"\(([^()\s]+)\)$", rest)
    return int(match.group(1)), (url.group(1) if url else rest)


def show_more_uid(snapshot: str) -> str | None:
    match = _SHOW_MORE.search(snapshot)
    return match.group(1) if match else None


def page_text(snapshot: str) -> str:
    """Snapshot → plain text for the model: drop uids and link targets (noise, tokens, and URLs)."""
    text = _URL_ATTR.sub("", _UID.sub("", snapshot))
    return text[:MAX_PAGE_CHARS]


async def browse(browser, url: str) -> tuple[str, str]:
    """Run the fixed MCP sequence. Returns (snapshot text, final URL)."""
    page_id, _ = selected_page(await browser.call("new_page", {"url": url, "timeout": NAVIGATION_TIMEOUT_MS}))
    try:
        await browser.call("wait_for", {"pageId": page_id, "text": WAIT_TEXTS, "timeout": WAIT_TIMEOUT_MS})
    except Exception:
        pass  # a timeout is not a failure: the empty-page check catches blank pages
    snapshot = await browser.call("take_snapshot", {"pageId": page_id})
    uid = show_more_uid(snapshot)
    if uid:
        await browser.call("click", {"pageId": page_id, "uid": uid})
        snapshot = await browser.call("take_snapshot", {"pageId": page_id})
    _, final_url = selected_page(await browser.call("list_pages", {}))
    return snapshot, final_url


def extract_job(settings: Settings, snapshot: str) -> dict:
    """One Bedrock call: page text → {"page", "title", "company", "location", "description"}."""
    response = client.converse(
        settings, [{"role": "user", "content": [{"text": build_extractor_prompt(page_text(snapshot))}]}],
        system=JOB_EXTRACTOR_SYSTEM)
    text = client.response_text(response)
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start:end + 1]) if start != -1 and end > start else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        raise FetchError("fetch_failed", "Could not extract the job from the page.")
    return {k: str(data.get(k) or "").strip() for k in ("page", "title", "company", "location", "description")}


async def fetch(settings: Settings, url: str, opener=None) -> dict:
    if not is_allowed_url(url, settings.allowed_job_sites):
        return _fail("not_allowed", NOT_ALLOWED_MESSAGE)  # before the browser is started
    try:
        async with (opener or open_browser)(settings) as browser:
            snapshot, final_url = await browse(browser, url.strip())
    except FetchError as exc:
        return _fail(exc.reason, str(exc))
    except Exception as exc:
        return _fail("fetch_failed", f"{MESSAGES['fetch_failed']} ({exc})")
    if not is_allowed_url(final_url, settings.allowed_job_sites):
        return _fail("not_allowed", NOT_ALLOWED_MESSAGE)  # redirected off the allowlist: drop the page

    try:
        fields = extract_job(settings, snapshot)
    except FetchError as exc:
        return _fail(exc.reason, str(exc))
    if fields["page"] in ("captcha", "login_required"):
        return _fail(fields["page"])
    if fields["page"] == "empty_page" or len(fields["description"]) < MIN_DESCRIPTION_CHARS:
        return _fail("empty_page")
    return {"ok": True, "job": {
        "title": fields["title"], "company": fields["company"], "location": fields["location"],
        "source_host": host_of(final_url), "final_url": final_url, "description": fields["description"],
    }}


def handle(settings: Settings, url: str) -> dict:
    return asyncio.run(fetch(settings, url))
