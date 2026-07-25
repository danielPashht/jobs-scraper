"""Which watcher's jobs go to which Telegram user.

Built once from ``Settings.watcher_users`` (the ``JOBS_WATCHER_USERS`` env var)
and stored in the bot's ``bot_data``, so the "claimed users" set is computed one
time instead of per watcher per fetch.

Rule: a watcher named in the table is pushed only to the users it names, and a
user named anywhere in the table receives only the watchers naming them. Watchers
the table doesn't name go to every subscriber it doesn't claim — so an empty
table means everyone gets everything (the original single-user behaviour).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence

from scraper.search_profile import SearchProfile

log = logging.getLogger(__name__)


class Router:
    def __init__(self, watcher_users: Mapping[str, tuple[int, ...]] | None = None) -> None:
        self._watcher_users: dict[str, frozenset[int]] = {
            watcher: frozenset(ids) for watcher, ids in (watcher_users or {}).items()
        }
        self._claimed: frozenset[int] = frozenset(
            uid for ids in self._watcher_users.values() for uid in ids
        )

    def is_recipient(self, user_id: int, watcher: str) -> bool:
        """True when `watcher`'s jobs should reach `user_id`.

        A watcher named in the routing table reaches only the users it names; a
        watcher named nowhere reaches every user the table doesn't claim. With an
        empty table every user is a recipient of every watcher.
        """
        mapped = self._watcher_users.get(watcher)
        if mapped:
            return user_id in mapped
        return user_id not in self._claimed

    def recipients(self, subscribers: Iterable[tuple[int, int]], watcher: str) -> list[int]:
        """Chat ids from (chat_id, user_id) pairs that should receive `watcher`."""
        return [
            chat_id for chat_id, user_id in subscribers if self.is_recipient(user_id, watcher)
        ]

    def watchers_for(
        self, profiles: Iterable[SearchProfile], user_id: int
    ) -> list[SearchProfile]:
        """The subset of `profiles` whose jobs `user_id` receives.

        Drives what `/start` reports and which searches a manual `/fetch` runs.
        """
        return [p for p in profiles if self.is_recipient(user_id, p.watcher)]

    def warn_on_misconfiguration(
        self, profiles: Sequence[SearchProfile], allowed_user_ids: Iterable[int]
    ) -> None:
        """Log routing entries that can never deliver — typos are otherwise silent."""
        known = {p.watcher for p in profiles}
        allowed = set(allowed_user_ids)
        for watcher, ids in self._watcher_users.items():
            if watcher not in known:
                log.warning(
                    "JOBS_WATCHER_USERS routes watcher=%r, which no loaded profile "
                    "defines (known: %s) — nothing will be sent for it",
                    watcher,
                    ",".join(sorted(known)) or "none",
                )
            for uid in sorted(ids - allowed):
                log.warning(
                    "JOBS_WATCHER_USERS routes watcher=%r to user_id=%d, which is not "
                    "in TG_ALLOWED_USER_IDS — that user can't /start, so they'll never "
                    "receive it",
                    watcher,
                    uid,
                )
