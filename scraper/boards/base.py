from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

import httpx

from scraper.models import Job

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class Board(ABC):
    name: str
    """Short identifier used on the CLI (e.g. 'web3career')."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        keywords: Iterable[str] | None = None,
    ) -> None:
        # The active search's include keywords. Boards that need a server-side
        # query (LinkedIn) or a path slug (web3.career) derive it from these;
        # broad-feed boards ignore them and let the pipeline filter narrow.
        self.query_keywords: tuple[str, ...] = tuple(keywords) if keywords else ()
        self.client = client or httpx.Client(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=30.0,
        )

    @abstractmethod
    def fetch(self, *, max_pages: int = 3) -> Iterable[Job]:
        """Yield Job records from the board."""

    def close(self) -> None:
        self.client.close()
