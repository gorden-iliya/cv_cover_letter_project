"""Chat agent: Bedrock Converse tool-use loop over the model-facing tools (AGENT_SPEC.md → Tools)."""

import json
from types import ModuleType
from typing import Callable

from agent import client
from agent.config import Settings
from prompts.chat_system import CHAT_SYSTEM

GREETING = "Paste a job URL or the job posting text to start (type 'exit' to quit)."

# Cap on model→tool→model hops for one user message, so a confused model cannot loop forever.
MAX_TOOL_TURNS = 8


class ChatAgent:
    def __init__(self, settings: Settings, tools: list[ModuleType],
                 converse: Callable = client.converse):
        self.settings = settings
        self.tools = {t.TOOL_SPEC["name"]: t for t in tools}
        self.converse = converse
        self.messages: list[dict] = []

    def tool_config(self) -> dict | None:
        if not self.tools:
            return None
        return {"tools": [{"toolSpec": t.TOOL_SPEC} for t in self.tools.values()]}

    def send(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": [{"text": user_text}]})
        for _ in range(MAX_TOOL_TURNS):
            response = self.converse(self.settings, self.messages, system=CHAT_SYSTEM,
                                     tool_config=self.tool_config())
            message = response["output"]["message"]
            self.messages.append(message)
            if response.get("stopReason") != "tool_use":
                return client.response_text(response)
            # Every toolUse block in the assistant turn must get a matching toolResult in the next user turn.
            results = [self._run_tool(block["toolUse"]) for block in message["content"] if "toolUse" in block]
            self.messages.append({"role": "user", "content": results})
        return "Stopped: too many tool steps for one message. Please try again."

    def _run_tool(self, tool_use: dict) -> dict:
        tool = self.tools.get(tool_use["name"])
        try:
            if tool is None:
                raise ValueError(f"Unknown tool: {tool_use['name']}")
            result, status = tool.handle(self.settings, **tool_use.get("input", {})), "success"
        except Exception as exc:  # report tool failures to the model instead of crashing the chat
            result, status = {"ok": False, "message": str(exc)}, "error"
        return {"toolResult": {"toolUseId": tool_use["toolUseId"],
                               "content": [{"json": json.loads(json.dumps(result, default=str))}],
                               "status": status}}
