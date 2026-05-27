from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from scraper.boards.base import Board
from scraper.models import Job

log = logging.getLogger(__name__)

BASE_URL = "https://web3.career"
# web3.career category pages take the form "/<role-slug>+remote-jobs", e.g.
# "/quality-assurance+remote-jobs". We derive the slug from the active search's
# primary keyword; this is the default when no keywords are supplied.
DEFAULT_SLUG = "quality-assurance"


class Web3CareerBoard(Board):
    name = "web3career"

    def _list_path(self) -> str:
        slug = DEFAULT_SLUG
        if self.query_keywords:
            slug = re.sub(r"[^a-z0-9]+", "-", self.query_keywords[0].lower()).strip("-") or DEFAULT_SLUG
        return f"/{slug}+remote-jobs"

    def fetch(self, *, max_pages: int = 3) -> Iterable[Job]:
        list_path = self._list_path()
        for page in range(1, max_pages + 1):
            url = f"{BASE_URL}{list_path}"
            params = {"page": page} if page > 1 else None
            log.info("web3.career fetch page=%d", page)
            resp = self.client.get(url, params=params)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("tr.table_row")
            if not rows:
                log.info("web3.career no rows on page=%d — stopping", page)
                return

            for row in rows:
                job = self._parse_row(row)
                if job is not None:
                    yield job

            # Be polite — brief calls out a 1–2s inter-page delay.
            time.sleep(1.5)

    def _parse_row(self, row: Tag) -> Job | None:
        title_el = row.select_one("h2")
        company_el = row.select_one("h3")
        link_el = row.select_one('a[data-turbo-frame="job"]')
        if not (title_el and company_el and link_el):
            return None

        href = link_el.get("href", "")
        if not href:
            return None

        salary_el = row.select_one("p.text-salary")
        time_el = row.select_one("time")
        badges = [a.get_text(strip=True) for a in row.select("span.my-badge a")]
        locations = [a.get_text(strip=True) for a in row.select('a[href*="web3-jobs-"]')]

        posted_at: datetime | None = None
        if time_el and time_el.get("datetime"):
            try:
                posted_at = datetime.fromisoformat(time_el["datetime"])
            except ValueError:
                posted_at = None

        return Job(
            title=title_el.get_text(strip=True),
            company=company_el.get_text(strip=True),
            source=self.name,
            url=f"{BASE_URL}{href}",
            salary=salary_el.get_text(" ", strip=True) if salary_el else None,
            tags=badges,
            locations=locations,
            remote="remote" in (t.lower() for t in badges),
            posted_at=posted_at,
        )
