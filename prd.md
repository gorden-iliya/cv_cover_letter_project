# PRD: CV & Cover Letter Tailoring Agent (v1)

Source: the whiteboard design from lesson 3 (`../job seeker skill/prd.md`) and the Chrome DevTools MCP tutorial, refined in a design review. Every `[Assumption]` and open question from the original PRD is resolved below.

**Document map. Each fact lives in one place:**
| File | Owns |
|---|---|
| `prd.md` (this file) | Problem, goal, product shape, architecture, MCP server setup, configuration, principles, testing strategy, metrics, roadmap |
| `AGENT_SPEC.md` | Agent purpose and rules, tool inputs, outputs and behavior, inputs and `profile.md`, validator JSON, output files, terminal output, steps |
| `prd.json` | Feature list with verification steps and `passes` flags (replaces a functional-requirements list) |
| `progress.txt` | Build log |

## 1. Problem
Job seekers have to adapt their CV and write a cover letter by hand for every job posting. It's slow, the results are inconsistent, and they often miss what the job actually asks for.

## 2. Goal
The user gives a link to a public job posting. The agent reads the posting in a real Chrome browser and tailors the user's original CV and a cover letter to that job. It validates both documents, then prints them in the terminal and saves them locally. The user can refine the result through chat. Nothing is ever sent or submitted.

## 3. Users
- One job seeker (the course student) who runs the agent locally and has their own CV and AWS Bedrock access.

## 4. Product shape
- A **standalone Python agent** that calls AWS Bedrock (boto3 Converse), built with the SDD template (`AGENT_SPEC.md`, `agent/`, `tools/`, `prompts/`, nested `CLAUDE.md` files).
- **Interface:** an interactive chat in the terminal.
- **Scope:** one job per run. Public job pages only.
- **Repo:** private, with personal data kept out of git.

## 5. Architecture

```
 User (terminal chat)
   │  "Tailor my CV for https://jobs.lever.co/acme/123"
   ▼
 ┌──────────── Chat agent (Bedrock, tool-calling loop) ────────────┐
 │ tools:                                                          │
 │   fetch_job(url) ──► Python ──► Chrome DevTools MCP ──► job     │
 │   tailor_application(job, feedback?, target)                    │
 │        │                                                        │
 │        ▼  fixed Python pipeline                                 │
 │   CV generator (Bedrock)     ← original CV + job                │
 │   Letter generator (Bedrock) ← tailored CV + job + profile      │
 │   Validator (Bedrock)        ← CV + letter + job + original CV  │
 │        + profile                                                │
 │     PASS → return     FAIL → fixes to failing generator(s),     │
 │                              max MAX_VALIDATION_ROUNDS          │
 └─────────────────────────────────────────────────────────────────┘
   │
   ▼  print results; save to OUTPUT_DIR
```

**Design choices:**
- **The order of steps is fixed in code, not chosen by the model.** It's predictable, cheap, testable, and the round cap is guaranteed.
- **The validator is a separate Bedrock call** that sees the original CV, so it doesn't just approve its own work.
- **The model never drives the browser in v1.** `fetch_job` runs a fixed browser sequence written in Python.
- **One model for every call.** Fact consistency is checked by the validator only, with no rule-based check in code in v1.

Tool behavior, the validator schema and the output layout are defined in `AGENT_SPEC.md`.

## 6. Chrome DevTools MCP integration
- The Python agent is an **MCP client** of `npx chrome-devtools-mcp@latest`, connected over stdio with the `mcp` Python SDK. The agent starts the server itself.
- **Server flags:** `--isolated` (a fresh temporary profile), `--no-usage-statistics`, `--no-category-network`, `--no-category-performance`, `--no-category-emulation` and `--no-javascript-evaluation`.
  - Not `--no-category-debugging`: in chrome-devtools-mcp 1.12.0 that group contains `take_snapshot`, which `fetch_job` needs. The other debugging tools (console messages, CSS styles, screenshots, Lighthouse, screencast) stay on the server, but the Python allowlist rejects them.
- **Window:** visible by default. `--headless` is added only when `CHROME_HEADLESS=true`.
- **Two layers of browser safety:**
  1. Risky tool groups are switched off when the server starts.
  2. A tool allowlist and URL checks are enforced in Python. Both are defined in `AGENT_SPEC.md` under `fetch_job`.
- The MCP server installed in Claude Code (user scope) is only a development aid. The app doesn't depend on it.

## 7. Configuration (`.env`)
| Variable | Purpose | Default |
|---|---|---|
| `BEDROCK_MODEL_ID` | Model used for every call | (required) |
| `AWS_REGION` | Bedrock region | (required) |
| `MAX_VALIDATION_ROUNDS` | Cap on the critic loop | `2` |
| `MAX_TOKENS_PER_CALL` | Max output tokens per Bedrock call | (set) |
| `CHROME_HEADLESS` | Run Chrome without a window | `false` |
| `ALLOWED_JOB_SITES` | Comma-separated allowed hosts, e.g. `jobs.lever.co,boards.greenhouse.io,comeet.com` | (required) |
| `CV_PATH` | Original CV | `cv/original_cv.md` |
| `PROFILE_PATH` | User profile | `cv/profile.md` |
| `OUTPUT_DIR` | Output root | `output` |

Configuration is loaded with `load_dotenv(find_dotenv())`. Nothing is hard-coded.

## 8. Non-functional principles
The rules that enforce these are in `AGENT_SPEC.md`. The checks that verify them are in `prd.json`.
- **Truthfulness:** the output never contains invented facts.
- **Safety:** nothing is ever sent. Job text is untrusted, the browser is locked down, and only allowed sites can be opened.
- **Privacy:** the CV, profile and outputs stay local. `.gitignore` covers `cv/`, `output/` and `.env`, and `cv/original_cv.example.md` is committed instead.
- **Cost:** one job per run, the round cap and `MAX_TOKENS_PER_CALL`.
- **Speed:** a soft target of under about 2 minutes per job. Total time is printed but not enforced by tests.
- **Observability:** validation results are saved for every round, with a one-line summary per round in the terminal.

## 9. Testing strategy
- **pytest unit tests** with Bedrock and MCP faked. No test calls real Bedrock or launches Chrome.
- **One manual end-to-end run** on a real public job page before release.

## 10. Success metrics
- At least 80% of runs pass validation within 2 rounds, measured from the saved validation JSON.
- Zero invented facts in user spot checks.
- At least 60% of results accepted without manual edits.

## 11. Out of scope (v1) / roadmap
| v1 out of scope | Planned for |
|---|---|
| LinkedIn and sites that need a login | v2 (with a persistent profile and manual login) |
| Job search: the model drives the browser to find jobs | v2 (direct MCP tools for the model) |
| Batch runs and ranking of many jobs | v2 |
| Site-specific readers (Lever, Greenhouse, Comeet...) | When the generic method is weak |
| Rule-based fact check in code | Later |
| Separate validator model | Later (via env variable) |
| PDF/DOCX export | Later |
| Browser-level URL allowlist (`--allowedUrlPattern`, Chrome 149+) | Later |
| Auto-applying, email sending, interview prep, salary negotiation | Not planned |
