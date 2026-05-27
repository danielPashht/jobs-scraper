from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime
from email.utils import parsedate_to_datetime

from scraper.boards.base import Board
from scraper.models import Job

log = logging.getLogger(__name__)

BASE_URL = "https://weworkremotely.com"

# WWR has no dedicated QA feed, so pull the categories most likely to contain
# SDET/test-engineer roles. The pipeline's keyword filter narrows from there.
DEFAULT_CATEGORIES: tuple[str, ...] = (
    "remote-programming-jobs",
    "remote-devops-sysadmin-jobs",
    "remote-full-stack-programming-jobs",
    "remote-back-end-programming-jobs",
    "remote-front-end-programming-jobs",
)


class WeWorkRemotelyBoard(Board):
    name = "weworkremotely"

    categories: tuple[str, ...] = DEFAULT_CATEGORIES

    def fetch(self, *, max_pages: int = 3) -> Iterable[Job]:
        seen_links: set[str] = set()
        for i, category in enumerate(self.categories):
            url = f"{BASE_URL}/categories/{category}.rss"
            log.info("weworkremotely fetch category=%s", category)
            resp = self.client.get(url)
            resp.raise_for_status()

            try:
                root = ET.fromstring(resp.text)
            except ET.ParseError as exc:
                log.warning("weworkremotely RSS parse failed for %s: %s", category, exc)
                continue

            for item in root.findall(".//item"):
                link = (item.findtext("link") or "").strip()
                if not link or link in seen_links:
                    continue
                seen_links.add(link)

                job = self._parse_item(item, link)
                if job is not None:
                    yield job

            if i < len(self.categories) - 1:
                time.sleep(1.0)

    def _parse_item(self, item: ET.Element, link: str) -> Job | None:
        raw_title = (item.findtext("title") or "").strip()
        if not raw_title:
            return None

        # WWR titles are "Company: Position". Fall back to the whole string as
        # the title if the colon isn't present.
        if ": " in raw_title:
            company, _, title = raw_title.partition(": ")
            company = company.strip()
            title = title.strip()
        else:
            company = "Unknown"
            title = raw_title

        region = (item.findtext("region") or "").strip()
        category = (item.findtext("category") or "").strip()

        posted_at: datetime | None = None
        pub_date = item.findtext("pubDate")
        if pub_date:
            try:
                posted_at = parsedate_to_datetime(pub_date)
            except (TypeError, ValueError):
                posted_at = None

        return Job(
            title=title,
            company=company,
            source=self.name,
            url=link,
            salary=None,  # WWR RSS doesn't expose salary structurally
            tags=[category] if category else [],
            locations=[region] if region else [],
            remote=True,  # WWR is remote-only by definition
            posted_at=posted_at,
        )
