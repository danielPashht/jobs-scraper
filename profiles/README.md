# profiles/ — one search profile per watcher

The bot can watch jobs for several people at once. Each person gets a profile
file here (same schema as `../search.example.toml`), and `.env` lists the active
ones:

```bash
JOBS_PROFILES=search.toml,profiles/anastasia.toml
```

Each pipeline run happens once per profile, and each profile's results are pushed
to the chats routed to it (labeled with the watcher).

To give a watcher its own recipient, allowlist them and add a routing entry:

```bash
TG_ALLOWED_USER_IDS=736345924,499184201
JOBS_WATCHER_USERS=anastasia=499184201
```

A user named in `JOBS_WATCHER_USERS` gets **only** their own watchers; watchers
named nowhere go to every other subscriber. They then `/start` the bot
themselves to register their chat.

Two keys matter for multi-watcher setups (both in `[search]`):

| key       | meaning                                                                    |
| --------- | -------------------------------------------------------------------------- |
| `watcher` | Dedup namespace + label. Must be unique; duplicates are skipped on load.   |
| `boards`  | Board set for this watcher only (e.g. `["linkedin"]`). Empty → `JOBS_BOARDS`. |

The main user's own profile stays at `../search.toml` (or the built-in defaults
when that file is absent) and uses the implicit `watcher = "default"`, which is
also where all pre-multi-watcher dedup history lives.

To add someone, run `/setup-search` in Claude Code — the "Adding another
watcher" section interviews them and writes the file. The `.toml` files here are
gitignored; only this README is committed.

Restart the bot after adding or editing a profile:

```bash
./scripts/stop-bot.sh && sleep 8 && ./scripts/run-bot.sh --detach
```
