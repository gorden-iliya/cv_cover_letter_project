# agent/ — the agent core

- `config.py`: settings from `.env` (`load_dotenv(find_dotenv())`). Names/defaults: prd.md §7.
- `client.py`: the only module that imports boto3. `converse()` is the single Bedrock Converse call
  used by every model call (chat, extractor, generators, validator). Provider swap point.
- The chat agent is a tool-use loop (Bedrock Converse `toolUse` → run tool → `toolResult`),
  with a turn cap. It exposes exactly the two tools in AGENT_SPEC.md; MCP tools are never passed to the model.
- The tailoring pipeline order and round cap are fixed in code, not chosen by the model.
