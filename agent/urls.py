"""Job URL checks (AGENT_SPEC.md → fetch_job): http/https only, host on ALLOWED_JOB_SITES."""

from urllib.parse import urlsplit

NOT_ALLOWED_MESSAGE = "Site not allowed. Add it to ALLOWED_JOB_SITES or paste the job text."


def host_of(url: str) -> str:
    try:
        return (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def is_allowed_url(url: str, allowed_sites: tuple[str, ...]) -> bool:
    """True if the scheme is http/https and the host is a listed host or a subdomain of one."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    if parts.scheme.lower() not in ("http", "https"):
        return False
    host = host_of(url)
    if not host:
        return False
    return any(host == site or host.endswith("." + site) for site in allowed_sites)
