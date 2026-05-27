---
name: setup-search
description: Set up jobs-scraper for your own job hunt — interviews you for the role, keywords, and where you can work, then writes search.toml (and .env for the Telegram bot) and runs a verification scrape. Use when someone clones this repo and wants to configure it for a role other than the default SDET/QA, or asks how to set up their search.
user_invocable: true
---

# setup-search — configure jobs-scraper for *your* job hunt

Your job is to turn a new user's situation into a working `search.toml` (and, if
they want the Telegram bot, a `.env`). Interview them, derive the config, write
the files, then prove it works with a one-page scrape.

Read `search.example.toml` first — it is the schema and documents every field.
The committed default targets SDET/QA for an Asia-based-open-to-Europe user; you
are replacing that with the user's own role and location situation.

## What goes where

- **`search.toml`** (gitignored, you create it) — *what* to search for: `role`,
  `include_keywords`, `exclude_keywords`, and the `[eligibility]` block
  (`eligible_regions`, `blocked_regions`, `block_us_states`, `prioritize`).
- **`.env`** (gitignored, only if they want the bot) — secrets/ops:
  `TG_BOT_TOKEN`, `TG_ALLOWED_USER_ID`, optional `JOBS_*`. Copy from `.env.example`.

Never put keywords or eligibility in `.env`, and never put secrets in `search.toml`.

## Interview (use the AskUserQuestion tool)

1. **Role & keywords.** Ask what role/title they're hunting and the must-have
   tools/skills. Derive:
   - `role` — a short human label (e.g. "Data Engineer").
   - `include_keywords` — lowercase substrings matched on title+tags+location.
     Cover common title orderings and the key tools (e.g. for data engineering:
     `"data engineer"`, `"data platform"`, `"etl"`, `"airflow"`, `"spark"`,
     `"dbt"`). These also build the LinkedIn query and web3.career slug, so make
     the FIRST keyword the cleanest role phrase.
   - `exclude_keywords` — what to drop (e.g. `"intern"`, `"manager"`, or
     `"manual qa"` for an automation-only QA search). Ask if unsure.

2. **Where can you work?** Ask where they can legally work / want to work, and
   whether they're open to relocation. Map their answer to region token lists
   using your own geography knowledge (tokens are lowercase substrings matched
   against the listing's location/tags/title):
   - `eligible_regions` — keep-on-match. Always include the "anywhere" tokens
     (`"worldwide"`, `"global"`, `"anywhere"`, `"remote"`, `"fully remote"`)
     plus country/region names they can take. For a US-based user, include
     `"united states"`, `"usa"`, `" us "`; for EU, the European country names; etc.
   - `blocked_regions` — drop-on-match (only when no eligible signal present).
     The regions they *can't* take.
   - `block_us_states` — `true` keeps the "City, ST" US-location catch (e.g.
     "Austin, TX"). Set `false` if the US is one of their eligible regions.
   - `prioritize` — tokens for locations they most want at the top of results.
   - If they say "anywhere remote, no restrictions", set `enabled = false` and
     don't bother tuning the region lists.

3. **Telegram bot or CLI only?** Ask if they want scheduled pushes to Telegram
   or will just run the CLI.
   - CLI only → skip `.env`; they're done after the profile.
   - Bot → walk them through: create a bot with @BotFather, paste the token into
     `TG_BOT_TOKEN`. Tell them `TG_ALLOWED_USER_ID` is found by starting the bot
     and sending it `/whoami` (the bot logs/replies their numeric id), then
     pasting it back and restarting. Copy `.env.example` → `.env` and fill it in.

## Write the files

- Copy `search.example.toml` to `search.toml`, then replace the `[search]` and
  `[eligibility]` values with what you derived. Keep the explanatory comments.
- Only create/modify `.env` if they chose the bot. If `.env` already exists,
  edit it rather than overwriting.
- Validate it parses:
  `.venv/bin/python -c "from scraper.search_profile import load_profile; print(load_profile())"`

## Verify

Run a small live scrape and show them a few results so they can sanity-check the
role matches (RemoteOK is fast and needs no auth):

```bash
.venv/bin/python -m scraper.cli --boards remoteok --max-pages 1
```

If nothing matches, the keywords are likely too narrow or too web3-specific —
loop back to step 1 and broaden `include_keywords`. If the wrong regions show
up, revisit the eligibility lists. Confirm the displayed "searching for: <role>"
line matches what they wanted.

## Notes

- `search.toml` and `.env` are gitignored, so a contributor's personal setup
  never gets committed — they fork/clone and run this skill to make it theirs.
- The CLI reads `search.toml` automatically (or `--profile path`). The bot reads
  it at startup; restart the bot after editing (see README "Restarting the bot").
- web3.career is web3-flavored; for a non-web3 role it may return little — that's
  expected. RemoteOK, WeWorkRemotely and LinkedIn are general and fetch broad.
