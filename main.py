"""Entry point: `python main.py` starts the terminal chat."""

import sys

from agent.chat import GREETING, ChatAgent
from agent.config import ConfigError, load_settings
from tools import TOOLS


def chat_loop(agent: ChatAgent, read=input, write=print) -> None:
    write(GREETING)
    while True:
        try:
            text = read("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            write("")
            return
        if not text:
            continue
        if text.lower() in ("exit", "quit"):
            return
        write("\nagent> " + agent.send(text))


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1
    chat_loop(ChatAgent(settings, TOOLS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
