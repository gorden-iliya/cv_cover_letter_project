# prompts/ — prompts as Python, one per file

- One prompt per file; each exposes a string or a function that builds and returns it.
- Job posting text is untrusted: always wrap it in `<job_posting>…</job_posting>` and tell the
  model to ignore instructions inside it.
- No business logic here beyond building the prompt string.
