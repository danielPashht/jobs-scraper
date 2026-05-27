# jobs-scraper — Claude notes

CLI + Telegram bot that scrapes **remote job boards across all industries** (web3, fintech, SaaS, anything) for **SDET / Automation QA / test-engineer roles**, filters by keyword, dedupes across sources, ranks APAC-friendly first, and pushes new listings to Telegram.

> ⚠️ Scope: the project is **not** restricted to crypto/web3/fintech. The keyword filter in `scraper/filters.py` is industry-agnostic; only some *sources* happen to be web3-focused. When adding boards, prefer general-purpose remote boards.

## Layout

```
scraper/
  cli.py            # `python -m scraper.cli` — one-shot terminal/CSV/JSON output
  bot.py            # `python -m scraper.bot` — long-running Telegram bot (APScheduler)
  pipeline.py       # scrape → filter → dedup → rank
  filters.py        # keyword include/exclude, location eligibility, APAC ranking, age cutoff
  models.py         # pydantic `Job` (dedup key = sha1(title|company))
  config.py         # env-driven Settings dataclass (TG_*, JOBS_*)
  db.py             # SQLite dedup store for the bot
  output.py         # rich table / CSV / JSON writers
  boards/
    base.py         # abstract Board(httpx.Client) → Iterable[Job]
    web3career.py   # static HTML, paginated
    remoteok.com    # JSON API, multiple tag slices unioned
    weworkremotely  # per-category RSS, stdlib xml.etree
    linkedin.py     # public guest jobs endpoint, boolean keyword query, 429 backoff
    cryptojobslist  # STUB — needs Playwright + stealth (Cloudflare)
scripts/
  run-bot.sh        # foreground or --detach (caffeinate + nohup + pidfile)
  stop-bot.sh       # kills via logs/bot.pid
tests/              # pytest, no live HTTP
data/jobs.db        # SQLite dedup state (gitignored)
logs/bot.log        # bot output (gitignored)
```

## Adding a board

Subclass `scraper.boards.base.Board`, implement `fetch(max_pages: int) -> Iterable[Job]`, register in `scraper/boards/__init__.py::ALL_BOARDS`. The `self.client` is a configured `httpx.Client` with a desktop UA. If a site needs JS/anti-bot bypass, follow the Playwright path sketched in `cryptojobslist.py`.

Each yielded `Job` runs through the same filter+rank pipeline — boards do **not** need to filter by keyword themselves. Just yield broadly; the pipeline narrows.

For pagination, use `max_pages`. For API-based boards (RemoteOK), it's fine to ignore it; the parameter exists for interface compatibility.

## Filters (current defaults, in `scraper/filters.py`)

- **Include kws:** `automation qa`, `sdet`, `test engineer`, `qa engineer`, `quality assurance`, `pytest`, `playwright`, `selenium`
- **Exclude kws:** `manual qa`, `manual quality assurance`, `manual test`, `manual tester`, `intern`
- **Match haystack:** `title + " ".join(tags) + " ".join(locations)`, lowercased substring match
- **Remote-only:** on by default (CLI: `--no-remote-only`)
- **Location eligibility (`--exclude-ineligible`):** on by default. Daniel is an Asia-based nomad who wants either a fully-remote role he can do from anywhere/Asia, **or** anything in Europe (remote-EU *or* a relocation offer). So `is_eligible()` keeps worldwide/APAC/European listings and anything with no clear region lock (ambiguous → keep, to avoid missing good jobs); it drops only roles clearly locked to a region he can't use — the US (incl. `City, ST` state codes, matched on the location string via `_US_STATE_RE`), the rest of the Americas, and the Middle East — when no eligible signal is present. Conservative by design.
- **Age cutoff:** 60 days; unknown `posted_at` is treated as recent

Daniel is based in Vietnam, so APAC-friendly listings (or those marked remote/worldwide) sort to the top.

## Bot

`python -m scraper.bot` runs a long-poll Telegram bot via `python-telegram-bot`. Schedule is two daily fetches in Asia/Ho_Chi_Minh; `data/jobs.db` tracks already-reported job IDs so the same listing isn't pushed twice. Only `TG_ALLOWED_USER_ID` can talk to it.

Required env (`.env`): `TG_BOT_TOKEN`, `TG_ALLOWED_USER_ID`. Optional: `JOBS_BOARDS`, `JOBS_MAX_PAGES`, `JOBS_MAX_AGE_DAYS`, `JOBS_SCHEDULE_TIMES`, `JOBS_TZ`, `JOBS_DB_PATH`.

**Restarting the bot:** `./scripts/stop-bot.sh && sleep 8 && ./scripts/run-bot.sh --detach`. The 8s gap matters — Telegram's long-poll on the previous process can take several seconds to release server-side, otherwise the new instance gets `telegram.error.Conflict: terminated by other getUpdates request` and exits. If you see that error, kill cleanly, wait, restart.

## Tests

`pytest` — 19 tests, all offline. Cover filter matching, exclude rules, dedup, APAC detection, ranking, age cutoff. **HTTP layer is intentionally not unit-tested.** Verify board changes by running the CLI against the live site, e.g.

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
