from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


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
    tg_allowed_user_id: int | None
    db_path: Path
    tz: ZoneInfo
    schedule_times: list[tuple[int, int]]
    max_pages: int
    max_age_days: int
    boards: tuple[str, ...]


def load_settings() -> Settings:
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TG_BOT_TOKEN is not set in environment / .env")
    allowed_raw = os.environ.get("TG_ALLOWED_USER_ID", "").strip()
    allowed = int(allowed_raw) if allowed_raw.isdigit() else None
    return Settings(
        tg_bot_token=token,
        tg_allowed_user_id=allowed,
        db_path=Path(os.environ.get("JOBS_DB_PATH", "data/jobs.db")),
        tz=ZoneInfo(os.environ.get("JOBS_TZ", "Asia/Ho_Chi_Minh")),
        schedule_times=_parse_times(os.environ.get("JOBS_SCHEDULE_TIMES", "09:00,21:00")),
        max_pages=int(os.environ.get("JOBS_MAX_PAGES", "3")),
        max_age_days=int(os.environ.get("JOBS_MAX_AGE_DAYS", "60")),
        boards=tuple(os.environ.get("JOBS_BOARDS", "web3career,cryptojobslist").split(",")),
    )
