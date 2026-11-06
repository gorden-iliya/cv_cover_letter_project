"""The user's profile (PROFILE_PATH). Read-only.

Missing headings mean "no constraint" (AGENT_SPEC.md → Data), so a missing file is an empty profile.
"""

from pathlib import Path

from agent.config import Settings


def read_profile(settings: Settings) -> str:
    path = Path(settings.profile_path)
    return path.read_text(encoding="utf-8") if path.is_file() else ""
