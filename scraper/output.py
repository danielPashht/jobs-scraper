from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path

from rich.console import Console
from rich.table import Table

from scraper.filters import is_apac_friendly
from scraper.models import Job


def render_table(jobs: Iterable[Job], console: Console | None = None) -> None:
    console = console or Console()
    table = Table(show_lines=False, header_style="bold magenta")
    table.add_column("Title", overflow="fold", max_width=40)
    table.add_column("Company")
    table.add_column("Source")
    table.add_column("Salary")
    table.add_column("Posted")
    table.add_column("APAC")
    table.add_column("URL", overflow="fold")

    for j in jobs:
        table.add_row(
            j.title,
            j.company,
            j.source,
            j.salary or "-",
            j.posted_at.date().isoformat() if j.posted_at else "-",
            "yes" if is_apac_friendly(j) else "-",
            str(j.url),
        )

    console.print(table)


def write_json(jobs: Iterable[Job], path: Path) -> None:
    payload = [json.loads(j.model_dump_json()) for j in jobs]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def write_csv(jobs: Iterable[Job], path: Path) -> None:
    jobs = list(jobs)
    fields = ["title", "company", "source", "salary", "posted_at", "remote", "url", "tags", "locations"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for j in jobs:
            writer.writerow(
                {
                    "title": j.title,
                    "company": j.company,
                    "source": j.source,
                    "salary": j.salary or "",
                    "posted_at": j.posted_at.isoformat() if j.posted_at else "",
                    "remote": j.remote,
                    "url": str(j.url),
                    "tags": ",".join(j.tags),
                    "locations": ",".join(j.locations),
                }
            )
