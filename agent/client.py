"""The only module that talks to the model provider (boto3 Bedrock Converse).

Every model call in the app (chat agent, extractor, CV/letter generators, validator)
goes through `converse()`, so swapping providers means changing this file only.
"""

import boto3

from agent.config import Settings

_client = None


def get_client(settings: Settings):
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    return _client


def converse(settings: Settings, messages: list, system: str | None = None,
             tool_config: dict | None = None) -> dict:
    """Send one Converse request and return the raw response dict."""
    kwargs = {
        "modelId": settings.bedrock_model_id,
        "messages": messages,
        "inferenceConfig": {"maxTokens": settings.max_tokens_per_call},
    }
    if system:
        kwargs["system"] = [{"text": system}]
    if tool_config:
        kwargs["toolConfig"] = tool_config
    return get_client(settings).converse(**kwargs)


def response_text(response: dict) -> str:
    """Concatenate the text blocks of a Converse response."""
    content = response["output"]["message"]["content"]
    return "".join(block.get("text", "") for block in content)
