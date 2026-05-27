# jobs-scraper

Python CLI + Telegram bot that scrapes remote job boards across all industries (web3, fintech, SaaS, anything), filters by keyword, dedupes across sources, ranks your preferred locations first, and prints a ranked table (or pushes new listings to Telegram).

**The role you search for is configurable** — it ships set up for SDET / Automation QA, but a `search.toml` profile lets anyone point it at any technical role and their own location situation. Run the `/setup-search` skill (in Claude Code) to be interviewed and have it written for you, or copy `search.example.toml` → `search.toml` and edit. See [Configure your search](#configure-your-search).

Replaces an earlier Claude-API "simulated listings" widget with real listings.

## Install

```bash
pip install -e .[dev]
```

Requires Python 3.11+.

## Usage

```bash
# Default: web3.career, default keywords, 3 pages, terminal table
python -m scraper.cli

# Multiple boards, custom keywords, JSON output
python -m scraper.cli \
  --boards web3career \
  --keywords "SDET" "automation QA" "playwright" \
  --max-pages 5 \
  --remote-only \
  --output jobs.json

# CSV
python -m scraper.cli --output jobs.csv
```

CLI flags:

| Flag | Default | Notes |
|---|---|---|
| `--profile` | `./search.toml` | Search profile to load (falls back to built-in defaults if absent). |
| `--boards` | `web3career` | Repeatable; choices: `web3career`, `remoteok`, `weworkremotely`, `linkedin`, `cryptojobslist` (stub) |
| `--keywords` | from `search.toml` | Case-insensitive substring match on title + tags + location. Overrides the profile. |
| `--exclude` | from `search.toml` | Same matching as keywords. Overrides the profile. |
| `--max-pages` | `3` | Per board |
| `--remote-only` | **on** | Keep only remote jobs. `--no-remote-only` to include onsite. |
| `--exclude-ineligible` | profile's setting | Drop roles locked to a region your profile marks ineligible, when no eligible-region signal is present. Keeps remote-anywhere and ambiguous listings. `--no-exclude-ineligible` to keep everything. |
| `--max-age-days` | `60` | Drop postings older than N days. Use `0` to disable. |
| `--output` | — | `.json` or `.csv` |
| `-v` | off | Verbose logging |

## Configure your search

What the scraper looks for lives in **`search.toml`** (gitignored, like `.env`). Two ways to create it:

- **Easiest:** open the repo in Claude Code and run the **`/setup-search`** skill. It interviews you (role, keywords, where you can work, Telegram), then writes `search.toml` + `.env` and runs a verification scrape.
- **Manual:** `cp search.example.toml search.toml` and edit. `search.example.toml` documents every field.

The profile has two parts:

- `[search]` — `role` label, `include_keywords`, `exclude_keywords`. Keywords are lowercase substrings matched on title + tags + location; a job is kept if it matches any include and no exclude keyword. They also drive the boards that need a server-side query (LinkedIn ORs them together; web3.career builds its URL slug from the first one).
- `[eligibility]` — `eligible_regions` (keep on match), `blocked_regions` (drop on match when no eligible signal), `block_us_states` (catch US "City, ST" locations), and `prioritize` (locations floated to the top). Set `enabled = false` to keep everything regardless of region.

If there's no `search.toml`, the project runs on its built-in defaults (SDET/QA, Asia-based-open-to-Europe), so it works out of the box.

## Output

Ranked by:
1. Preferred location first — your `prioritize` tokens from `search.toml` (defaults to remote / APAC)
2. Newest first

## Sources

| Board | Status | Notes |
|---|---|---|
| web3.career | working | Static HTML, paginated `?page=N`, 1.5s inter-page delay. URL slug (`/<role>+remote-jobs`) is derived from your first include keyword; web3-flavored, so it may return little for non-web3 roles. |
| remoteok.com | working | Public JSON API. Fetches the **full recent feed** and lets the pipeline keyword filter narrow it — role-agnostic. Set `tags` on `RemoteOKBoard` to pull specific tag slices instead. |
| weworkremotely.com | working | Fetches the full **all-jobs RSS feed** (stdlib `xml.etree`) and lets the keyword filter narrow. Set `categories` on `WeWorkRemotelyBoard` to pull specific category feeds. |
| linkedin.com | working | Public **guest** jobs endpoint (`jobs-guest/jobs/api/seeMoreJobPostings`), no auth. Requires a `keywords` query, which is built by OR-ing your `include_keywords` — a source-side query, with the pipeline narrowing on top. Throttled hard: 3s inter-page delay + one-shot 20s backoff on HTTP 429. Avoids the authenticated Voyager API on purpose (account-ban risk). |
| cryptojobslist.com | stub | Cloudflare challenge blocks httpx. Needs Playwright + stealth — see `scraper/boards/cryptojobslist.py` for the wiring instructions |

## Tests

```bash
pytest
```

Tests cover filter matching, exclusion, dedup, APAC detection, and ranking. The HTTP layer is not unit-tested; verify by running the CLI against the live site.

## Cron / GitHub Actions

```yaml
# .github/workflows/jobs.yml
on:
  schedule:
    - cron: "0 8 * * 1"  # Mondays 08:00 UTC
  workflow_dispatch:
jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -e .
      - run: python -m scraper.cli --output jobs.json --max-pages 5
      - uses: actions/upload-artifact@v4
        with: { name: jobs, path: jobs.json }
```

## Telegram bot

A long-running bot that scrapes on a schedule and pushes new jobs to your Telegram, deduping against a local SQLite so you never see the same listing twice.

### Setup

1. Copy `.env.example` → `.env` and paste your `TG_BOT_TOKEN` (from @BotFather).
2. Install the bot extras (already pulled in by base install):
   ```bash
   .venv/bin/pip install -e '.[cf]'
   ```
3. Find your Telegram `user_id`: start the bot, message it `/whoami`, copy the `user_id`, paste it as `TG_ALLOWED_USER_ID` in `.env`, restart. The bot ignores all other users.

### Running

```bash
./scripts/run-bot.sh             # foreground, Ctrl-C to stop
./scripts/run-bot.sh --detach    # background via caffeinate+nohup; survives terminal close
./scripts/stop-bot.sh            # stop the detached bot
tail -f logs/bot.log             # live logs
```

`caffeinate -i` prevents the Mac from idle-sleeping while the bot is up. The bot does **not** survive reboot — re-run `run-bot.sh --detach` after boot. (A `launchd` plist for boot-survival is a 10-minute add if you want it.)

### Bot UX

- `/start` — registers your chat for scheduled pushes and shows the "Fetch now" keyboard.
- `/fetch` or tapping **Fetch now** — runs the full pipeline immediately. Reply is either "No new jobs." or one or more messages listing the new ones with title / company / salary / age / location / Apply link.
j- Scheduled fetches at 09:00 and 21:00 in `Asia/Ho_Chi_Minh` (configurable via `JOBS_TZ` / `JOBS_SCHEDULE_TIMES`).

The first run sends every job that passes the filters, since the dedup DB starts empty.

### Config (in `.env`)

| Var | Default | Notes |
|---|---|---|
| `TG_BOT_TOKEN` | — | required |
| `TG_ALLOWED_USER_ID` | — | required; first /whoami tells you yours |
| `JOBS_DB_PATH` | `data/jobs.db` | SQLite file |
| `JOBS_TZ` | `Asia/Ho_Chi_Minh` | zoneinfo name |
| `JOBS_SCHEDULE_TIMES` | `09:00,21:00` | comma-separated `HH:MM` |
| `JOBS_BOARDS` | `web3career,remoteok,weworkremotely,linkedin` | comma-separated |
| `JOBS_MAX_PAGES` | `3` | per board |
| `JOBS_MAX_AGE_DAYS` | `60` | age cutoff |
| `PLAYWRIGHT_BROWSERS_PATH` | system default | needed for CJL |

> The role you're searching for (keywords + location eligibility) is **not** in
> `.env` — it lives in `search.toml`. See [Configure your search](#configure-your-search).

## Next steps

- Add WeWorkRemotely (RSS) and Himalayas next — both static, no auth
- Add Remote3 / Built In via the Playwright path (low marginal effort)
- Daily/weekly digest summary instead of every-run notifications
- launchd plist so the bot survives reboot
