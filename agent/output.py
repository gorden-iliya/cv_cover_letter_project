"""Version folders under OUTPUT_DIR (AGENT_SPEC.md → Data → outputs). Nothing is overwritten."""

import re
from pathlib import Path

JOB_FIELDS = ("title", "company", "location", "source_host", "final_url", "description")


def slugify(text: str | None, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or fallback


def job_dir_name(job: dict) -> str:
    return f"{slugify(job.get('company'), 'unknown-company')}_{slugify(job.get('title'), 'unknown-role')}"


def new_version_dir(output_dir: str, job: dict) -> Path:
    """Create and return OUTPUT_DIR/<company>_<role>/vN with N = highest existing + 1."""
    base = Path(output_dir) / job_dir_name(job)
    base.mkdir(parents=True, exist_ok=True)
    numbers = [int(p.name[1:]) for p in base.iterdir() if p.is_dir() and re.fullmatch(r"v\d+", p.name)]
    version = base / f"v{max(numbers, default=0) + 1}"
    version.mkdir()  # exist_ok=False: never reuse a folder
    return version


def job_markdown(job: dict) -> str:
    lines = [f"# {job.get('title') or 'Unknown role'}", ""]
    for key in JOB_FIELDS[1:-1]:
        lines.append(f"- {key}: {job.get(key) or 'unknown'}")
    lines += ["", "## description", "", job.get("description", "")]
    return "\n".join(lines) + "\n"


def write_text(folder: Path, name: str, text: str) -> None:
    (folder / name).write_text(text, encoding="utf-8")
