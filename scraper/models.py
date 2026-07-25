from __future__ import annotations

from datetime import datetime
from hashlib import sha1

from pydantic import BaseModel, Field, HttpUrl


class Job(BaseModel):
    title: str
    company: str
    source: str
    url: HttpUrl
    salary: str | None = None
    tags: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote: bool = False
    # Full ad text, when the source gives one (Telegram posts are whole ads).
    # Include-keyword matching reads it; exclude matching deliberately does not
    # — see scraper.filters.matches.
    description: str | None = None
    posted_at: datetime | None = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    def dedup_key(self) -> str:
        raw = f"{self.title.strip().lower()}|{self.company.strip().lower()}"
        return sha1(raw.encode("utf-8")).hexdigest()
