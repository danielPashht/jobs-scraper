from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from scraper.models import Job
from scraper.search_profile import DEFAULT_WATCHER

log = logging.getLogger(__name__)

# Reported jobs are keyed per *watcher*: the bot can watch jobs for several
# people, and the same listing must be reportable once to each of them.
SCHEMA = """
CREATE TABLE IF NOT EXISTS reported_jobs (
    watcher    TEXT NOT NULL DEFAULT 'default',
    url        TEXT NOT NULL,
    dedup_key  TEXT NOT NULL,
    title      TEXT NOT NULL,
    company    TEXT NOT NULL,
    source     TEXT NOT NULL,
    salary     TEXT,
    posted_at  TEXT,
    sent_at    TEXT NOT NULL,
    PRIMARY KEY (watcher, url)
);
CREATE INDEX IF NOT EXISTS idx_reported_dedup ON reported_jobs(watcher, dedup_key);

CREATE TABLE IF NOT EXISTS subscribers (
    chat_id    INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    added_at   TEXT NOT NULL
);
"""

# Single source of truth for the insert/select column order — the placeholder
# lists below are derived from it, so adding a column can't desync them.
COLUMNS = (
    "watcher",
    "url",
    "dedup_key",
    "title",
    "company",
    "source",
    "salary",
    "posted_at",
    "sent_at",
)
COLUMN_LIST = ", ".join(COLUMNS)
PLACEHOLDERS = ", ".join("?" * len(COLUMNS))

# SQLite's default SQLITE_MAX_VARIABLE_NUMBER is 999 on older builds; a broad
# scrape easily exceeds that in one `IN (...)`, so queries are chunked.
MAX_QUERY_VARS = 900


def _chunks(items: Sequence[str], size: int = MAX_QUERY_VARS) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class Repo:
    """Thin sync SQLite wrapper. Bot calls these from a thread (asyncio.to_thread)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c:
            self._migrate_watcher_column(c)
            c.executescript(SCHEMA)

    @staticmethod
    def _migrate_watcher_column(c: sqlite3.Connection) -> None:
        """Rebuild a pre-multi-watcher `reported_jobs` (url as sole PRIMARY KEY).

        The old PK would reject a second watcher's copy of the same url, and
        SQLite can't alter a primary key in place — so copy the rows across into
        the new shape, attributing them to the default watcher. The whole rebuild
        runs in one explicit transaction: the connection is in autocommit mode, so
        without it a crash mid-way would strand the history in the legacy table.
        """
        cols = [row[1] for row in c.execute("PRAGMA table_info(reported_jobs)")]
        if not cols or "watcher" in cols:
            return
        log.info("migrating reported_jobs to per-watcher keys (watcher=%r)", DEFAULT_WATCHER)
        c.execute("BEGIN IMMEDIATE")
        try:
            c.execute("ALTER TABLE reported_jobs RENAME TO reported_jobs_legacy")
            # The index follows the rename and keeps its name, which would make
            # the CREATE INDEX below a silent no-op — and it dies with the
            # legacy table.
            c.execute("DROP INDEX IF EXISTS idx_reported_dedup")
            # executescript() would commit the open transaction, so run the DDL
            # statements individually.
            for statement in filter(str.strip, SCHEMA.split(";")):
                c.execute(statement)
            c.execute(
                f"INSERT OR IGNORE INTO reported_jobs ({COLUMN_LIST})"
                f" SELECT ?, {', '.join(COLUMNS[1:])} FROM reported_jobs_legacy",
                (DEFAULT_WATCHER,),
            )
            c.execute("DROP TABLE reported_jobs_legacy")
        except Exception:
            c.execute("ROLLBACK")
            raise
        c.execute("COMMIT")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, isolation_level=None)  # autocommit
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    # --- reported jobs ---

    def filter_new(self, jobs: Iterable[Job], watcher: str = DEFAULT_WATCHER) -> list[Job]:
        """Jobs whose url AND dedup_key this watcher hasn't been told about yet."""
        jobs = list(jobs)
        if not jobs:
            return []
        urls = sorted({str(j.url) for j in jobs})
        keys = sorted({j.dedup_key() for j in jobs})
        with closing(self._conn()) as c:
            existing_urls = self._existing(c, "url", urls, watcher)
            existing_keys = self._existing(c, "dedup_key", keys, watcher)
        return [
            j
            for j in jobs
            if str(j.url) not in existing_urls and j.dedup_key() not in existing_keys
        ]

    @staticmethod
    def _existing(
        c: sqlite3.Connection, column: str, values: Sequence[str], watcher: str
    ) -> set[str]:
        """Which of `values` this watcher already has, queried in safe-sized chunks."""
        found: set[str] = set()
        for chunk in _chunks(values):
            found.update(
                row[0]
                for row in c.execute(
                    f"SELECT {column} FROM reported_jobs WHERE watcher = ?"  # noqa: S608 — column is a literal
                    f" AND {column} IN ({','.join('?' * len(chunk))})",
                    [watcher, *chunk],
                )
            )
        return found

    def mark_reported(self, jobs: Iterable[Job], watcher: str = DEFAULT_WATCHER) -> int:
        """Record `jobs` as already reported to `watcher`.

        Parameters:
            jobs: the jobs just pushed; each is stored under (watcher, url).
            watcher: whose feed they were sent to. Defaults to the historical
                single-watcher namespace.

        Returns the number of rows actually inserted — rows this watcher already
        had are ignored, so it can be lower than ``len(jobs)``.
        """
        rows = [
            (
                watcher,
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
        with closing(self._conn()) as c:
            cur = c.executemany(
                f"INSERT OR IGNORE INTO reported_jobs ({COLUMN_LIST})"
                f" VALUES ({PLACEHOLDERS})",
                rows,
            )
            # Rows already present are ignored, so this is the real insert count.
            return cur.rowcount

    def count_reported(self, watcher: str | None = None) -> int:
        """Rows reported to `watcher`, or across all watchers when None."""
        with closing(self._conn()) as c:
            if watcher is None:
                return c.execute("SELECT COUNT(*) FROM reported_jobs").fetchone()[0]
            return c.execute(
                "SELECT COUNT(*) FROM reported_jobs WHERE watcher = ?", (watcher,)
            ).fetchone()[0]

    # --- subscribers ---

    def add_subscriber(self, chat_id: int, user_id: int) -> None:
        with closing(self._conn()) as c:
            c.execute(
                "INSERT OR REPLACE INTO subscribers (chat_id, user_id, added_at) VALUES (?, ?, ?)",
                (chat_id, user_id, datetime.now(timezone.utc).isoformat()),
            )

    def list_subscribers(self) -> list[tuple[int, int]]:
        """(chat_id, user_id) pairs — the user_id drives per-watcher routing."""
        with closing(self._conn()) as c:
            return [
                (row[0], row[1])
                for row in c.execute("SELECT chat_id, user_id FROM subscribers")
            ]

    def forget_reported(self, watcher: str) -> int:
        """Drop a watcher's dedup state so its next run re-reports everything."""
        with closing(self._conn()) as c:
            cur = c.execute("DELETE FROM reported_jobs WHERE watcher = ?", (watcher,))
            deleted = cur.rowcount
        # Destructive and irreversible — always leave a trace of who lost what.
        log.warning("cleared %d reported row(s) for watcher=%r", deleted, watcher)
        return deleted
