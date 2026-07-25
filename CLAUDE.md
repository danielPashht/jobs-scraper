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
  search_profile.py # SearchProfile + load_profile()/load_profiles() — reads search.toml (what to search for)
  models.py         # pydantic `Job` (dedup key = sha1(title|company))
  config.py         # env-driven Settings dataclass — secrets/ops only (TG_*, JOBS_*)
  db.py             # SQLite dedup store for the bot, keyed per watcher
  routing.py        # Router — which watcher's jobs reach which Telegram user (JOBS_WATCHER_USERS)
  output.py         # rich table / CSV / JSON writers
  boards/
    base.py         # abstract Board(client, *, keywords) → Iterable[Job]
    web3career.py   # static HTML, paginated; slug derived from keywords
    remoteok.com    # JSON API, broad recent feed (tags optional)
    weworkremotely  # all-jobs RSS feed (categories optional), stdlib xml.etree
    linkedin.py     # public guest jobs endpoint, boolean query OR-ed from keywords, per-profile
                    # locations (a Cyrillic query needs a country), 429 backoff + request budget
    telegramjobs.py # t.me/s/<channel> web preview, no auth. Free-text ads → Job.description;
                    # link-only posts fall back to Telegram's link preview (hh.ru mirrors)
    cryptojobslist  # STUB — needs Playwright + stealth (Cloudflare)
search.example.toml # committed template for search.toml (gitignored local profile)
profiles/           # one profile per extra watched person (*.toml gitignored; README committed)
.claude/skills/setup-search/  # onboarding skill: interviews a new user → writes search.toml + .env
                              # (+ "Adding another watcher" questionnaire for profiles/)
scripts/
  run-bot.sh        # foreground or --detach (caffeinate + nohup + pidfile)
  stop-bot.sh       # kills via logs/bot.pid
