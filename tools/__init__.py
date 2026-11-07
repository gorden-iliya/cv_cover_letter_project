"""Model-facing tools. TOOLS is the list the chat agent exposes (AGENT_SPEC.md → Tools)."""

from tools import fetch_job, tailor_application

TOOLS: list = [fetch_job, tailor_application]
