# CV & Cover Letter Tailoring Agent

A terminal chat agent that tailors your CV and writes a cover letter for one public job posting.
You paste a job URL, the agent reads the page in a real Chrome browser (through the Chrome DevTools
MCP server), generates both documents with AWS Bedrock, validates them against the job and your
original CV, then prints and saves them locally. **Nothing is ever sent or submitted.**

Design details live in [`prd.md`](prd.md) (system design, config) and [`AGENT_SPEC.md`](AGENT_SPEC.md)
(agent behavior, tools, output format).

## Prerequisites
- Python 3.10+
- Node.js (the agent starts `npx chrome-devtools-mcp@latest` itself) and Google Chrome
- AWS credentials with access to a Bedrock model

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then fill it in
```

### 1. Configure `.env`
Fill in AWS credentials (or use an AWS profile / SSO) and the required settings:
`BEDROCK_MODEL_ID`, `AWS_REGION`, `ALLOWED_JOB_SITES`, `MAX_TOKENS_PER_CALL`.
Every variable, its purpose and its default is listed in [`prd.md` §7](prd.md#7-configuration-env).

The agent only opens job pages whose host is in `ALLOWED_JOB_SITES` (or a subdomain of one).
For other sites, paste the job text into the chat instead.

### 2. Add your CV
The agent reads your original CV from `CV_PATH` (default `cv-md/cv.md`). It never changes this file.

- **From a PDF:** put the PDF in `cv-pdf/` and run the `/cv-pdf-to-markdown-converter` skill in
  Claude Code. It writes `cv-md/cv.md` in the expected format.
- **By hand:** write a Markdown CV following
  [`.claude/skills/cv-pdf-to-markdown-converter/templates/cv_example.md`](.claude/skills/cv-pdf-to-markdown-converter/templates/cv_example.md).

### 3. (Optional) Add a profile
`cv/profile.md` (`PROFILE_PATH`) steers tone and content. It uses these headings, all optional:
Tone, Language, Length limits, Must mention, Never mention, Target roles, Companies to avoid.
Without the file, no constraints apply.

```markdown
## Tone
Confident, concise.
## Length limits
Cover letter under 250 words.
## Never mention
Salary expectations.
```

## Usage
```bash
python main.py
```

```
Paste a job URL or the job posting text to start (type 'exit' to quit).

you> Tailor my CV for https://jobs.lever.co/acme/123
...
Round 1: FAIL (2 issues) → Round 2: PASS, fit 8/10
<tailored CV, cover letter, fit summary, gaps>
Saved to: output/acme_senior-developer/v1
Total run time: 102.4s

you> make the cover letter shorter
...
Saved to: output/acme_senior-developer/v2
Total run time: 38.0s

you> exit
```

- **Job input:** a job URL, or the posting text pasted directly. If the page can't be read
  (site not allowed, login wall, CAPTCHA, empty page), the agent says why and asks you to paste the text.
- **Refining:** ask in plain words ("make the letter shorter", "emphasize my AWS work"). The agent
  decides whether to redo the CV, the letter or both, and always re-validates.
- **New job:** paste another URL in the same chat to start a new job.
- **Not passed:** if validation still fails after `MAX_VALIDATION_ROUNDS`, you get the best attempt with
  the remaining issues listed above the documents.
- **Prompt injection:** job text is treated as data. If a posting contains instructions aimed at the
  model, they are ignored and a warning shows the suspicious text.
- Set `CHROME_HEADLESS=true` to hide the browser window.

## Output
Each run (and each refinement) creates a new version folder; nothing is overwritten:
```
output/<company>_<role>/vN/
  job.md                     # the extracted job posting
  cv.md                      # tailored CV
  cover_letter.md
  validation_round_1.json    # one file per validation round
```

## Tests
```bash
python -m pytest
```
Bedrock and Chrome are faked in every test, so no AWS calls are made and no browser is launched.

## Privacy
`.env`, `cv/`, `cv-pdf/`, `cv-md/` and `output/` hold personal data and are git-ignored. Keep it that way.
