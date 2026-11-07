"""Chrome DevTools MCP client (prd.md §6). The only module that talks to the browser.

The agent starts `npx chrome-devtools-mcp@latest` itself over stdio (Python `mcp` SDK) and may
call only the tools in ALLOWED_MCP_TOOLS; anything else is rejected here, before the server sees it.
"""

import os
import shutil
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.config import Settings

ALLOWED_MCP_TOOLS = frozenset({"navigate_page", "new_page", "take_snapshot", "click", "wait_for", "list_pages"})

SERVER_FLAGS = (
    "--isolated",
    "--no-usage-statistics",
    "--no-category-network",
    "--no-category-performance",
    "--no-category-emulation",
    "--no-javascript-evaluation",
)


class DisallowedToolError(PermissionError):
    """An MCP tool outside ALLOWED_MCP_TOOLS was requested."""


class BrowserToolError(RuntimeError):
    """The MCP server returned an error result for a tool call."""


def server_params(settings: Settings) -> StdioServerParameters:
    args = ["-y", "chrome-devtools-mcp@latest", *SERVER_FLAGS]
    if settings.chrome_headless:
        args.append("--headless")
    # On Windows npx is npx.cmd; which() resolves it so the subprocess can start without a shell.
    return StdioServerParameters(command=shutil.which("npx") or "npx", args=args)


class BrowserSession:
    """Wraps an MCP ClientSession and enforces the tool allowlist."""

    def __init__(self, session):
        self._session = session

    async def call(self, name: str, arguments: dict | None = None) -> str:
        if name not in ALLOWED_MCP_TOOLS:
            raise DisallowedToolError(f"MCP tool not allowed: {name}")
        result = await self._session.call_tool(name, arguments or {})
        text = "".join(getattr(block, "text", "") for block in result.content)
        # mcp 2.x: tool failures come back as is_error results, not exceptions.
        if result.is_error:
            raise BrowserToolError(f"{name} failed: {text}")
        return text


@asynccontextmanager
async def open_browser(settings: Settings):
    """Start chrome-devtools-mcp, yield a BrowserSession, stop the server (and Chrome) on exit."""
    with open(os.devnull, "w") as errlog:  # keep the server's banner/log out of the chat
        async with stdio_client(server_params(settings), errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield BrowserSession(session)
