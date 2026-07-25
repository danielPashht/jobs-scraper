"""Telegram job channels, via the public web preview (``t.me/s/<channel>``).

Lots of Russian-language roles — especially junior PM/BA/assistant work and CIS
remote jobs — are only ever posted to Telegram channels, never to a job board.
The preview page serves the last ~20 posts as plain HTML with no auth, no API
key and no user account: title line, `✅` employer, `📍` location, `💰` salary,
a `<time datetime>` and the post's permalink in `data-post`.

Unlike the other boards, a post is free text rather than a structured listing, so
the whole body is carried on ``Job.description``; ``filters.matches`` reads it for
include keywords (the role is often only named in the text) but not for excludes.

Configured per watcher via the profile:

    [boards.telegram]
    channels = ["pm_vacancy", "product_jobs"]
    queries = ["проект"]   # optional: t.me in-channel search, on top of the feed
"""

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

PREVIEW_URL = "https://t.me/s/{channel}"
POST_URL = "https://t.me/{post}"

# Channels are polled twice a day, so be gentle and bounded.
PAGE_DELAY_SECONDS = 1.5
DEFAULT_MAX_REQUESTS = 30
MAX_TITLE_CHARS = 140

_REMOTE_HINTS = (
    "удал",  # удалённо / удаленка / удаленная работа
    "дистанц",
    "remote",
    "from anywhere",
    "wfh",
    "релокац",  # relocation offers are still workable
)

# "$2000–2500", "от 90 000 ₽", "70 000 до 200 000 руб.", "€3k"
_SALARY_PATTERNS = (
    re.compile(r"[$€]\s?\d[\d\s.,]*(?:\s?[kк])?(?:\s?[-–—]\s?[$€]?\s?\d[\d\s.,]*(?:\s?[kк])?)?"),
    re.compile(
        r"(?:от\s*)?\d[\d\s]{2,}(?:\s*(?:до|[-–—])\s*\d[\d\s]{2,})?\s*(?:₽|руб\.?|rub|тенге|₸)",
        re.IGNORECASE,
    ),
)

# Employer lines: "✅ ООО Ромашка", "Компания: Acme", "Работодатель — Acme"
_COMPANY_LABEL_RE = re.compile(
    r"^(?:компания|работодатель|employer|company)\s*[:\-—]?\s*(.+)$", re.I
)
_HASHTAG_RE = re.compile(r"#(\w+)")
_LEADING_JUNK_RE = re.compile(r"^[^\w(]+", re.UNICODE)
_URL_RE = re.compile(r"https?://\S+")
# "Вакансия: Project Manager", "Vacancy - PM", "Вакансия Руководитель проектов"
_TITLE_LABEL_RE = re.compile(r"^(?:вакансия|ваканси[яи]|vacancy|job)\s*[:\-—]?\s*", re.I)
# hh.ru link previews: "Вакансия <role> в <city>, работа в компании <employer>"
_HH_PREVIEW_RE = re.compile(
    r"^(?:вакансия\s+)?(?P<role>.+?),\s*работа в компании\s+(?P<company>.+)$", re.I
)
# Title left hanging on a preposition because a link split the line.
_DANGLING_RE = re.compile(r"\b(?:в|во|для|at|to|in|@)$", re.I)
# Leftover preposition once the "Вакансия"/"Vacancy" label is stripped.
_LEADING_CONNECTOR_RE = re.compile(r"^(?:для|на|for|of)\s+", re.I)
# Label words that are never an employer name (they precede one).
_LABEL_WORDS = frozenset({"компания", "работодатель", "employer", "company"})


