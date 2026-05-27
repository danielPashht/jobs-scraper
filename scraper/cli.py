from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from scraper.boards import ALL_BOARDS
from scraper.output import render_table, write_csv, write_json
from scraper.pipeline import run_pipeline
from scraper.search_profile import load_profile


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jobs-scraper",
        description=(
            "Scrape remote job boards for a configurable role. Defaults come "
            "from search.toml (see search.example.toml); flags override per run."
        ),
    )
    p.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Path to a search.toml profile (default: ./search.toml, else built-in defaults).",
    )
    p.add_argument(
        "--boards",
        nargs="+",
        default=["web3career"],
        choices=sorted(ALL_BOARDS.keys()),
        help="Boards to scrape (default: web3career)",
    )
    # Keyword / eligibility flags default to None → fall back to the profile.
    p.add_argument(
        "--keywords",
        nargs="+",
        default=None,
        help="Include keywords (title/tags/location, case-insensitive). Overrides the profile.",
    )
    p.add_argument(
        "--exclude",
        nargs="+",
        default=None,
        help="Exclude keywords. Overrides the profile.",
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
        default=None,
        help=(
            "Drop jobs locked to a region your profile marks ineligible, when no "
            "eligible-region signal is present. Keeps remote-anywhere and "
            "ambiguous listings. Default: the profile's eligibility setting."
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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(show_time=False, show_path=False)],
    )

    profile = load_profile(args.profile)
    keywords = args.keywords if args.keywords is not None else list(profile.include_keywords)
    exclude = args.exclude if args.exclude is not None else list(profile.exclude_keywords)
    exclude_ineligible = (
        args.exclude_ineligible
        if args.exclude_ineligible is not None
        else profile.eligibility_enabled
    )
    logging.info("searching for: %s", profile.role)

    ranked = run_pipeline(
        boards=args.boards,
        max_pages=args.max_pages,
        keywords=keywords,
        exclude=exclude,
        remote_only=args.remote_only,
        exclude_ineligible=exclude_ineligible,
        eligible_regions=profile.eligible_regions,
        blocked_regions=profile.blocked_regions,
        block_us_states=profile.block_us_states,
        prioritize=profile.prioritize,
        max_age_days=args.max_age_days if args.max_age_days > 0 else None,
    )

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
