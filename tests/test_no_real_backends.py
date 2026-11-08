"""The conftest guard really blocks Bedrock and Chrome, so a passing suite proves no real calls happened."""

import asyncio

import pytest

from agent import browser, client
from agent.config import Settings


def _settings():
    return Settings("model-x", "eu-west-1", ("jobs.lever.co",), 100, 2, False,
                    "cv-md/cv.md", "cv/profile.md", "output")


def test_real_bedrock_call_is_blocked():
    with pytest.raises(AssertionError, match="real boto3"):
        client.converse(_settings(), [{"role": "user", "content": [{"text": "x"}]}])


def test_real_mcp_server_launch_is_blocked():
    async def run():
        async with browser.open_browser(_settings()):
            pass

    with pytest.raises(AssertionError, match="chrome-devtools-mcp"):
        asyncio.run(run())
