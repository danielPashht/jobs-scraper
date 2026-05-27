from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from datetime import datetime

from scraper.boards.base import Board
from scraper.models import Job

log = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"

# RemoteOK is a general remote board across all industries. We pull the
# tag-filtered slices most likely to contain SDET/QA roles — the pipeline's
# keyword filter narrows further regardless of industry (web3, fintech, SaaS,
# anything). Dedup across slices happens via the job id.
DEFAULT_TAGS: tuple[str, ...] = ("qa", "testing")


class RemoteOKBoard(Board):
    name = "remoteok"

    # API returns the full set per tag in one response; `max_pages` is accepted
    # for interface compatibility but is not used for pagination here.
    tags: tuple[str, ...] = DEFAULT_TAGS

    def fetch(self, *, max_pages: int = 3) -> Iterable[Job]:
        seen_ids: set[str] = set()
        for i, tag in enumerate(self.tags):
            log.info("remoteok fetch tag=%s", tag)
            resp = self.client.get(API_URL, params={"tags": tag})
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

            if i < len(self.tags) - 1:
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
