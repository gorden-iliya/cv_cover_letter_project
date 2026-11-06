"""Entry point: `python main.py` starts the terminal chat."""

import sys

from agent.config import ConfigError, load_settings


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    # Terminal chat is implemented in a later slice (prd.json: "Terminal chat starts and asks for a job").
    print(f"Settings loaded (model {settings.bedrock_model_id}, region {settings.aws_region}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
