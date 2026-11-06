# tools/ — model-facing tools, one per file

- Exactly two tools in v1: `fetch_job` and `tailor_application` (spec: AGENT_SPEC.md → Tools).
- Each file exposes `TOOL_SPEC` (Bedrock `toolSpec`: name, description, `inputSchema.json` with
  `additionalProperties: false`, `required`, a `description` on every field) and `handle(...)`.
- Backends are real (Chrome DevTools MCP, Bedrock) — tests fake them; no test calls real Bedrock or Chrome.
- Enforce the MCP tool allowlist and ALLOWED_JOB_SITES in code here, not in prompts.
