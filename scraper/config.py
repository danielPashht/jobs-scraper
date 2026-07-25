from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# NOTE: this module holds operational/secret config only (Telegram, schedule,
# boards, paging). *What* to search for — role keywords + location eligibility —
# lives in search.toml via scraper.search_profile.SearchProfile.


def _parse_paths(raw: str) -> tuple[Path, ...]:
    return tuple(Path(chunk.strip()) for chunk in raw.split(",") if chunk.strip())


def _parse_ids(raw: str) -> tuple[int, ...]:
    out = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            out.append(int(chunk))
    return tuple(out)


def _parse_watcher_users(raw: str) -> dict[str, tuple[int, ...]]:
    """Parse ``watcher=id[,id];watcher2=id`` into {watcher: (user_id, ...)}.

    This is the routing table: a watcher listed here is pushed only to those
    Telegram users, and those users are pushed only the watchers they're listed
    for. Watchers absent from the table go to every subscriber the table doesn't
    claim — so a single-watcher setup needs no entry at all.
    """
    out: dict[str, tuple[int, ...]] = {}
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        watcher, _, ids = entry.partition("=")
        user_ids = _parse_ids(ids)
        if not watcher.strip() or not user_ids:
            # Silently dropping this would route the watcher to everyone.
            log.warning("ignoring malformed JOBS_WATCHER_USERS entry: %r", entry)
            continue
        out[watcher.strip()] = user_ids
    return out


def _parse_times(raw: str) -> list[tuple[int, int]]:
    out = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        h, m = chunk.split(":")
        out.append((int(h), int(m)))
    return out


@dataclass(frozen=True)
class Settings:
    tg_bot_token: str
    tg_allowed_user_ids: tuple[int, ...]
    db_path: Path
    tz: ZoneInfo
    schedule_times: list[tuple[int, int]]
    max_pages: int
    max_age_days: int
    boards: tuple[str, ...]
    # One search profile per person the bot watches jobs for. A profile may
    # override `boards`; see scraper.search_profile.
    profiles: tuple[Path, ...]
    # Which Telegram users each watcher's jobs go to. Empty → everyone gets
    # everything (the original single-user behaviour).
    watcher_users: dict[str, tuple[int, ...]]


def load_settings() -> Settings:
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TG_BOT_TOKEN is not set in environment / .env")
    # TG_ALLOWED_USER_ID (singular) predates multi-user support; both are read
    # and merged so an existing .env keeps working.
    allowed = _parse_ids(
        ",".join(
            (
                os.environ.get("TG_ALLOWED_USER_IDS", ""),
                os.environ.get("TG_ALLOWED_USER_ID", ""),
            )
        )
    )
    return Settings(
        tg_bot_token=token,
        tg_allowed_user_ids=tuple(dict.fromkeys(allowed)),
        db_path=Path(os.environ.get("JOBS_DB_PATH", "data/jobs.db")),
        tz=ZoneInfo(os.environ.get("JOBS_TZ", "Asia/Ho_Chi_Minh")),
        schedule_times=_parse_times(os.environ.get("JOBS_SCHEDULE_TIMES", "09:00,21:00")),
        max_pages=int(os.environ.get("JOBS_MAX_PAGES", "3")),
        max_age_days=int(os.environ.get("JOBS_MAX_AGE_DAYS", "60")),
        boards=tuple(os.environ.get("JOBS_BOARDS", "web3career,remoteok,weworkremotely,linkedin").split(",")),
        profiles=_parse_paths(os.environ.get("JOBS_PROFILES", "search.toml")),
        watcher_users=_parse_watcher_users(os.environ.get("JOBS_WATCHER_USERS", "")),
    )
