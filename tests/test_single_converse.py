"""F3: every model call (chat, extractor, CV gen, letter gen, validator) goes through client.converse."""

import json
import re
from pathlib import Path

from agent import client
from agent.chat import ChatAgent
from agent.config import Settings
from prompts.chat_system import CHAT_SYSTEM
from prompts.cv_generator import CV_GENERATOR_SYSTEM
from prompts.job_extractor import JOB_EXTRACTOR_SYSTEM
from prompts.letter_generator import LETTER_GENERATOR_SYSTEM
from prompts.validator import VALIDATOR_SYSTEM
from tools import TOOLS
from tools.fetch_job import extract_job

ROOT = Path(__file__).resolve().parent.parent
JOB = {"title": "DevOps Engineer", "company": "Acme", "location": "Remote",
       "description": "We need Kubernetes and Terraform skills. " * 5}
VALIDATION = {"verdict": "PASS", "fit_score": 8, "issues": [], "fit_summary": "Good fit.", "gaps": []}


def _settings(tmp_path):
    return Settings("model-x", "eu-west-1", ("jobs.lever.co",), 777, 1, False,
                    "cv/original_cv.example.md", str(tmp_path / "no_profile.md"), str(tmp_path / "out"))


def _msg(content, stop="end_turn"):
    return {"stopReason": stop, "output": {"message": {"role": "assistant", "content": content}}}


class FakeBedrock:
    """Stands in for the boto3 bedrock-runtime client, below client.converse."""

    def __init__(self):
        self.calls = []
        self.chat_turns = 0

    def converse(self, **kwargs):
        system = kwargs["system"][0]["text"]
        role = {CHAT_SYSTEM: "chat", JOB_EXTRACTOR_SYSTEM: "extractor", CV_GENERATOR_SYSTEM: "cv",
                LETTER_GENERATOR_SYSTEM: "letter", VALIDATOR_SYSTEM: "validator"}[system]
        self.calls.append((role, kwargs))
        if role == "chat":
            self.chat_turns += 1
            if self.chat_turns == 1:
                return _msg([{"toolUse": {"toolUseId": "t1", "name": "tailor_application",
                                          "input": {"job": JOB}}}], stop="tool_use")
            return _msg([{"text": "Done."}])
        if role == "extractor":
            return _msg([{"text": json.dumps({"page": "job", **JOB})}])
        if role == "validator":
            return _msg([{"text": json.dumps(VALIDATION)}])
        return _msg([{"text": f"{role} text"}])


def test_all_model_calls_use_one_converse_with_model_and_max_tokens(tmp_path, monkeypatch):
    fake = FakeBedrock()
    monkeypatch.setattr(client, "_client", fake)
    settings = _settings(tmp_path)

    assert ChatAgent(settings, TOOLS).send("Tailor my CV for this job: ...") == "Done."
    assert extract_job(settings, 'heading "DevOps Engineer"')["company"] == "Acme"

    roles = [role for role, _ in fake.calls]
    assert set(roles) == {"chat", "extractor", "cv", "letter", "validator"}
    for _, kwargs in fake.calls:
        assert kwargs["modelId"] == "model-x"
        assert kwargs["inferenceConfig"] == {"maxTokens": 777}


def test_only_client_module_calls_bedrock():
    boto_users, raw_converse = [], []
    for path in list((ROOT / "agent").glob("*.py")) + list((ROOT / "tools").glob("*.py")) + \
            list((ROOT / "prompts").glob("*.py")) + [ROOT / "main.py"]:
        src = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(import|from)\s+boto3", src, re.M):
            boto_users.append(path.name)
        # A converse call that is not client.converse / self.converse (the injected client.converse).
        if re.search(r"(?<!client)(?<!self)\.converse\(", src) and path.name != "client.py":
            raw_converse.append(path.name)
    assert boto_users == ["client.py"]
    assert raw_converse == []
    assert len(re.findall(r"^def converse\(", (ROOT / "agent" / "client.py").read_text(), re.M)) == 1
