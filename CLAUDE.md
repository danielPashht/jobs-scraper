# jobs-scraper — Claude notes

CLI + Telegram bot that scrapes **remote job boards across all industries** (web3, fintech, SaaS, anything) for **a configurable technical role**, filters by keyword, dedupes across sources, ranks preferred locations first, and pushes new listings to Telegram.

> ⚠️ Scope: the project is **not** restricted to crypto/web3/fintech, nor to QA. *What* it searches for lives in `search.toml` (see `scraper/search_profile.py` + `search.example.toml`) — role keywords + location eligibility. The shipped **default** profile is SDET / Automation QA for an Asia-based-open-to-Europe user, used when no `search.toml` exists. The `/setup-search` skill (`.claude/skills/setup-search/`) interviews a new user and writes their profile. When adding boards, prefer general-purpose remote boards and keep them role-agnostic.

## Layout

```
scraper/
  cli.py            # `python -m scraper.cli` — one-shot terminal/CSV/JSON output
  bot.py            # `python -m scraper.bot` — long-running Telegram bot (APScheduler)
  pipeline.py       # scrape → filter → dedup → rank
  filters.py        # keyword include/exclude, location eligibility, ranking, age cutoff (all parameterized; defaults = SDET/Asia)
  search_profile.py # SearchProfile dataclass + load_profile() — reads search.toml (what to search for)
  models.py         # pydantic `Job` (dedup key = sha1(title|company))
  config.py         # env-driven Settings dataclass — secrets/ops only (TG_*, JOBS_*)
  db.py             # SQLite dedup store for the bot
  output.py         # rich table / CSV / JSON writers
  boards/
    base.py         # abstract Board(client, *, keywords) → Iterable[Job]
    web3career.py   # static HTML, paginated; slug derived from keywords
    remoteok.com    # JSON API, broad recent feed (tags optional)
    weworkremotely  # all-jobs RSS feed (categories optional), stdlib xml.etree
    linkedin.py     # public guest jobs endpoint, boolean query OR-ed from keywords, 429 backoff
    cryptojobslist  # STUB — needs Playwright + stealth (Cloudflare)
search.example.toml # committed template for search.toml (gitignored local profile)
.claude/skills/setup-search/  # onboarding skill: interviews a new user → writes search.toml + .env
scripts/
  run-bot.sh        # foreground or --detach (caffeinate + nohup + pidfile)
  stop-bot.sh       # kills via logs/bot.pid
tests/              # pytest, no live HTTP
data/jobs.db        # SQLite dedup state (gitignored)
logs/bot.log        # bot output (gitignored)
```

## Adding a board

Subclass `scraper.boards.base.Board`, implement `fetch(max_pages: int) -> Iterable[Job]`, register in `scraper/boards/__init__.py::ALL_BOARDS`. The `self.client` is a configured `httpx.Client` with a desktop UA. If a site needs JS/anti-bot bypass, follow the Playwright path sketched in `cryptojobslist.py`.

Each yielded `Job` runs through the same filter+rank pipeline — boards do **not** need to filter by keyword themselves. Just yield broadly; the pipeline narrows. Boards that need a server-side query receive the active search's include keywords via `Board.__init__(..., keywords=...)` (set `self.query_keywords`): LinkedIn ORs them into its `keywords` param, web3.career slugifies the first one. Broad-feed boards (RemoteOK, WWR) ignore them.

For pagination, use `max_pages`. For API-based boards (RemoteOK), it's fine to ignore it; the parameter exists for interface compatibility.

## Search profile & filters

*What* to search for is a `SearchProfile` (`scraper/search_profile.py`), loaded from `search.toml` (gitignored) or built-in defaults when absent. `cli.py` and `bot.py` both load it and thread its fields into `run_pipeline`. The filter/rank functions in `scraper/filters.py` are all **parameterized** with these values; the module-level `DEFAULT_*` constants are the fallback defaults (and what the offline tests assert against).

