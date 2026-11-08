---
name: cv-pdf-to-markdown-converter
description: Use this skill when the user asks to convert a CV in PDF format (in the cv-pdf/ folder) into a Markdown (.md) CV that follows the project's CV template.
---

# CV PDF to Markdown Converter
Read the CV PDF in the project's `cv-pdf/` folder, restructure its content into Markdown that follows
`templates/cv_example.md` (in this skill's folder), validate it with `scripts/check_cv_format.py` until it is green,
then write the result to `cv-md/cv.md`.

## When to Use This Skill
The user asks to parse or convert a CV PDF into a Markdown file.

## Prerequisites & Tools
- No external converter is needed: read the PDF with the Read tool (it supports PDFs).
- Python 3 for `scripts/check_cv_format.py` (standard library only).
- The `cv-to-md` subagent (`.claude/agents/cv-to-md.md`).

## Process
1. **Find the input.** Look for a `.pdf` file in `cv-pdf/`. If there is none, stop and tell the user:
   "No PDF file to parse was found in the cv-pdf folder." If there are several, ask which one to use.
2. **Extract.** Read the PDF with the Read tool and collect its full text.
3. **Structure (delegate).** Do not restructure the text yourself. Hand the extracted text to the **`cv-to-md` subagent**.
   It returns the CV as Markdown in the template structure.
4. **Validate.** Save the result to `cv-md/cv.md`, then run:
   ```bash
   python .claude/skills/cv-pdf-to-markdown-converter/scripts/check_cv_format.py cv-md/cv.md
   ```
   If it prints problems, fix only those problems in `cv-md/cv.md` and run it again. Continue only when it prints `OK`.
5. **Report.** Tell the user the file is at `cv-md/cv.md`. To use it as the agent's CV, they can copy it to
   `cv/original_cv.md` or set `CV_PATH=cv-md/cv.md` in `.env`.

## Rules
- Use only facts from the PDF. Never invent or "improve" employers, titles, dates, numbers or skills.
- Never write into `cv-pdf/` and never change the PDF.
- `cv-pdf/` and `cv-md/` hold personal data and are git-ignored. Never commit them.

## Done means
`cv-md/cv.md` exists, `check_cv_format.py` prints `OK` for it, and its content comes only from the PDF.
