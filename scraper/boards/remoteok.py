from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from datetime import datetime

from scraper.boards.base import Board
from scraper.models import Job

log = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"

# RemoteOK is a general remote board across all industries. By default we pull
# its full recent feed and let the pipeline's keyword filter narrow it to the
# active role — that keeps the board role-agnostic. Set `tags` to fetch specific
# tag slices instead (each tag is one extra request, deduped by job id).
DEFAULT_TAGS: tuple[str, ...] = ()


class RemoteOKBoard(Board):
    name = "remoteok"

    # API returns the full set per request; `max_pages` is accepted for
    # interface compatibility but is not used for pagination here.
    tags: tuple[str, ...] = DEFAULT_TAGS

    def fetch(self, *, max_pages: int = 3) -> Iterable[Job]:
        # Empty tags → one call to the broad feed; otherwise one call per tag.
        slices: tuple[str | None, ...] = self.tags or (None,)
        seen_ids: set[str] = set()
        for i, tag in enumerate(slices):
            log.info("remoteok fetch tag=%s", tag or "(all)")
            params = {"tags": tag} if tag else None
            resp = self.client.get(API_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()

            for entry in payload:
                # First element is the API ToS disclaimer — has no "position".
                if not isinstance(entry, dict) or "position" not in entry:
                    continue
                job_id = str(entry.get("id") or entry.get("slug") or "")
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                job = self._parse_entry(entry)
                if job is not None:
                    yield job

            if i < len(slices) - 1:
                time.sleep(1.0)

    def _parse_entry(self, entry: dict) -> Job | None:
        title = (entry.get("position") or "").strip()
        company = (entry.get("company") or "").strip()
        url = entry.get("url") or entry.get("apply_url")
        if not (title and company and url):
            return None

        posted_at: datetime | None = None
        date_str = entry.get("date")
        if isinstance(date_str, str):
            try:
                posted_at = datetime.fromisoformat(date_str)
            except ValueError:
                posted_at = None

        tags = [str(t) for t in (entry.get("tags") or []) if t]

        location_raw = entry.get("location")
        locations = [location_raw.strip()] if isinstance(location_raw, str) and location_raw.strip() else []

        salary: str | None = None
        smin = entry.get("salary_min") or 0
        smax = entry.get("salary_max") or 0
        if smin and smax:
            salary = f"${int(smin):,} – ${int(smax):,}"
        elif smin:
            salary = f"from ${int(smin):,}"
        elif smax:
            salary = f"up to ${int(smax):,}"

        return Job(
            title=title,
            company=company,
            source=self.name,
            url=url,
            salary=salary,
            tags=tags,
            locations=locations,
            remote=True,  # RemoteOK is remote-only by definition
            posted_at=posted_at,
        )
