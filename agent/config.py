"""Settings loaded from .env / environment. Names and defaults are defined in prd.md §7."""

import os
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

REQUIRED = ("BEDROCK_MODEL_ID", "AWS_REGION", "ALLOWED_JOB_SITES", "MAX_TOKENS_PER_CALL")

DEFAULTS = {
    "MAX_VALIDATION_ROUNDS": "2",
    "CHROME_HEADLESS": "false",
    "CV_PATH": "cv-md/cv.md",
    "PROFILE_PATH": "cv/profile.md",
    "OUTPUT_DIR": "output",
}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    bedrock_model_id: str
    aws_region: str
    allowed_job_sites: tuple[str, ...]
    max_tokens_per_call: int
    max_validation_rounds: int
    chrome_headless: bool
    cv_path: str
    profile_path: str
    output_dir: str


def _get(name: str) -> str:
    # An empty value counts as missing, so "KEY=" in .env is reported too.
    value = os.environ.get(name, "").strip()
    return value or DEFAULTS.get(name, "")


def _positive_int(name: str) -> int:
    raw = _get(name)
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"Invalid setting {name}={raw!r}: expected a positive integer.") from None
    if value < 1:
        raise ConfigError(f"Invalid setting {name}={raw!r}: expected a positive integer.")
    return value


def _bool(name: str) -> bool:
    raw = _get(name).lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise ConfigError(f"Invalid setting {name}={raw!r}: expected true or false.")


def load_settings() -> Settings:
    # override=False: real environment variables win over .env values.
    load_dotenv(find_dotenv())

    missing = [name for name in REQUIRED if not _get(name)]
    if missing:
        raise ConfigError(
            "Missing setting(s): " + ", ".join(missing)
            + ". Add them to .env (see .env.example)."
        )

    sites = tuple(s.strip().lower() for s in _get("ALLOWED_JOB_SITES").split(",") if s.strip())
    if not sites:
        raise ConfigError("Missing setting(s): ALLOWED_JOB_SITES. Add them to .env (see .env.example).")

    return Settings(
        bedrock_model_id=_get("BEDROCK_MODEL_ID"),
        aws_region=_get("AWS_REGION"),
        allowed_job_sites=sites,
        max_tokens_per_call=_positive_int("MAX_TOKENS_PER_CALL"),
        max_validation_rounds=_positive_int("MAX_VALIDATION_ROUNDS"),
        chrome_headless=_bool("CHROME_HEADLESS"),
        cv_path=_get("CV_PATH"),
        profile_path=_get("PROFILE_PATH"),
        output_dir=_get("OUTPUT_DIR"),
    )
