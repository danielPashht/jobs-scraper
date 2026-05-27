from __future__ import annotations

import logging
from collections.abc import Iterable

from scraper.boards import ALL_BOARDS
from scraper.filters import (
    DEFAULT_EXCLUDE_KEYWORDS,
    DEFAULT_INCLUDE_KEYWORDS,
    deduplicate,
    filter_jobs,
    rank,
)
from scraper.models import Job

log = logging.getLogger(__name__)


def scrape(boards: Iterable[str], max_pages: int) -> list[Job]:
    out: list[Job] = []
    for name in boards:
        board_cls = ALL_BOARDS.get(name)
        if board_cls is None:
            log.warning("unknown board: %s", name)
            continue
        board = board_cls()
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
    max_age_days: int | None = 60,
) -> list[Job]:
    """Full scrape → filter → dedup → rank pipeline. Returns the ranked job list."""
    raw = scrape(boards, max_pages)
    log.info("scraped %d raw jobs", len(raw))
    filtered = filter_jobs(
        raw,
        include=keywords,
        exclude=exclude,
        remote_only=remote_only,
        exclude_ineligible=exclude_ineligible,
        max_age_days=max_age_days,
    )
    deduped = deduplicate(filtered)
    ranked = rank(deduped)
    log.info("after filter/dedup/rank: %d jobs", len(ranked))
    return ranked
