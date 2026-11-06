import pytest

from agent import config
from agent.config import ConfigError, load_settings

ALL_KEYS = (
    "BEDROCK_MODEL_ID", "AWS_REGION", "ALLOWED_JOB_SITES", "MAX_TOKENS_PER_CALL",
    "MAX_VALIDATION_ROUNDS", "CHROME_HEADLESS", "CV_PATH", "PROFILE_PATH", "OUTPUT_DIR",
)


@pytest.fixture
def env(monkeypatch):
    """Isolate from the developer's real .env and set only the required keys."""
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    for key in ALL_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("ALLOWED_JOB_SITES", "jobs.lever.co, Boards.Greenhouse.io")
    monkeypatch.setenv("MAX_TOKENS_PER_CALL", "1000")
    return monkeypatch


def test_loads_required_values(env):
    s = load_settings()
    assert s.bedrock_model_id == "test-model"
    assert s.aws_region == "eu-west-1"
    assert s.allowed_job_sites == ("jobs.lever.co", "boards.greenhouse.io")
    assert s.max_tokens_per_call == 1000


def test_optional_defaults(env):
    s = load_settings()
    assert s.max_validation_rounds == 2
    assert s.chrome_headless is False
    assert s.cv_path == "cv/original_cv.md"
    assert s.profile_path == "cv/profile.md"
    assert s.output_dir == "output"


def test_optional_overrides(env):
    env.setenv("MAX_VALIDATION_ROUNDS", "3")
    env.setenv("CHROME_HEADLESS", "true")
    env.setenv("CV_PATH", "x/cv.md")
    env.setenv("PROFILE_PATH", "x/p.md")
    env.setenv("OUTPUT_DIR", "out2")
    s = load_settings()
    assert (s.max_validation_rounds, s.chrome_headless, s.cv_path, s.profile_path, s.output_dir) == (
        3, True, "x/cv.md", "x/p.md", "out2")


@pytest.mark.parametrize("key", ["BEDROCK_MODEL_ID", "AWS_REGION", "ALLOWED_JOB_SITES", "MAX_TOKENS_PER_CALL"])
def test_missing_required_is_named(env, key):
    env.delenv(key)
    with pytest.raises(ConfigError, match=f"Missing setting.*{key}"):
        load_settings()


def test_empty_value_counts_as_missing(env):
    env.setenv("BEDROCK_MODEL_ID", "  ")
    with pytest.raises(ConfigError, match="BEDROCK_MODEL_ID"):
        load_settings()


@pytest.mark.parametrize("key,value", [("MAX_TOKENS_PER_CALL", "abc"), ("MAX_VALIDATION_ROUNDS", "0"),
                                       ("CHROME_HEADLESS", "maybe")])
def test_invalid_values(env, key, value):
    env.setenv(key, value)
    with pytest.raises(ConfigError, match=key):
        load_settings()


def test_uses_load_dotenv_find_dotenv(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "find_dotenv", lambda: "/some/.env")
    monkeypatch.setattr(config, "load_dotenv", lambda path: calls.append(path))
    for key in ALL_KEYS:
        monkeypatch.setenv(key, "1" if key in ("MAX_TOKENS_PER_CALL", "MAX_VALIDATION_ROUNDS") else "x")
    monkeypatch.setenv("CHROME_HEADLESS", "false")
    load_settings()
    assert calls == ["/some/.env"]


def test_main_exits_with_missing_setting_message(env, capsys):
    import main
    env.delenv("BEDROCK_MODEL_ID")
    assert main.main() == 1
    assert "Missing setting(s): BEDROCK_MODEL_ID" in capsys.readouterr().err
