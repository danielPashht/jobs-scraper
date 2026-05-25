from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime, timedelta

from bs4 import BeautifulSoup, Tag

from scraper.boards.base import Board
from scraper.models import Job

log = logging.getLogger(__name__)

BASE_URL = "https://cryptojobslist.com"
# CJL's `?search=` query is unreliable server-side, so we pull the recent feed
# and rely on the downstream keyword filter to find QA/SDET roles.
LIST_PATHS = ("/engineering", "/")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

REL_TIME_RE = re.compile(r"^(\d+)\s*(d|w|mo|m|y|h)$")
SALARY_RE = re.compile(r"\$?\d+(?:\.\d+)?\s*k\s*-\s*\$?\d+(?:\.\d+)?\s*k(?:/\w+)?", re.IGNORECASE)


def _parse_relative_time(rel: str) -> datetime | None:
    """Convert a CJL relative timestamp like '3w', '5d', '2mo' to an absolute datetime."""
    m = REL_TIME_RE.match(rel.strip().lower())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    delta = {
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
        "w": timedelta(weeks=n),
        "mo": timedelta(days=30 * n),
        "m": timedelta(days=30 * n),  # CJL uses 'mo' but be defensive
        "y": timedelta(days=365 * n),
    }.get(unit)
    return (datetime.utcnow() - delta) if delta else None


class CryptoJobsListBoard(Board):
    """Cryptojobslist scraper via Playwright + stealth (Cloudflare-protected).

    Install: `pip install -e '.[cf]'` then `playwright install chromium`.
    Browsers are cached at `$PLAYWRIGHT_BROWSERS_PATH` or `~/Library/Caches/ms-playwright`
    on macOS by default.
    """

    name = "cryptojobslist"

    def fetch(self, *, max_pages: int = 3) -> Iterable[Job]:
        # max_pages is interpreted as "how many list endpoints to walk", since CJL
        # doesn't expose a stable ?page= contract — we hit /engineering and /.
        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import stealth_sync
        except ImportError as exc:  # pragma: no cover — surfaced to the user
            log.error(
                "cryptojobslist scraper needs the 'cf' extra: pip install -e '.[cf]' "
                "(missing: %s)",
                exc.name,
            )
            return

        paths = LIST_PATHS[:max_pages]
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=UA, locale="en-US")
            page = ctx.new_page()
            stealth_sync(page)
            for path in paths:
                url = f"{BASE_URL}{path}"
                log.info("cryptojobslist fetch %s", url)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_selector("a.job-title-text", timeout=20000)
                except Exception as exc:  # noqa: BLE001
                    log.warning("cryptojobslist: %s failed (%s)", url, exc)
                    continue
                html = page.content()
                yield from self._parse_listing(html)
            browser.close()

    def _parse_listing(self, html: str) -> Iterable[Job]:
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select('tr[role="button"]')
        log.debug("cryptojobslist parsed %d rows", len(rows))
        for row in rows:
            job = self._parse_row(row)
            if job is not None:
                yield job

    def _parse_row(self, row: Tag) -> Job | None:
        title_el = row.select_one("a.job-title-text")
        company_el = row.select_one("a.job-company-name-text")
        if not (title_el and company_el):
            return None

        href = title_el.get("href", "")
        if not href:
            return None

        tags = [s.get_text(strip=True) for s in row.select("td.job-tags span.category")]

        # Salary is not in a stable selector — search the row text for a $XXk-$YYk pattern.
        row_text = row.get_text(" ", strip=True)
        salary_match = SALARY_RE.search(row_text)
        salary = salary_match.group(0) if salary_match else None

        # Location: CJL sometimes has a hidden <span> "Remote" or a 📍 prefix in the row.
        locations: list[str] = []
        for hidden in row.select("span.hidden"):
            text = hidden.get_text(strip=True)
            if text:
                locations.append(text)
        loc_match = re.search(r"📍\s*([A-Za-z][A-Za-z ,/]+?)(?=\s+(?:Full Time|Part Time|Contract|Freelance|Internship|$))", row_text)
        if loc_match:
            locations.append(loc_match.group(1).strip())

        is_remote = any(t.lower() == "remote" for t in tags) or "Remote" in locations

        posted_at = None
        time_el = row.select_one("td.job-time-since-creation")
        if time_el:
            posted_at = _parse_relative_time(time_el.get_text(strip=True))

        full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
        return Job(
            title=title_el.get_text(strip=True),
            company=company_el.get_text(strip=True),
            source=self.name,
            url=full_url,
            salary=salary,
            tags=tags,
            locations=locations,
            remote=is_remote,
            posted_at=posted_at,
        )
