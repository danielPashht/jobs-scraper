from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from scraper.boards.base import Board
from scraper.models import Job

log = logging.getLogger(__name__)

# LinkedIn's public "guest" jobs endpoint — no auth, returns HTML <li> job
# cards, 25 per page, paginated via the `start` offset. This is the same shape
# as our other boards (plain httpx + BeautifulSoup); we deliberately avoid the
# authenticated Voyager API, which would put a real account at ban risk.
SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
PAGE_SIZE = 25

# NOTE: unlike other boards, LinkedIn has no "fetch everything" mode — the guest
# endpoint *requires* a keywords query. So the query is a source-side parameter
# (like RemoteOK's tag slices), not board-level post-filtering. The pipeline's
# keyword filter still runs on top and narrows further.
#
# The query is derived from the active search's include keywords (OR-ed
# together, since LinkedIn's `keywords` field supports boolean operators). This
# fallback is only used when the board is constructed without keywords.
DEFAULT_KEYWORDS = (
    '("SDET" OR "QA" OR "AQA" OR "Automation QA" OR "Test Engineer" '
    'OR "Quality Assurance")'
)

# "Worldwide" + f_WT=2 (remote) keeps results remote-friendly; the pipeline's
# APAC ranking + remote-only filter take it from there.
DEFAULT_LOCATION = "Worldwide"

# NOTE: a Cyrillic query against location=Worldwide comes back empty — LinkedIn
# only serves non-English queries when the search is pinned to a country. So a
# watcher hunting Russian-language roles sets `[boards.linkedin] locations` in
# its profile (e.g. ["Kazakhstan", "Cyprus"]) and we sweep them one by one.
DEFAULT_MAX_REQUESTS = 12

# LinkedIn throttles this endpoint aggressively (429s after relatively few
# requests from one IP), so we sleep longer between pages than the other boards.
PAGE_DELAY_SECONDS = 3.0
RATE_LIMIT_BACKOFF_SECONDS = 20.0


class LinkedInBoard(Board):
    name = "linkedin"

    location: str = DEFAULT_LOCATION

    def _keywords_query(self) -> str:
        """OR the active search's include keywords into a LinkedIn boolean query."""
        if not self.query_keywords:
            return DEFAULT_KEYWORDS
        return " OR ".join(f'"{kw}"' for kw in self.query_keywords)

    def _locations(self) -> tuple[str, ...]:
        raw = self.options.get("locations")
        if isinstance(raw, (list, tuple)) and raw:
            return tuple(str(loc) for loc in raw)
        return (self.location,)

    def _max_requests(self) -> int:
        raw = self.options.get("max_requests", DEFAULT_MAX_REQUESTS)
        try:
            return max(1, int(raw))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            log.warning("linkedin: bad max_requests=%r, using %d", raw, DEFAULT_MAX_REQUESTS)
            return DEFAULT_MAX_REQUESTS

    def fetch(self, *, max_pages: int = 3) -> Iterable[Job]:
        query = self._keywords_query()
        locations = self._locations()
        budget = self._max_requests()
        planned = len(locations) * max_pages
        if planned > budget:
            # This endpoint 429s on bursts from one IP; never silently over-fetch,
            # and never silently under-report the cut either.
            log.warning(
                "linkedin: %d location(s) × %d page(s) = %d requests exceeds the "
                "max_requests budget of %d — later pages/locations will be skipped",
                len(locations),
                max_pages,
                planned,
                budget,
            )
        # Deduped across locations: country searches overlap heavily on
        # remote-anywhere postings.
        seen_ids: set[str] = set()
        requests_made = 0
        for location in locations:
            for page in range(max_pages):
                if requests_made >= budget:
                    return
                params = {
                    "keywords": query,
                    "location": location,
                    "f_WT": "2",  # remote
                    "start": page * PAGE_SIZE,
                }
                log.info(
                    "linkedin fetch location=%s page=%d start=%d",
                    location,
                    page + 1,
                    page * PAGE_SIZE,
                )
                if requests_made:
                    time.sleep(PAGE_DELAY_SECONDS)
                requests_made += 1
                resp = self.client.get(SEARCH_URL, params=params)

                if resp.status_code == 429:
                    # Backed off once; if it persists, stop rather than hammer.
                    log.warning(
                        "linkedin rate-limited (429), backing off %.0fs",
                        RATE_LIMIT_BACKOFF_SECONDS,
                    )
                    time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
                    resp = self.client.get(SEARCH_URL, params=params)
                    if resp.status_code == 429:
                        log.warning("linkedin still rate-limited after backoff — stopping")
                        return
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.select("li")
                if not cards:
                    log.info(
                        "linkedin no cards for location=%s page=%d — next location",
                        location,
                        page + 1,
                    )
                    break

                yielded = 0
                for card in cards:
                    job_id, job = self._parse_card(card)
                    if job is None:
                        continue
                    if job_id and job_id in seen_ids:
                        continue
                    if job_id:
                        seen_ids.add(job_id)
                    yielded += 1
                    yield job

                # A short page with no parseable cards means this location is done.
                if yielded == 0:
                    log.info(
                        "linkedin location=%s page=%d had no parseable jobs — next location",
                        location,
                        page + 1,
                    )
                    break

    def _parse_card(self, card: Tag) -> tuple[str | None, Job | None]:
        title_el = card.select_one(".base-search-card__title")
        company_el = card.select_one(".base-search-card__subtitle")
        link_el = card.select_one("a.base-card__full-link") or card.select_one("a[href*='/jobs/view/']")
        if not (title_el and company_el and link_el):
            return None, None

        href = (link_el.get("href") or "").split("?")[0].strip()
        if not href:
            return None, None

        # Stable id from the data-entity-urn (urn:li:jobPosting:<id>) when present.
        urn_el = card.select_one("[data-entity-urn]")
        job_id: str | None = None
        if urn_el:
            urn = urn_el.get("data-entity-urn", "")
            job_id = urn.rsplit(":", 1)[-1] or None
        if not job_id:
            job_id = href.rstrip("/").rsplit("/", 1)[-1] or None

        location_el = card.select_one(".job-search-card__location")
        salary_el = card.select_one(".job-search-card__salary-info")

        posted_at: datetime | None = None
        time_el = card.select_one("time")
        if time_el and time_el.get("datetime"):
            try:
                posted_at = datetime.fromisoformat(time_el["datetime"])
            except ValueError:
                posted_at = None

        location = location_el.get_text(strip=True) if location_el else ""

        return job_id, Job(
            title=title_el.get_text(strip=True),
            company=company_el.get_text(strip=True),
            source=self.name,
            url=href,
            salary=salary_el.get_text(" ", strip=True) if salary_el else None,
            tags=[],
            locations=[location] if location else [],
            remote=True,  # f_WT=2 restricts the query to remote roles
            posted_at=posted_at,
        )
