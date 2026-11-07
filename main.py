"""Entry point: `python main.py` starts the terminal chat."""

import sys

from agent.chat import GREETING, ChatAgent
from agent.config import ConfigError, load_settings
from agent.cv import MissingCVError
from agent.present import format_result
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


def result_printer(write=print):
    def on_tool_result(name: str, result: dict, elapsed: float) -> None:
        if name == "tailor_application":
            write("\n" + format_result(result, elapsed))
        elif name == "fetch_job" and result.get("reason") == "not_allowed":
            # The spec fixes this exact wording, so code prints it instead of trusting the model's paraphrase.
            write("\n" + result["message"])
    return on_tool_result


def main() -> int:
    # Windows pipes default to cp1252, which cannot print "→" or many CV characters.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1
    try:
        chat_loop(ChatAgent(settings, TOOLS, on_tool_result=result_printer()))
    except MissingCVError as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