tests/              # pytest, no live HTTP
data/jobs.db        # SQLite dedup state (gitignored)
logs/bot.log        # bot output (gitignored)
```

## Adding a board

Subclass `scraper.boards.base.Board`, implement `fetch(max_pages: int) -> Iterable[Job]`, register in `scraper/boards/__init__.py::ALL_BOARDS`. The `self.client` is a configured `httpx.Client` with a desktop UA. If a site needs JS/anti-bot bypass, follow the Playwright path sketched in `cryptojobslist.py`.

Boards that need source-side settings read them from `self.options`, which comes from the profile's `[boards.<name>]` table (`SearchProfile.board_options` → `run_pipeline(board_options=)` → `scrape()`): LinkedIn's `locations`/`max_requests`, Telegram's `channels`/`queries`/`max_requests`. Same convention as `keywords` — boards that need none ignore it. Don't add env vars for per-board settings.

Each yielded `Job` runs through the same filter+rank pipeline — boards do **not** need to filter by keyword themselves. Just yield broadly; the pipeline narrows. Boards that need a server-side query receive the active search's include keywords via `Board.__init__(..., keywords=...)` (set `self.query_keywords`): LinkedIn ORs them into its `keywords` param, web3.career slugifies the first one. Broad-feed boards (RemoteOK, WWR) ignore them.

For pagination, use `max_pages`. For API-based boards (RemoteOK), it's fine to ignore it; the parameter exists for interface compatibility.

## Search profile & filters

*What* to search for is a `SearchProfile` (`scraper/search_profile.py`), loaded from `search.toml` (gitignored) or built-in defaults when absent. `cli.py` and `bot.py` both load it and thread its fields into `run_pipeline`. The filter/rank functions in `scraper/filters.py` are all **parameterized** with these values; the module-level `DEFAULT_*` constants are the fallback defaults (and what the offline tests assert against).

Profile → pipeline mapping:
- `include_keywords` / `exclude_keywords` → `filter_jobs(include=, exclude=)`; `include_keywords` also feeds the boards (LinkedIn query, web3.career slug).
- `[eligibility]` `eligible_regions` / `blocked_regions` / `block_us_states` → `is_eligible(...)`. A listing is kept on any eligible-region token; else dropped on a blocked-region token (or a US `City, ST` code via `_US_STATE_RE` when `block_us_states`); ambiguous (no signal) → kept. `enabled=false` → skip eligibility filtering.
- `prioritize` → `rank(prioritize=)` / `is_prioritized()` — tokens that float to the top. `is_apac_friendly()` is a back-compat alias for the default.
- **Age cutoff** (`JOBS_MAX_AGE_DAYS`, default 60) stays in `.env`, not the profile; unknown `posted_at` is treated as recent.

### Multiple watchers

The bot can watch jobs for several people. `JOBS_PROFILES` (`.env`, default
`search.toml`) lists one profile file per person; `load_profiles()` returns one
`SearchProfile` each and drops duplicate `watcher` keys. Extra people's profiles
live in `profiles/*.toml` (gitignored; `profiles/README.md` is committed).

Two `[search]` keys are watcher-specific:
- `watcher` — dedup namespace in `data/jobs.db` **and** the label on that
  person's Telegram results (`SearchProfile.display_name`). Omitted →
  `"default"`, which is where all pre-multi-watcher history was migrated.
- `boards` — board subset for this watcher, overriding `JOBS_BOARDS` / `--boards`
  (e.g. `["linkedin"]`). Empty → the ops default.

`bot.py` runs one pipeline per profile (`_run_one_profile`); a failure in one
watcher's run is reported and the next still runs. `Repo.filter_new` /
`mark_reported` / `count_reported` all take a `watcher` argument, and
`reported_jobs` is keyed `(watcher, url)` — `Repo._migrate_watcher_column`
rebuilds the old url-only-PK table on first open. `Repo.forget_reported(watcher)`
clears one watcher's state (used when a feed was consumed by the wrong chat).

**Routing** (`Router` in `scraper/routing.py`, `JOBS_WATCHER_USERS` in `.env`, format
`watcher=user_id[,user_id];…`): a watcher named in the table is pushed only to
those users, and users named anywhere in the table receive only the watchers
they're named for. Unnamed watchers go to every subscriber the table doesn't
claim, so an empty table = everyone gets everything (original behaviour).
`/fetch` runs only the requesting user's watchers, so a manual fetch can't eat
another person's dedup state. Allowlist is `TG_ALLOWED_USER_IDS` (plural;
singular still read and merged).

Current watchers:
- `default` — Daniel, built-in SDET profile, all boards, unrouted (goes to him).
- `anastasia` — BD/partnerships + adjacent (BA/PM/AM/ops), LinkedIn on
  Worldwide+Cyprus (`profiles/anastasia.toml`), routed to user 499184201.
- `anastasia-pm` — junior Project Manager / Business Analyst in **Russian**,
  Telegram channels + LinkedIn pinned to Kazakhstan/Cyprus/Tbilisi/Uzbekistan
  (`profiles/anastasia-pm.toml`), routed to 499184201.

Both of her profiles exclude Europe (no work authorization) and keep
worldwide-remote + Cyprus + CIS + APAC. **Region tokens are substrings matched
against title+tags+location**, so `"remote"`, `"international"` and `"georgia"`
are deliberately absent from her eligible lists — each appears in job *titles*
and would override the region blocks (verified: US "EPC Project Manager - Remote"
and "BD Manager - International" in Portugal both leaked through until removed).

The shipped defaults reproduce the original behaviour: SDET/QA keywords, Asia-based-open-to-Europe eligibility, APAC/remote prioritized. To change the search, edit `search.toml` (or run `/setup-search`) — **don't** hardcode role/region assumptions back into `filters.py`.

## Bot

`python -m scraper.bot` runs a long-poll Telegram bot via `python-telegram-bot`. Schedule is two daily fetches in Asia/Ho_Chi_Minh; `data/jobs.db` tracks already-reported job IDs so the same listing isn't pushed twice. Only the ids in `TG_ALLOWED_USER_IDS` can talk to it.

Required env (`.env`): `TG_BOT_TOKEN`, `TG_ALLOWED_USER_IDS`. Optional: `JOBS_BOARDS`, `JOBS_MAX_PAGES`, `JOBS_MAX_AGE_DAYS`, `JOBS_SCHEDULE_TIMES`, `JOBS_TZ`, `JOBS_DB_PATH`, `JOBS_PROFILES`, `JOBS_WATCHER_USERS`. The search role/keywords/eligibility live in the profile files, loaded once at startup into `bot_data["profiles"]` (a list); restart the bot after editing them.

**Restarting the bot:** `./scripts/stop-bot.sh && sleep 8 && ./scripts/run-bot.sh --detach`. The 8s gap matters — Telegram's long-poll on the previous process can take several seconds to release server-side, otherwise the new instance gets `telegram.error.Conflict: terminated by other getUpdates request` and exits. If you see that error, kill cleanly, wait, restart.

## Tests

`pytest` — 78 tests, all offline. Cover filter matching, exclude rules (incl. include-vs-exclude scoping of `Job.description`), dedup, prioritization/ranking, age cutoff, parameterized eligibility, `search.toml` loading + multi-watcher profiles + `[boards.*]` options (`tests/test_search_profile.py`), per-watcher dedup state incl. the legacy-table migration (`tests/test_db.py`), watcher→user routing (`tests/test_routing.py`), Telegram post parsing from saved fixtures (`tests/test_telegramjobs.py`), and LinkedIn location/request-budget expansion (`tests/test_linkedin_board.py`). **HTTP layer is intentionally not unit-tested.** Verify board changes by running the CLI against the live site, e.g.

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
