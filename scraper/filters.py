from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from scraper.models import Job

DEFAULT_INCLUDE_KEYWORDS = (
    "automation qa",
    "sdet",
    "test engineer",
    "qa engineer",
    "quality assurance",
    "pytest",
    "playwright",
    "selenium",
)

DEFAULT_EXCLUDE_KEYWORDS = (
    # User is not interested in manual-only roles.
    "manual qa",
    "manual quality assurance",
    "manual test",
    "manual tester",
    "intern",
    # Speculative / "submit your CV" non-postings that boards sometimes surface.
    "expression of interest",
)

# Exact-match (case-insensitive, stripped) junk titles — placeholder listings
# boards occasionally publish. Substring excludes can't be used here because
# e.g. "tst" would also strip "Pytest specialist".
JUNK_TITLES: frozenset[str] = frozenset({
    "tst",
    "test",
    "test job",
    "test posting",
})


def is_junk_title(title: str) -> bool:
    return title.strip().lower() in JUNK_TITLES

APAC_HINTS = (
    "apac",
    "asia",
    "vietnam",
    "singapore",
    "thailand",
    "indonesia",
    "philippines",
    "japan",
    "korea",
    "hong kong",
    "taiwan",
    "remote",
)

# Strings that indicate a job restricts hiring to the United States.
_US_TOKENS = ("united states", "usa", " us ", "us-only", "us only", "u.s.")

# Strings that signal a truly global remote role — overrides US-location signal.
_GLOBAL_TOKENS = (
    "worldwide",
    "global",
    "anywhere",
    "international",
    "remote, eu",
    "remote — emea",
    "remote emea",
    "apac",
    "europe",
    "latam",
)

# Non-US country / region tokens. If present anywhere in the listing, the role
# is not US-only even if a US location is also listed.
_NON_US_COUNTRY_TOKENS = (
    "germany",
    "france",
    "spain",
    "portugal",
    "netherlands",
    "uk",
    "united kingdom",
    "ireland",
    "poland",
    "ukraine",
    "estonia",
    "latvia",
    "czech",
    "switzerland",
    "italy",
    "austria",
    "vietnam",
    "thailand",
    "singapore",
    "indonesia",
    "philippines",
    "japan",
    "korea",
    "hong kong",
    "taiwan",
    "india",
    "argentina",
    "brazil",
    "mexico",
    "colombia",
    "canada",  # not US, even if many US-only roles also accept Canada
    "australia",
    "new zealand",
    "south africa",
    "uae",
    "dubai",
    "israel",
    "turkey",
    "georgia",  # the country, not the state — noisy but worth keeping for our user
)


def _haystack(job: Job) -> str:
    parts = [job.title, " ".join(job.tags), " ".join(job.locations)]
    return " ".join(parts).lower()


def matches(job: Job, include: Iterable[str], exclude: Iterable[str]) -> bool:
    hay = _haystack(job)
    if any(bad.lower() in hay for bad in exclude):
        return False
    return any(kw.lower() in hay for kw in include)


def is_us_only(job: Job) -> bool:
    """Heuristic: True when the listing looks restricted to the United States.

    Conservative — only flags when (a) a US location is present and (b) there's
    no signal of a global hire (no other-country location, no 'worldwide'/'global'
    in title or tags). Won't catch every US-only role, but minimises false positives
    on truly global listings.
    """
    hay = _haystack(job)
    has_us = any(tok in hay for tok in _US_TOKENS)
    if not has_us:
        return False
    has_global_marker = any(tok in hay for tok in _GLOBAL_TOKENS)
    has_other_country = any(tok in hay for tok in _NON_US_COUNTRY_TOKENS)
    return not (has_global_marker or has_other_country)


def is_recent(job: Job, *, max_age_days: int) -> bool:
    """Return True if posted_at is within max_age_days of now (unknown = treat as recent)."""
    if job.posted_at is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    posted = job.posted_at
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return posted >= cutoff


def filter_jobs(
    jobs: Iterable[Job],
    *,
    include: Iterable[str] = DEFAULT_INCLUDE_KEYWORDS,
    exclude: Iterable[str] = DEFAULT_EXCLUDE_KEYWORDS,
    remote_only: bool = False,
    exclude_us_only: bool = False,
    max_age_days: int | None = None,
) -> list[Job]:
    include = tuple(include)
    exclude = tuple(exclude)
    out: list[Job] = []
    for job in jobs:
        if is_junk_title(job.title):
            continue
        if remote_only and not job.remote:
            continue
        if exclude_us_only and is_us_only(job):
            continue
        if max_age_days is not None and not is_recent(job, max_age_days=max_age_days):
            continue
        if matches(job, include, exclude):
            out.append(job)
    return out


def deduplicate(jobs: Iterable[Job]) -> list[Job]:
    seen: dict[str, Job] = {}
    for job in jobs:
        key = job.dedup_key()
        # Keep the first occurrence; later boards just dedupe against it.
        if key not in seen:
            seen[key] = job
    return list(seen.values())


def is_apac_friendly(job: Job) -> bool:
    hay = _haystack(job)
    return any(hint in hay for hint in APAC_HINTS)


def rank(jobs: Iterable[Job]) -> list[Job]:
    """Sort jobs by posted_at desc (newest first), then by APAC-friendliness."""

    def key(j: Job) -> tuple[int, float]:
        # APAC-friendly first (0 < 1), then most recent first (negated timestamp).
        apac = 0 if is_apac_friendly(j) else 1
        ts = j.posted_at.timestamp() if j.posted_at else 0.0
        return (apac, -ts)

    return sorted(jobs, key=key)