class TelegramJobsBoard(Board):
    name = "telegram"

    # --- config -----------------------------------------------------------

    def _channels(self) -> tuple[str, ...]:
        raw = self.options.get("channels")
        if not isinstance(raw, (list, tuple)) or not raw:
            return ()
        # Accept "@name", a t.me link, or a bare handle.
        return tuple(
            str(c).strip().removeprefix("@").removeprefix("https://t.me/").removeprefix("s/").strip("/")
            for c in raw
            if str(c).strip()
        )

    def _queries(self) -> tuple[str | None, ...]:
        """`None` = the plain channel feed; strings use t.me's in-channel search."""
        raw = self.options.get("queries")
        if isinstance(raw, (list, tuple)) and raw:
            return (None, *(str(q) for q in raw))
        return (None,)

    def _max_requests(self) -> int:
        raw = self.options.get("max_requests", DEFAULT_MAX_REQUESTS)
        try:
            return max(1, int(raw))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            log.warning("telegram: bad max_requests=%r, using %d", raw, DEFAULT_MAX_REQUESTS)
            return DEFAULT_MAX_REQUESTS

    # --- fetch ------------------------------------------------------------

    def fetch(self, *, max_pages: int = 3) -> Iterable[Job]:
        channels = self._channels()
        if not channels:
            log.warning(
                "telegram board has no channels configured — set [boards.telegram] "
                "channels = [...] in the profile; yielding nothing"
            )
            return

        queries = self._queries()
        budget = self._max_requests()
        planned = len(channels) * len(queries) * max_pages
        if planned > budget:
            log.warning(
                "telegram: %d channel(s) × %d query/queries × %d page(s) = %d requests "
                "exceeds the max_requests budget of %d — the tail will be skipped",
                len(channels),
                len(queries),
                max_pages,
                planned,
                budget,
            )

        seen_posts: set[str] = set()
        requests_made = 0
        for channel in channels:
            for query in queries:
                before: str | None = None
                for page in range(max_pages):
                    if requests_made >= budget:
                        return
                    params: dict[str, str] = {}
                    if query:
                        params["q"] = query
                    if before:
                        params["before"] = before
                    log.info(
                        "telegram fetch channel=%s query=%s page=%d",
                        channel,
                        query or "(feed)",
                        page + 1,
                    )
                    if requests_made:
                        time.sleep(PAGE_DELAY_SECONDS)
                    requests_made += 1
                    resp = self.client.get(PREVIEW_URL.format(channel=channel), params=params)
                    if resp.status_code == 404:
                        log.warning("telegram channel not found or private: %s", channel)
                        break
                    resp.raise_for_status()

                    messages = BeautifulSoup(resp.text, "html.parser").select(
                        "div.tgme_widget_message[data-post]"
                    )
                    if not messages:
                        log.info("telegram channel=%s page=%d had no posts", channel, page + 1)
                        break

                    for message in messages:
                        post_id = message.get("data-post", "")
                        if not post_id or post_id in seen_posts:
                            continue
                        seen_posts.add(post_id)
                        job = self._parse_message(message, channel, post_id)
                        if job is not None:
                            yield job

                    # The preview lists oldest→newest, so the first post is the
                    # cursor for the next (older) page.
                    oldest = messages[0].get("data-post", "").rsplit("/", 1)[-1]
                    if not oldest.isdigit():
                        break
                    before = oldest

    # --- parsing ----------------------------------------------------------

    def _parse_message(self, message: Tag, channel: str, post_id: str) -> Job | None:
        text_el = message.select_one(".tgme_widget_message_text")
        body = text_el.get_text("\n", strip=True) if text_el else ""
        lines = [line.strip() for line in body.split("\n") if line.strip()]
        preview = self._preview(message)

        # Some channels (e.g. @pm_vacancy) post nothing but a link, and the role
        # lives only in Telegram's link preview — which for hh.ru links carries
        # the title, salary and city we'd otherwise have no access to.
        title = self._title(lines) or self._title_from_preview(preview)
        if not title:
            return None  # media-only or link-less post, nothing to match on

        haystack = "\n".join(filter(None, (body, preview.get("title"), preview.get("description"))))
        link_only = bool(preview.get("href")) and not self._title(lines)

        return Job(
            title=title,
            company=(
                self._company(lines) or self._company_from_preview(preview) or f"@{channel}"
            ),
            source=self.name,
            url=preview["href"] if link_only else POST_URL.format(post=post_id),
            salary=self._salary(haystack),
            tags=self._tags(haystack),
            locations=self._locations(lines),
            remote=self._is_remote(haystack),
            posted_at=self._posted_at(message),
            description=haystack,
        )

    @staticmethod
    def _preview(message: Tag) -> dict[str, str]:
        """Telegram's link-preview card for a post, as a dict.

        Keys, all optional because Telegram renders whichever parts the target
        page exposed: ``href`` (the linked page — present whenever a preview
        exists), ``site``, ``title``, ``description``. Returns an empty dict when
        the post has no preview, so callers must not index blindly.
        """
        block = message.select_one(".tgme_widget_message_link_preview")
        if block is None:
            return {}
        out = {"href": (block.get("href") or "").strip()}
        for key, cls in (
            ("site", "link_preview_site_name"),
            ("title", "link_preview_title"),
            ("description", "link_preview_description"),
        ):
            el = block.select_one(f".{cls}")
            if el:
                out[key] = el.get_text(" ", strip=True)
        return out

    @classmethod
    def _title(cls, lines: list[str]) -> str | None:
        """First line that reads like a role — emoji, hashtags and URLs stripped."""
        for i, line in enumerate(lines[:4]):
            cleaned = cls._clean_title(line)
            if len(re.findall(r"\w", cleaned)) < 3:
                continue
            # A link inside the title splits the line, leaving "Role в" with the
            # employer on the next line ("… (Commercial) в" / "OrcaBio").
            if _DANGLING_RE.search(cleaned) and i + 1 < len(lines):
                cleaned = f"{cleaned} {cls._clean_title(lines[i + 1])}".strip()
            return cleaned[:MAX_TITLE_CHARS]
        return None

    @classmethod
    def _title_from_preview(cls, preview: dict[str, str]) -> str | None:
        raw = preview.get("title")
        if not raw:
            return None
        hh = _HH_PREVIEW_RE.match(raw)
        role = hh.group("role") if hh else raw
        cleaned = cls._clean_title(role)
        return cleaned[:MAX_TITLE_CHARS] if cleaned else None

    @staticmethod
    def _clean_title(line: str) -> str:
        no_urls = _URL_RE.sub("", line)
        no_tags = _HASHTAG_RE.sub("", no_urls)
        stripped = _LEADING_JUNK_RE.sub("", no_tags).strip(" -—–:•|")
        labelled = _TITLE_LABEL_RE.sub("", stripped)
        # "Вакансия для Project Manager" → "Project Manager"
        labelled = _LEADING_CONNECTOR_RE.sub("", labelled)
        return re.sub(r"\s{2,}", " ", labelled).strip(" -—–:•|")

    @classmethod
    def _company(cls, lines: list[str]) -> str | None:
        for i, line in enumerate(lines):
            labelled = _COMPANY_LABEL_RE.match(_LEADING_JUNK_RE.sub("", line))
            if labelled:
                # Either "Компания: Acme", or the label alone with the name on a
                # following line — sometimes behind a second label
                # ("Работодатель:" / "Компания" / "ROX PRO").
                value = cls._first_named_value(
                    [labelled.group(1), *lines[i + 1 : i + 3]]
                )
                if value:
                    return value
            # "✅" on its own line marks the employer on the line that follows.
            if line == "✅":
                value = cls._first_named_value(lines[i + 1 : i + 3])
                if value:
                    return value
        return None

    @staticmethod
    def _first_named_value(candidates: list[str]) -> str | None:
        """First candidate that carries a real name — label words don't count."""
        for candidate in candidates:
            value = candidate.strip(" :—-")
            if value.lower().rstrip(":") in _LABEL_WORDS:
                continue
            if re.search(r"\w", value):
                return value[:MAX_TITLE_CHARS]
        return None

    @staticmethod
    def _company_from_preview(preview: dict[str, str]) -> str | None:
        hh = _HH_PREVIEW_RE.match(preview.get("title", ""))
        return hh.group("company").strip()[:MAX_TITLE_CHARS] if hh else None

    @staticmethod
    def _salary(body: str) -> str | None:
        for pattern in _SALARY_PATTERNS:
            found = pattern.search(body)
            if found:
                return re.sub(r"\s+", " ", found.group(0)).strip()
        return None

    @staticmethod
    def _tags(body: str) -> list[str]:
        tags = [tag.lower() for tag in _HASHTAG_RE.findall(body)]
        if TelegramJobsBoard._is_remote(body):
            tags.append("remote")
        return tags

    @staticmethod
    def _locations(lines: list[str]) -> list[str]:
        for i, line in enumerate(lines):
            if not line.startswith("📍"):
                continue
            rest = line.removeprefix("📍").strip(" :—-")
            if rest:
                return [rest]
            if i + 1 < len(lines):  # emoji alone on its line
                return [lines[i + 1]]
        return []

    @staticmethod
    def _is_remote(body: str) -> bool:
        low = body.lower()
        return any(hint in low for hint in _REMOTE_HINTS)

    @staticmethod
    def _posted_at(message: Tag) -> datetime | None:
        time_el = message.select_one("time[datetime]")
        if time_el is None:
            return None
        try:
            return datetime.fromisoformat(time_el["datetime"])
        except (ValueError, KeyError):
            return None
