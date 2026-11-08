"""Check that a CV markdown file follows the structure of templates/cv_example.md.

Usage:
    python check_cv_format.py <cv.md> [--template <template.md>]

Exit code 0 = green (prints OK). Exit code 1 = problems found (one per line). Exit code 2 = bad usage.
The template is the source of truth for which "## " sections exist and in what order.
Standard library only.
"""
import argparse
import re
import sys
from pathlib import Path

DEFAULT_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "cv_example.md"

MONTH = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}"
DATE_RANGE = re.compile(rf"^{MONTH} [–-] ({MONTH}|Present)$")
EDUCATION_ITEM = re.compile(r"^- [^()]+ - [^()]+ \(\d{4}( - \d{4})?\)$")
TECH_LINE = re.compile(r"^\*\(.+\)\*$")


def sections(lines):
    """Map each '## ' heading (colon stripped) to the lines under it, keeping order."""
    result, current = {}, None
    for line in lines:
        if line.startswith("## "):
            current = line[3:].strip().rstrip(":").strip()
            result[current] = []
        elif current is not None:
            result[current].append(line)
    return result


def check(cv_text, template_text):
    problems = []
    lines = [l.rstrip() for l in cv_text.splitlines()]
    t_lines = [l.rstrip() for l in template_text.splitlines()]
    non_empty = [l for l in lines if l.strip()]

    # Header: "# Name" then a tagline line.
    if not non_empty or not non_empty[0].startswith("# ") or non_empty[0].startswith("## "):
        problems.append("First line must be '# <full name>'.")
    elif len(non_empty) < 2 or non_empty[1].startswith("#"):
        problems.append("Second line must be a tagline (job title, location).")
    if sum(1 for l in lines if l.startswith("# ")) != 1:
        problems.append("There must be exactly one '# ' heading (the name).")

    # Left-over template content.
    t_name = next((l for l in t_lines if l.startswith("# ")), None)
    if t_name and non_empty and non_empty[0] == t_name:
        problems.append(f"Name is still the template placeholder: '{t_name[2:]}'.")
    if re.search(r"example\.(com|org)|jane-doe-example|50-000-0000", cv_text):
        problems.append("Template placeholder contact details are still present.")

    # Sections: same '## ' headings as the template, same order.
    expected = list(sections(t_lines))
    found = list(sections(lines))
    for name in expected:
        if name not in found:
            problems.append(f"Missing section '## {name}'.")
    for name in found:
        if name not in expected:
            problems.append(f"Unexpected section '## {name}' (not in template).")
    common = [n for n in found if n in expected]
    if common != [n for n in expected if n in found]:
        problems.append(f"Sections are out of order. Expected order: {', '.join(expected)}.")

    secs = sections(lines)
    for name, body in secs.items():
        if not any(l.strip() for l in body):
            problems.append(f"Section '## {name}' is empty.")

    # Contact details: a bullet list.
    contact = secs.get("Contact details", [])
    if contact and not any(l.startswith("- ") for l in contact):
        problems.append("'## Contact details' must be a '- ' bullet list.")

    # Experience: '### A | B | ... | <date range>' entries, each with a bold line and bullets.
    exp = secs.get("Experience", [])
    jobs, job = [], None
    for line in exp:
        if line.startswith("### "):
            job = {"header": line[4:].strip(), "body": []}
            jobs.append(job)
        elif job is not None:
            job["body"].append(line)
    if "Experience" in secs and not jobs:
        problems.append("'## Experience' needs at least one '### ' job entry.")
    for j in jobs:
        parts = [p.strip() for p in j["header"].split("|")]
        label = j["header"][:60]
        if len(parts) < 3:
            problems.append(f"Job header '{label}' needs ' | '-separated parts ending with a date range.")
        elif not DATE_RANGE.match(parts[-1]):
            problems.append(f"Job header '{label}': date range must look like 'Mmm YYYY – Mmm YYYY' or 'Mmm YYYY – Present'.")
        body = [l for l in j["body"] if l.strip()]
        if not any(l.startswith("**") and l.endswith("**") for l in body):
            problems.append(f"Job '{label}' needs a bold '**...**' description line.")
        bullets = [l for l in body if l.startswith("- ")]
        if not bullets:
            problems.append(f"Job '{label}' needs at least one '- ' accomplishment.")
        if not any(TECH_LINE.match(l) or l.endswith(")*") for l in body):
            problems.append(f"Job '{label}' needs technologies as '*(Tech, Tech)*'.")
        seen = set()
        for b in bullets:
            if b in seen:
                problems.append(f"Job '{label}' has a duplicated bullet: '{b[:60]}'.")
            seen.add(b)

    # Education: '- School - Course (YYYY)' or '(YYYY - YYYY)'.
    for line in secs.get("Education", []):
        if line.strip() and not EDUCATION_ITEM.match(line.strip()):
            problems.append(f"Education line must be '- <school> - <course> (YYYY)' or '(YYYY - YYYY)': '{line.strip()[:60]}'.")

    # Skills: one comma-separated line.
    skills = [l for l in secs.get("Skills", []) if l.strip()]
    if skills and (len(skills) != 1 or "," not in skills[0]):
        problems.append("'## Skills' must be one comma-separated line.")

    return problems


def main():
    # CV text is often non-ASCII (e.g. '–', Hebrew); the Windows console default (cp1252) would mangle it.
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cv", type=Path)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    args = parser.parse_args()
    for p in (args.cv, args.template):
        if not p.is_file():
            print(f"File not found: {p}")
            return 2
    problems = check(args.cv.read_text(encoding="utf-8"), args.template.read_text(encoding="utf-8"))
    if problems:
        print("\n".join(problems))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
