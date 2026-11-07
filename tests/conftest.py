"""Suite-wide guard: no test may reach real Bedrock or start the Chrome DevTools MCP server."""

import pytest

from agent import browser, client


class RealBackendUsed(AssertionError):
    pass


def _no_boto3_client(*args, **kwargs):
    raise RealBackendUsed("test tried to create a real boto3 Bedrock client; fake client.converse instead")


def _no_stdio_client(*args, **kwargs):
    raise RealBackendUsed("test tried to launch chrome-devtools-mcp; fake open_browser instead")


@pytest.fixture(autouse=True)
def block_real_backends(monkeypatch):
    # get_client() caches in client._client; start each test with no cached real client
    monkeypatch.setattr(client, "_client", None)
    monkeypatch.setattr(client.boto3, "client", _no_boto3_client)
    monkeypatch.setattr(browser, "stdio_client", _no_stdio_client)
