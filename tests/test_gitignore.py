"""Personal data (cv/, output/, .env) must stay out of git; the example files must not."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _ignored(path: str) -> bool:
    # --no-index: judge by .gitignore rules even if the path is tracked or does not exist
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=ROOT, capture_output=True,
    )
    return result.returncode == 0


@pytest.mark.parametrize("path", [
    ".env",
    "cv-md/cv.md",
    "cv/profile.md",
    "output/acme_devops-engineer/v1/cv.md",
])
def test_personal_data_is_ignored(path):
    assert _ignored(path)


@pytest.mark.parametrize("path", ["cv/original_cv.example.md", ".env.example"])
def test_example_files_are_not_ignored(path):
    assert not _ignored(path)
    assert (ROOT / path).is_file()
