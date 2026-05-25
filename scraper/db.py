from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from scraper.models import Job

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS reported_jobs (
    url        TEXT PRIMARY KEY,
    dedup_key  TEXT NOT NULL,
    title      TEXT NOT NULL,
    company    TEXT NOT NULL,
    source     TEXT NOT NULL,
    salary     TEXT,
    posted_at  TEXT,
    sent_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reported_dedup ON reported_jobs(dedup_key);

CREATE TABLE IF NOT EXISTS subscribers (
    chat_id    INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    added_at   TEXT NOT NULL
);
"""


class Repo:
    """Thin sync SQLite wrapper. Bot calls these from a thread (asyncio.to_thread)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, isolation_level=None)  # autocommit
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    # --- reported jobs ---

    def filter_new(self, jobs: Iterable[Job]) -> list[Job]:
        """Return the subset of jobs whose url AND dedup_key are not yet recorded."""
        jobs = list(jobs)
        if not jobs:
            return []
        with self._conn() as c:
            urls = {str(j.url) for j in jobs}
            keys = {j.dedup_key() for j in jobs}
            existing_urls = {
                row[0]
                for row in c.execute(
                    f"SELECT url FROM reported_jobs WHERE url IN ({','.join('?' * len(urls))})",
                    list(urls),
                )
            }
            existing_keys = {
                row[0]
                for row in c.execute(
                    f"SELECT dedup_key FROM reported_jobs WHERE dedup_key IN ({','.join('?' * len(keys))})",
                    list(keys),
                )
            }
        return [
            j
            for j in jobs
            if str(j.url) not in existing_urls and j.dedup_key() not in existing_keys
        ]

    def mark_reported(self, jobs: Iterable[Job]) -> int:
        rows = [
            (
                str(j.url),
                j.dedup_key(),
                j.title,
                j.company,
                j.source,
                j.salary,
                j.posted_at.isoformat() if j.posted_at else None,
                datetime.now(timezone.utc).isoformat(),
            )
            for j in jobs
        ]
        if not rows:
            return 0
        with self._conn() as c:
            c.executemany(
                "INSERT OR IGNORE INTO reported_jobs"
                " (url, dedup_key, title, company, source, salary, posted_at, sent_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def count_reported(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM reported_jobs").fetchone()[0]

    # --- subscribers ---

    def add_subscriber(self, chat_id: int, user_id: int) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO subscribers (chat_id, user_id, added_at) VALUES (?, ?, ?)",
                (chat_id, user_id, datetime.now(timezone.utc).isoformat()),
            )

    def list_subscriber_chat_ids(self) -> list[int]:
        with self._conn() as c:
            return [row[0] for row in c.execute("SELECT chat_id FROM subscribers")]
