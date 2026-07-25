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

# Aggregated defaults consumed by is_eligible / rank when no profile overrides
# them (see scraper/search_profile.py). A listing is KEPT if it matches any
# eligible-region token; otherwise DROPPED if it matches a blocked-region token
# (or a US "City, ST" code, when block_us_states is on). These reproduce the
# original Asia-nomad-open-to-Europe behaviour as the shipped default.
DEFAULT_ELIGIBLE_REGIONS = _GLOBAL_TOKENS + _EUROPE_TOKENS + _APAC_TOKENS
DEFAULT_BLOCKED_REGIONS = _US_NAME_TOKENS + _OTHER_INELIGIBLE_TOKENS
# Tokens that float to the top of the ranked output (preferred locations).
DEFAULT_PRIORITIZE = APAC_HINTS


def _haystack(job: Job, *, with_description: bool = False) -> str:
    parts = [job.title, " ".join(job.tags), " ".join(job.locations)]
    if with_description and job.description:
        parts.append(job.description)
    return " ".join(parts).lower()


def matches(job: Job, include: Iterable[str], exclude: Iterable[str]) -> bool:
    """Keep when an include keyword hits and no exclude keyword does.

    Includes read the ad body too (Telegram posts carry the whole ad, where the
    role is often only named in the text). Excludes deliberately do NOT: they
    encode title semantics, and a body mentioning e.g. "работа с senior
    разработчиками" must not drop an otherwise-junior role.
    """
    title_hay = _haystack(job)
    if any(bad.lower() in title_hay for bad in exclude):
        return False
    full_hay = _haystack(job, with_description=True)
    return any(kw.lower() in full_hay for kw in include)


def is_eligible(
    job: Job,
    *,
    eligible_regions: Iterable[str] = DEFAULT_ELIGIBLE_REGIONS,
    blocked_regions: Iterable[str] = DEFAULT_BLOCKED_REGIONS,
    block_us_states: bool = True,
) -> bool:
    """True when the listing is workable from the user's location situation.

    Keeps any listing carrying an eligible-region signal, plus anything with no
    clear region lock (ambiguous → keep). Drops only listings clearly locked to
    a blocked region (or a US "City, ST" code when ``block_us_states`` is on)
    with no eligible signal present. Conservative by design — better to surface
    a borderline role than silently miss a good one. The default region lists
    reproduce the original Asia-nomad-open-to-Europe behaviour; the search
    profile overrides them per user.
    """
    hay = _haystack(job)
    if any(tok in hay for tok in eligible_regions):
        return True
    # No eligible marker — drop only on a clear ineligible-region lock.
    if any(tok in hay for tok in blocked_regions):
        return False
    if block_us_states and any(_US_STATE_RE.search(loc.strip()) for loc in job.locations):
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
    eligible_regions: Iterable[str] = DEFAULT_ELIGIBLE_REGIONS,
    blocked_regions: Iterable[str] = DEFAULT_BLOCKED_REGIONS,
    block_us_states: bool = True,
    max_age_days: int | None = None,
) -> list[Job]:
    include = tuple(include)
    exclude = tuple(exclude)
    eligible_regions = tuple(eligible_regions)
    blocked_regions = tuple(blocked_regions)
    out: list[Job] = []
    for job in jobs:
        if is_junk_title(job.title):
            continue
        if remote_only and not job.remote:
            continue
        if exclude_ineligible and not is_eligible(
            job,
            eligible_regions=eligible_regions,
            blocked_regions=blocked_regions,
            block_us_states=block_us_states,
        ):
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


def is_prioritized(job: Job, prioritize: Iterable[str] = DEFAULT_PRIORITIZE) -> bool:
    """True when the listing matches a preferred-location token (floats to top)."""
    hay = _haystack(job)
    return any(tok in hay for tok in prioritize)


def is_apac_friendly(job: Job) -> bool:
    """Back-compat alias for the shipped default (APAC-preferred) prioritization."""
    return is_prioritized(job)


def rank(jobs: Iterable[Job], *, prioritize: Iterable[str] = DEFAULT_PRIORITIZE) -> list[Job]:
    """Sort by preferred-location first, then posted_at desc (newest first)."""
    prioritize = tuple(prioritize)

    def key(j: Job) -> tuple[int, float]:
        # Preferred-location first (0 < 1), then most recent first (negated ts).
        pref = 0 if is_prioritized(j, prioritize) else 1
        ts = j.posted_at.timestamp() if j.posted_at else 0.0
        return (pref, -ts)

    return sorted(jobs, key=key)
