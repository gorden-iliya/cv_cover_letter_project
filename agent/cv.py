"""Access to the user's original CV (CV_PATH). Read-only: this module never writes it."""

from pathlib import Path

from agent.config import Settings


class MissingCVError(Exception):
    """The original CV file is missing. Fatal: the chat stops (AGENT_SPEC.md → Behavior → rules)."""

    def __init__(self, path: str):
        self.path = path
        super().__init__(
            f"Original CV not found at '{path}'. Create it or set CV_PATH in .env, then restart."
        )


def require_original_cv(settings: Settings) -> Path:
    path = Path(settings.cv_path)
    if not path.is_file():
        raise MissingCVError(settings.cv_path)
    return path


def read_original_cv(settings: Settings) -> str:
    return require_original_cv(settings).read_text(encoding="utf-8")
