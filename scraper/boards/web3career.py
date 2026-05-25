from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from scraper.boards.base import Board
from scraper.models import Job

log = logging.getLogger(__name__)

BASE_URL = "https://web3.career"
# The "remote+quality-assurance" canonical form is "quality-assurance+remote-jobs".
LIST_PATH = "/quality-assurance+remote-jobs"


class Web3CareerBoard(Board):
    name = "web3career"

    def fetch(self, *, max_pages: int = 3) -> Iterable[Job]:
        for page in range(1, max_pages + 1):
            url = f"{BASE_URL}{LIST_PATH}"
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
