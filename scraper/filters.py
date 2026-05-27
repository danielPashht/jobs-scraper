from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from scraper.models import Job

DEFAULT_INCLUDE_KEYWORDS = (
    "automation qa",
    "qa automation",  # the common reversed order ("QA Automation Engineer")
    "test automation",  # "Test Automation Engineer", "Mobile Test Automation"
    "sdet",
    "engineer in test",  # SDET spelled out: "Software (Development) Engineer in Test"
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

# --- Location eligibility --------------------------------------------------
# Target user is an Asia-based nomad who will take either (a) a role he can do
# fully remotely from anywhere/Asia, or (b) anything in Europe (remote-EU OR a
# relocation offer). So a listing is "eligible" when it carries a worldwide /
# APAC / European signal — or when it carries no clear region lock at all
# (ambiguous → keep, so we don't miss good jobs). It's dropped only when it is
# clearly locked to a region he can't use (the US, the rest of the Americas,
# the Middle East) with no eligible signal present.

# A truly location-agnostic remote role.
_GLOBAL_TOKENS = (
    "worldwide",
    "global",
    "anywhere",
    "international",
    "work from anywhere",
    "fully remote",
    "remote-first",
    "remote first",
)

# Europe — either remote-from-Europe or a relocation target. Both are wanted.
_EUROPE_TOKENS = (
    "europe", "european union", "european", " eu ", "eu-only", "eu only", "emea",
    "germany", "france", "spain", "portugal", "netherlands", "uk",
    "united kingdom", "england", "scotland", "wales", "ireland", "poland",
    "ukraine", "estonia", "latvia", "lithuania", "czech", "switzerland",
    "italy", "austria", "belgium", "denmark", "sweden", "norway", "finland",
    "iceland", "romania", "bulgaria", "greece", "hungary", "croatia", "serbia",
    "slovakia", "slovenia", "luxembourg", "cyprus", "malta", "georgia",
    "armenia", "moldova",
)

# APAC — workable from where the user already is.
_APAC_TOKENS = (
    "apac", "asia", "vietnam", "singapore", "thailand", "indonesia",
    "philippines", "malaysia", "japan", "korea", "hong kong", "taiwan",
    "india", "china", "australia", "new zealand",
)

# Region locks the user CANNOT use: the US and the rest of the Americas, plus
# the Middle East. Presence of one of these (with no eligible signal) drops it.
_US_NAME_TOKENS = ("united states", "usa", " us ", "us-only", "us only", "u.s.")

# On LinkedIn, US locations arrive as "City, ST" (e.g. "Austin, TX"). Match a
# trailing two-letter state code on a *location string* specifically, so we
# don't false-positive on e.g. ", Inc" appearing in a title.
_US_STATE_RE = re.compile(
    r",\s*(a[klrz]|c[aot]|d[ce]|fl|ga|hi|i[adln]|k[sy]|la|m[adeinost]|"
    r"n[cdehjmvy]|o[hkr]|pa|ri|s[cd]|t[nx]|ut|v[at]|w[aivy])$",
    re.IGNORECASE,
)

_OTHER_INELIGIBLE_TOKENS = (
    "canada", "mexico", "brazil", "argentina", "colombia", "chile", "peru",
    "uruguay", "latam", "latin america", "americas", "united arab emirates",
    "uae", "dubai", "saudi", "qatar", "kuwait", "bahrain",
)


def _haystack(job: Job) -> str:
    parts = [job.title, " ".join(job.tags), " ".join(job.locations)]
    return " ".join(parts).lower()


def matches(job: Job, include: Iterable[str], exclude: Iterable[str]) -> bool:
    hay = _haystack(job)
    if any(bad.lower() in hay for bad in exclude):
        return False
    return any(kw.lower() in hay for kw in include)


def is_eligible(job: Job) -> bool:
    """True when the listing is workable for an Asia-based nomad open to Europe.

    Keeps worldwide / APAC / European roles, and anything with no clear region
    lock (ambiguous → keep). Drops only roles clearly locked to a region the
    user can't use (the US, the rest of the Americas, the Middle East) with no
    eligible signal. Conservative by design — better to surface a borderline
    role than silently miss a good one.
    """
    hay = _haystack(job)
    if any(tok in hay for tok in _GLOBAL_TOKENS):
        return True
    if any(tok in hay for tok in _EUROPE_TOKENS):
        return True
    if any(tok in hay for tok in _APAC_TOKENS):
        return True
    # No eligible marker — drop only on a clear ineligible-region lock.
    if any(tok in hay for tok in _US_NAME_TOKENS):
        return False
    if any(tok in hay for tok in _OTHER_INELIGIBLE_TOKENS):
        return False
    if any(_US_STATE_RE.search(loc.strip()) for loc in job.locations):
        return False
    return True  # ambiguous (no signal either way) → keep


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
    exclude_ineligible: bool = False,
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
        if exclude_ineligible and not is_eligible(job):
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
