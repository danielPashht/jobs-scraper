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

**Multiple watchers.** One bot can watch jobs for several people: list several
profile files in ``JOBS_PROFILES`` (e.g. ``search.toml,profiles/anastasia.toml``)
and ``load_profiles()`` returns one ``SearchProfile`` each. A profile's
``watcher`` key namespaces its dedup state in the DB (so the same listing can be
pushed to two people) and labels its results; its optional ``boards`` key lets
one watcher scrape a different board set than the ops default.
"""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
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
DEFAULT_WATCHER = "default"


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
    # Who this search is for. Namespaces the bot's dedup state, so two watchers
    # can each be told about the same listing. The historical single-watcher
    # state lives under DEFAULT_WATCHER.
    watcher: str = DEFAULT_WATCHER
    # Boards this watcher wants. Empty → whatever JOBS_BOARDS / the CLI says.
    boards: tuple[str, ...] = ()
    # Source-side settings per board, from `[boards.<name>]` tables in the TOML
    # (e.g. LinkedIn's `locations`, Telegram's `channels`). Boards that need none
    # ignore it, exactly as broad-feed boards ignore `keywords`.
    board_options: dict[str, dict] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Label for output — the watcher's name, or the role for the default."""
        if self.watcher and self.watcher != DEFAULT_WATCHER:
            return f"{self.watcher} · {self.role}"
        return self.role


def _as_tuple(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    """A non-empty list in the TOML wins; anything else falls back to default."""
    if isinstance(value, (list, tuple)) and value:
        return tuple(str(v) for v in value)
    return default


def _as_board_options(value: object) -> dict[str, dict]:
    """`[boards.<name>]` tables → {board_name: {option: value}}; non-tables dropped."""
    if not isinstance(value, dict):
        return {}
    out = {}
    for name, options in value.items():
        if isinstance(options, dict):
            out[str(name)] = options
        else:
            log.warning("ignoring [boards.%s] — expected a table, got %r", name, type(options))
    return out


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
        watcher=str(search.get("watcher") or DEFAULT_WATCHER),
        boards=_as_tuple(search.get("boards"), ()),
        board_options=_as_board_options(data.get("boards")),
    )


def load_profiles(paths: Iterable[str | Path] | None = None) -> list[SearchProfile]:
    """Load one profile per path (see ``Settings.profiles`` / ``JOBS_PROFILES``).

    Duplicate ``watcher`` keys are dropped — two profiles sharing a watcher would
    share dedup state and silently hide each other's jobs.
    """
    paths = list(paths) if paths else [DEFAULT_PROFILE_PATH]
    out: list[SearchProfile] = []
    seen: set[str] = set()
    for path in paths:
        profile = load_profile(path)
        if profile.watcher in seen:
            log.warning(
                "profile %s reuses watcher=%r — skipping (watcher keys must be unique)",
                path,
                profile.watcher,
            )
            continue
        seen.add(profile.watcher)
        out.append(profile)
    return out