Profile → pipeline mapping:
- `include_keywords` / `exclude_keywords` → `filter_jobs(include=, exclude=)`; `include_keywords` also feeds the boards (LinkedIn query, web3.career slug).
- `[eligibility]` `eligible_regions` / `blocked_regions` / `block_us_states` → `is_eligible(...)`. A listing is kept on any eligible-region token; else dropped on a blocked-region token (or a US `City, ST` code via `_US_STATE_RE` when `block_us_states`); ambiguous (no signal) → kept. `enabled=false` → skip eligibility filtering.
- `prioritize` → `rank(prioritize=)` / `is_prioritized()` — tokens that float to the top. `is_apac_friendly()` is a back-compat alias for the default.
- **Age cutoff** (`JOBS_MAX_AGE_DAYS`, default 60) stays in `.env`, not the profile; unknown `posted_at` is treated as recent.

The shipped defaults reproduce the original behaviour: SDET/QA keywords, Asia-based-open-to-Europe eligibility, APAC/remote prioritized. To change the search, edit `search.toml` (or run `/setup-search`) — **don't** hardcode role/region assumptions back into `filters.py`.

## Bot

`python -m scraper.bot` runs a long-poll Telegram bot via `python-telegram-bot`. Schedule is two daily fetches in Asia/Ho_Chi_Minh; `data/jobs.db` tracks already-reported job IDs so the same listing isn't pushed twice. Only `TG_ALLOWED_USER_ID` can talk to it.

Required env (`.env`): `TG_BOT_TOKEN`, `TG_ALLOWED_USER_ID`. Optional: `JOBS_BOARDS`, `JOBS_MAX_PAGES`, `JOBS_MAX_AGE_DAYS`, `JOBS_SCHEDULE_TIMES`, `JOBS_TZ`, `JOBS_DB_PATH`. The search role/keywords/eligibility live in `search.toml`, loaded once at startup into `bot_data["profile"]`; restart the bot after editing it.

**Restarting the bot:** `./scripts/stop-bot.sh && sleep 8 && ./scripts/run-bot.sh --detach`. The 8s gap matters — Telegram's long-poll on the previous process can take several seconds to release server-side, otherwise the new instance gets `telegram.error.Conflict: terminated by other getUpdates request` and exits. If you see that error, kill cleanly, wait, restart.

## Tests

`pytest` — 42 tests, all offline. Cover filter matching, exclude rules, dedup, prioritization/ranking, age cutoff, parameterized eligibility, and `search.toml` loading (`tests/test_search_profile.py`). **HTTP layer is intentionally not unit-tested.** Verify board changes by running the CLI against the live site, e.g.

```bash
.venv/bin/python -m scraper.cli --boards remoteok --max-pages 1
```

## Conventions

- Python 3.11+, `from __future__ import annotations`, pydantic for the `Job` model, `httpx.Client` (sync) for HTTP, BeautifulSoup or stdlib `xml.etree` for parsing.
- Keep boards small (~40–80 lines). One file per source.
- Don't add board-level keyword filtering — that's the pipeline's job. Boards yield broadly; let `filter_jobs` narrow. **Exception:** sources with no "fetch everything" mode (LinkedIn's guest endpoint *requires* a `keywords` query) pass a query server-side; that's a source param, not post-filtering, and the pipeline still narrows on top.
- Don't add board-level deduplication across boards — that's `deduplicate()`'s job. But it's fine to dedupe *within* a board (e.g. across tag slices) by source-native ID.
- Use `log = logging.getLogger(__name__)` per module. The CLI/bot wire up the handler.

## Known stubs / next up

- `cryptojobslist.com` — needs Playwright + stealth (Cloudflare). Wiring sketch lives in `scraper/boards/cryptojobslist.py`.
- `himalayas.app` and `wellfound.com` — listed as future additions in the README.
- `launchd` plist so the bot survives reboot — currently has to be re-launched manually with `run-bot.sh --detach` after a Mac restart.
