"""Model-facing tools. TOOLS is the list the chat agent exposes (AGENT_SPEC.md → Tools)."""

from tools import tailor_application

# fetch_job is added in slice 5.
TOOLS: list = [tailor_application]
