from agent import client
from agent.config import Settings


def _settings():
    return Settings("model-x", "eu-west-1", ("jobs.lever.co",), 777, 2, False,
                    "cv-md/cv.md", "cv/profile.md", "output")


class FakeBedrock:
    def __init__(self):
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {"output": {"message": {"content": [{"text": "hi "}, {"text": "there"}]}}}


def test_converse_passes_model_and_max_tokens(monkeypatch):
    fake = FakeBedrock()
    monkeypatch.setattr(client, "_client", fake)
    resp = client.converse(_settings(), [{"role": "user", "content": [{"text": "x"}]}], system="sys")
    call = fake.calls[0]
    assert call["modelId"] == "model-x"
    assert call["inferenceConfig"] == {"maxTokens": 777}
    assert call["system"] == [{"text": "sys"}]
    assert "toolConfig" not in call
    assert client.response_text(resp) == "hi there"
