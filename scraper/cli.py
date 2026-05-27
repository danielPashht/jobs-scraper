from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from scraper.boards import ALL_BOARDS
from scraper.filters import (
    DEFAULT_EXCLUDE_KEYWORDS,
    DEFAULT_INCLUDE_KEYWORDS,
    deduplicate,
    filter_jobs,
    rank,
)
from scraper.models import Job
from scraper.output import render_table, write_csv, write_json


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jobs-scraper",
        description="Scrape web3/fintech job boards for SDET/QA roles.",
    )
    p.add_argument(
        "--boards",
        nargs="+",
        default=["web3career"],
        choices=sorted(ALL_BOARDS.keys()),
        help="Boards to scrape (default: web3career)",
    )
    p.add_argument(
        "--keywords",
        nargs="+",
        default=list(DEFAULT_INCLUDE_KEYWORDS),
        help="Include keywords (title/tags/location, case-insensitive)",
    )
    p.add_argument(
        "--exclude",
        nargs="+",
        default=list(DEFAULT_EXCLUDE_KEYWORDS),
        help="Exclude keywords",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Maximum pages to fetch per board (default: 3)",
    )
    p.add_argument(
        "--remote-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep only remote jobs (default: on). Use --no-remote-only to include onsite.",
    )
    p.add_argument(
        "--exclude-ineligible",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Drop roles locked to a region the user can't take (US / rest of the "
            "Americas / Middle East) with no worldwide/APAC/Europe signal. Keeps "
            "remote-anywhere, APAC and European (remote or relocation) roles, and "
            "ambiguous listings. Default: on."
        ),
    )
    p.add_argument(
        "--max-age-days",
        type=int,
        default=60,
        help="Drop jobs older than this many days (default: 60). Use 0 to disable.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write results to this file. Format inferred from suffix (.json/.csv).",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    return p


def _scrape(boards: list[str], max_pages: int) -> list[Job]:
    collected: list[Job] = []
    for name in boards:
        board_cls = ALL_BOARDS[name]
        board = board_cls()
        try:
            collected.extend(board.fetch(max_pages=max_pages))
        except Exception as exc:  # noqa: BLE001 — one board's failure shouldn't kill the run
            logging.error("board %s failed: %s", name, exc)
        finally:
            board.close()
    return collected


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(show_time=False, show_path=False)],
    )

    raw = _scrape(args.boards, args.max_pages)
    logging.info("scraped %d raw jobs", len(raw))

    filtered = filter_jobs(
        raw,
        include=args.keywords,
        exclude=args.exclude,
        remote_only=args.remote_only,
        exclude_ineligible=args.exclude_ineligible,
        max_age_days=args.max_age_days if args.max_age_days > 0 else None,
    )
    deduped = deduplicate(filtered)
    ranked = rank(deduped)
    logging.info("after filter/dedup: %d jobs", len(ranked))

    console = Console()
    if not ranked:
        console.print("[yellow]No jobs matched. Try relaxing --keywords or --remote-only.[/yellow]")
        return 0

    render_table(ranked, console=console)

    if args.output is not None:
        suffix = args.output.suffix.lower()
        if suffix == ".json":
            write_json(ranked, args.output)
        elif suffix == ".csv":
            write_csv(ranked, args.output)
        else:
            logging.error("unknown output format: %s (use .json or .csv)", suffix)
            return 2
        logging.info("wrote %d jobs to %s", len(ranked), args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
