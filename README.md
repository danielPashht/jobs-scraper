# jobs-scraper

Python CLI that scrapes web3/fintech job boards for SDET / Automation QA / test-engineer roles, filters by keyword, dedupes across sources, and prints a ranked table.

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
| `--boards` | `web3career` | Repeatable; choices: `web3career`, `cryptojobslist` (stub) |
| `--keywords` | SDET/QA defaults | Case-insensitive substring match on title + tags + location |
| `--exclude` | `manual qa only`, `intern` | Same matching as keywords |
| `--max-pages` | `3` | Per board |
| `--remote-only` | **on** | Keep only remote jobs. `--no-remote-only` to include onsite. |
| `--exclude-us-only` | **on** | Drop jobs that look US-only (US location + no global marker). `--no-exclude-us-only` to keep them. |
| `--max-age-days` | `60` | Drop postings older than N days. Use `0` to disable. |
| `--output` | — | `.json` or `.csv` |
| `-v` | off | Verbose logging |

## Output

Ranked by:
1. APAC-friendly (remote OR location mentions APAC) — Daniel is in Vietnam
2. Newest first

## Sources

| Board | Status | Notes |
|---|---|---|
| web3.career | working | Static HTML, paginated `?page=N`, 1.5s inter-page delay |
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
| `JOBS_BOARDS` | `web3career,cryptojobslist` | comma-separated |
| `JOBS_MAX_PAGES` | `3` | per board |
| `JOBS_MAX_AGE_DAYS` | `60` | age cutoff |
| `PLAYWRIGHT_BROWSERS_PATH` | system default | needed for CJL |

## Next steps

- Add Remote3 / Built In via the Playwright path (low marginal effort)
- Daily/weekly digest summary instead of every-run notifications
- launchd plist so the bot survives reboot
