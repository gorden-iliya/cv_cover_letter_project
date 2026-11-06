# CLAUDE.md — conventions for this project

- Sources of truth (build what they specify; if something is unclear, ask rather than invent):
  - `prd.md`: system design (product scope, architecture, Chrome DevTools MCP setup and flags,
    `.env` config, principles, testing strategy, roadmap).
  - `AGENT_SPEC.md`: the agent's purpose, rules, tools, inputs, validator JSON, output files,
    terminal output, behavior and steps.
  - Each fact lives in one file only. When changing a fact, change it where it lives.
  - `prd.json`: the feature list. Each feature has verification steps and a `passes` flag.
  - If they conflict, stop and ask.

- `prd.json` rules:
  - Work on one feature at a time.
  - Set `passes` to `true` only after running every step of that feature and seeing it work.
  - Never remove or edit features, descriptions or steps to make them pass. Only `passes` changes.

- `progress.txt`: read it at the start of every session. After completing each task, append:
  - Task completed and PRD item reference (prd.json description)
  - Key decisions made and reasoning
  - Files changed
  - Any blockers or notes for next iteration
  Keep entries concise. Sacrifice grammar for the sake of concision. This file helps future iterations skip exploration.

- Call the model with boto3 Bedrock Converse.
- Keep the Bedrock call in one function so a provider swap is easy.
- Config from env: `.env` via `load_dotenv(find_dotenv())`;
  BEDROCK_MODEL_ID, AWS_REGION and every other setting from env vars, never hard-coded.
- The browser is reached only through the Chrome DevTools MCP server (Python `mcp` SDK, stdio).
  Enforce the MCP tool allowlist and the ALLOWED_JOB_SITES check in code, not only in prompts.
- Never commit personal data: `cv/`, `output/` and `.env` are git-ignored.
- Comment only the non-obvious AI/SDK bits — skip the obvious.
