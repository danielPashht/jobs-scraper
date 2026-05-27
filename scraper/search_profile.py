"""The search profile — *what* you're hunting for, decoupled from *how*.

A ``search.toml`` file (gitignored, like ``.env``) holds the role label,
include/exclude keywords, and location-eligibility rules. ``search.example.toml``
is the committed template; the ``/setup-search`` skill fills a real one in.
Operational/secret settings (Telegram token, schedule, boards) stay in ``.env``
via ``scraper.config.Settings``.

When no ``search.toml`` exists, ``load_profile()`` returns the built-in defaults,
which reproduce the original SDET/QA + Asia-nomad behaviour — so the project
works out of the box, and a new user only needs the profile to change *what* it
searches for.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

from scraper.filters import (
    DEFAULT_BLOCKED_REGIONS,
    DEFAULT_ELIGIBLE_REGIONS,
    DEFAULT_EXCLUDE_KEYWORDS,
    DEFAULT_INCLUDE_KEYWORDS,
    DEFAULT_PRIORITIZE,
)

log = logging.getLogger(__name__)

DEFAULT_ROLE = "SDET / Automation QA"
DEFAULT_PROFILE_PATH = Path("search.toml")


@dataclass(frozen=True)
class SearchProfile:
    role: str = DEFAULT_ROLE
    include_keywords: tuple[str, ...] = DEFAULT_INCLUDE_KEYWORDS
    exclude_keywords: tuple[str, ...] = DEFAULT_EXCLUDE_KEYWORDS
    eligibility_enabled: bool = True
    eligible_regions: tuple[str, ...] = DEFAULT_ELIGIBLE_REGIONS
    blocked_regions: tuple[str, ...] = DEFAULT_BLOCKED_REGIONS
    block_us_states: bool = True
    prioritize: tuple[str, ...] = DEFAULT_PRIORITIZE


def _as_tuple(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    """A non-empty list in the TOML wins; anything else falls back to default."""
    if isinstance(value, (list, tuple)) and value:
        return tuple(str(v) for v in value)
    return default


def load_profile(path: str | Path | None = None) -> SearchProfile:
    """Load a SearchProfile from ``search.toml`` (or the given path).

    Missing file → built-in defaults. Missing keys within the file fall back to
    their defaults individually, so a partial profile is valid.
    """
    p = Path(path) if path is not None else DEFAULT_PROFILE_PATH
    if not p.exists():
        log.info("no %s — using built-in default search profile (%s)", p, DEFAULT_ROLE)
        return SearchProfile()

    with p.open("rb") as fh:
        data = tomllib.load(fh)
    search = data.get("search", {})
    elig = data.get("eligibility", {})

    return SearchProfile(
        role=str(search.get("role") or DEFAULT_ROLE),
        include_keywords=_as_tuple(search.get("include_keywords"), DEFAULT_INCLUDE_KEYWORDS),
        exclude_keywords=_as_tuple(search.get("exclude_keywords"), DEFAULT_EXCLUDE_KEYWORDS),
        eligibility_enabled=bool(elig.get("enabled", True)),
        eligible_regions=_as_tuple(elig.get("eligible_regions"), DEFAULT_ELIGIBLE_REGIONS),
        blocked_regions=_as_tuple(elig.get("blocked_regions"), DEFAULT_BLOCKED_REGIONS),
        block_us_states=bool(elig.get("block_us_states", True)),
        prioritize=_as_tuple(elig.get("prioritize"), DEFAULT_PRIORITIZE),
    )
