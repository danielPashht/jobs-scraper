from __future__ import annotations

import asyncio

import pytest

from scraper import bot as bot_module
from scraper.config import _parse_watcher_users
from scraper.routing import Router
from scraper.search_profile import SearchProfile

DANIEL = (111, 111)  # (chat_id, user_id)
ANASTASIA = (222, 222)
SUBS = [DANIEL, ANASTASIA]

PROFILES = [
    SearchProfile(),  # watcher="default"
    SearchProfile(watcher="anastasia", role="BD"),
]


def test_parse_watcher_users():
    assert _parse_watcher_users("anastasia=222") == {"anastasia": (222,)}
    assert _parse_watcher_users("a=1,2; b = 3 ;junk;=4;c=") == {"a": (1, 2), "b": (3,)}
    assert _parse_watcher_users("") == {}


def test_no_routing_table_sends_everything_to_everyone():
    r = Router()
    assert r.recipients(SUBS, "default") == [111, 222]
    assert r.recipients(SUBS, "anastasia") == [111, 222]


def test_claimed_watcher_goes_only_to_its_users():
    r = Router({"anastasia": (222,)})
    assert r.recipients(SUBS, "anastasia") == [222]


def test_claimed_user_is_excluded_from_unclaimed_watchers():
    r = Router({"anastasia": (222,)})
    # Daniel keeps the unrouted 'default' feed; Anastasia does not get it.
    assert r.recipients(SUBS, "default") == [111]


def test_watcher_can_be_routed_to_several_users():
    r = Router({"anastasia": (222, 111)})
    assert r.recipients(SUBS, "anastasia") == [111, 222]
    # Both users are claimed now, so nobody receives the unrouted watcher.
    assert r.recipients(SUBS, "default") == []


def test_watchers_for_splits_the_two_feeds():
    r = Router({"anastasia": (222,)})
    assert [p.watcher for p in r.watchers_for(PROFILES, 111)] == ["default"]
    assert [p.watcher for p in r.watchers_for(PROFILES, 222)] == ["anastasia"]


def test_warn_on_misconfiguration(caplog):
    r = Router({"typo": (222,), "anastasia": (999,)})
    with caplog.at_level("WARNING"):
        r.warn_on_misconfiguration(PROFILES, [111, 222])
    messages = " ".join(rec.getMessage() for rec in caplog.records)
    assert "watcher='typo'" in messages  # no profile defines it
    assert "user_id=999" in messages  # not on the allowlist


class _FakeApp:
    def __init__(self, bot_data):
        self.bot_data = bot_data


class _FakeContext:
    def __init__(self, bot_data):
        self.application = _FakeApp(bot_data)


def test_run_and_report_runs_only_the_requesting_users_watchers(monkeypatch):
    """A manual /fetch must not run — or consume the dedup state of — other feeds."""
    ran: list[str] = []

    async def fake_run_one(context, chat_ids, profile):
        ran.append(profile.watcher)

    monkeypatch.setattr(bot_module, "_run_one_profile", fake_run_one)
    monkeypatch.setattr(bot_module, "WATCHER_GAP_SEC", 0)
    ctx = _FakeContext(
        {"profiles": PROFILES, "router": Router({"anastasia": (222,)})}
    )

    asyncio.run(bot_module._run_and_report(ctx, [ANASTASIA]))
    assert ran == ["anastasia"]

    ran.clear()
    asyncio.run(bot_module._run_and_report(ctx, [DANIEL]))
    assert ran == ["default"]


def test_run_and_report_staggers_multiple_watchers(monkeypatch):
    """Two watchers in one run must not hit the same boards back to back."""
    sleeps: list[float] = []

    async def fake_run_one(context, chat_ids, profile):
        return None

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(bot_module, "_run_one_profile", fake_run_one)
    monkeypatch.setattr(bot_module.asyncio, "sleep", fake_sleep)
    ctx = _FakeContext({"profiles": PROFILES, "router": Router()})

    asyncio.run(bot_module._run_and_report(ctx, SUBS))
    # One gap between the two watchers — none before the first.
    assert sleeps == [bot_module.WATCHER_GAP_SEC]


@pytest.mark.parametrize("subscribers", [[], [(333, 333)]])
def test_run_and_report_skips_watchers_without_recipients(monkeypatch, subscribers):
    ran: list[str] = []

    async def fake_run_one(context, chat_ids, profile):
        ran.append(profile.watcher)

    monkeypatch.setattr(bot_module, "_run_one_profile", fake_run_one)
    monkeypatch.setattr(bot_module, "WATCHER_GAP_SEC", 0)
    # Every watcher is claimed by users who aren't subscribed here.
    ctx = _FakeContext(
        {
            "profiles": PROFILES,
            "router": Router({"default": (111,), "anastasia": (222,)}),
        }
    )
    asyncio.run(bot_module._run_and_report(ctx, subscribers))
    assert ran == []
