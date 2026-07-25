from __future__ import annotations

import sqlite3

from scraper.db import Repo
from tests.test_filters import make_job

LEGACY_SCHEMA = """
CREATE TABLE reported_jobs (
    url        TEXT PRIMARY KEY,
    dedup_key  TEXT NOT NULL,
    title      TEXT NOT NULL,
    company    TEXT NOT NULL,
    source     TEXT NOT NULL,
    salary     TEXT,
    posted_at  TEXT,
    sent_at    TEXT NOT NULL
);
CREATE INDEX idx_reported_dedup ON reported_jobs(dedup_key);
"""


def test_filter_new_is_scoped_per_watcher(tmp_path):
    repo = Repo(tmp_path / "jobs.db")
    job = make_job(title="Business Development Manager", company="Acme")

    assert repo.filter_new([job], "daniel") == [job]
    repo.mark_reported([job], "daniel")

    # Reported to daniel only — anastasia still gets to hear about it.
    assert repo.filter_new([job], "daniel") == []
    assert repo.filter_new([job], "anastasia") == [job]
    repo.mark_reported([job], "anastasia")
    assert repo.filter_new([job], "anastasia") == []

    assert repo.count_reported("daniel") == 1
    assert repo.count_reported("anastasia") == 1
    assert repo.count_reported() == 2


def test_dedup_key_collision_is_also_per_watcher(tmp_path):
    repo = Repo(tmp_path / "jobs.db")
    first = make_job(title="BD Manager", company="Acme", url="https://example.com/a")
    # Same title|company → same dedup key, different url (cross-board repost).
    repost = make_job(title="BD Manager", company="Acme", url="https://example.com/b")

    repo.mark_reported([first], "anastasia")
    assert repo.filter_new([repost], "anastasia") == []
    assert repo.filter_new([repost], "daniel") == [repost]


def test_migrates_legacy_single_watcher_table(tmp_path):
    path = tmp_path / "jobs.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    job = make_job(title="Senior SDET", company="Acme")
    with sqlite3.connect(path, isolation_level=None) as c:
        c.executescript(LEGACY_SCHEMA)
        c.execute(
            "INSERT INTO reported_jobs"
            " (url, dedup_key, title, company, source, salary, posted_at, sent_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(job.url), job.dedup_key(), job.title, job.company, job.source,
             None, None, "2026-01-01T00:00:00+00:00"),
        )

    repo = Repo(path)  # migration runs on open

    # History survives, attributed to the default watcher…
    assert repo.count_reported("default") == 1
    assert repo.filter_new([job], "default") == []
    # …and a second watcher can now be told about the same listing.
    assert repo.filter_new([job], "anastasia") == [job]
    repo.mark_reported([job], "anastasia")
    assert repo.count_reported() == 2

    with sqlite3.connect(path) as c:
        indexes = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        tables = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "idx_reported_dedup" in indexes
    assert "reported_jobs_legacy" not in tables
