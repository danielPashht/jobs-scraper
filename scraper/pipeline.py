from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

from scraper.boards import ALL_BOARDS
from scraper.filters import (
    DEFAULT_BLOCKED_REGIONS,
    DEFAULT_ELIGIBLE_REGIONS,
    DEFAULT_EXCLUDE_KEYWORDS,
    DEFAULT_INCLUDE_KEYWORDS,
    DEFAULT_PRIORITIZE,
    deduplicate,
    filter_jobs,
    rank,
)
from scraper.models import Job

log = logging.getLogger(__name__)


def scrape(
    boards: Iterable[str],
    max_pages: int,
    *,
    keywords: Iterable[str] = DEFAULT_INCLUDE_KEYWORDS,
    board_options: Mapping[str, Mapping[str, object]] | None = None,
) -> list[Job]:
    # `keywords` is handed to each board so the ones that need a server-side
    # query (LinkedIn) or a path slug (web3.career) can derive it from the role;
    # broad-feed boards ignore it and let the pipeline filter narrow.
    # `board_options` carries per-board source settings from the profile's
    # `[boards.<name>]` tables (LinkedIn locations, Telegram channels, ...).
    keywords = list(keywords)
    board_options = board_options or {}
    out: list[Job] = []
    for name in boards:
        board_cls = ALL_BOARDS.get(name)
        if board_cls is None:
            log.warning("unknown board: %s", name)
            continue
        board = board_cls(keywords=keywords, options=board_options.get(name, {}))
        try:
            out.extend(board.fetch(max_pages=max_pages))
        except Exception as exc:  # noqa: BLE001 — one bad board shouldn't kill the run
            log.error("board %s failed: %s", name, exc)
        finally:
            board.close()
    return out


def run_pipeline(
    *,
    boards: Iterable[str],
    max_pages: int,
    keywords: Iterable[str] = DEFAULT_INCLUDE_KEYWORDS,
    exclude: Iterable[str] = DEFAULT_EXCLUDE_KEYWORDS,
    remote_only: bool = True,
    exclude_ineligible: bool = True,
    eligible_regions: Iterable[str] = DEFAULT_ELIGIBLE_REGIONS,
    blocked_regions: Iterable[str] = DEFAULT_BLOCKED_REGIONS,
    block_us_states: bool = True,
    prioritize: Iterable[str] = DEFAULT_PRIORITIZE,
    max_age_days: int | None = 60,
    board_options: Mapping[str, Mapping[str, object]] | None = None,
) -> list[Job]:
    """Full scrape → filter → dedup → rank pipeline. Returns the ranked job list."""
    raw = scrape(boards, max_pages, keywords=keywords, board_options=board_options)
    log.info("scraped %d raw jobs", len(raw))
    filtered = filter_jobs(
        raw,
        include=keywords,
        exclude=exclude,
        remote_only=remote_only,
        exclude_ineligible=exclude_ineligible,
        eligible_regions=eligible_regions,
        blocked_regions=blocked_regions,
        block_us_states=block_us_states,
        max_age_days=max_age_days,
    )
    deduped = deduplicate(filtered)
    ranked = rank(deduped, prioritize=prioritize)
    log.info("after filter/dedup/rank: %d jobs", len(ranked))
    return ranked
