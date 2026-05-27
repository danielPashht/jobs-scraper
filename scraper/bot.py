from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, time, timezone

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from scraper.config import Settings, load_settings
from scraper.db import Repo
from scraper.filters import DEFAULT_PRIORITIZE, is_prioritized
from scraper.models import Job
from scraper.pipeline import run_pipeline
from scraper.search_profile import SearchProfile, load_profile

log = logging.getLogger(__name__)

FETCH_BUTTON_LABEL = "Fetch now"
MAX_MESSAGE_CHARS = 3800  # Telegram hard cap is 4096; leave headroom.
SEND_RETRIES = 3
SEND_BACKOFF_SEC = 2.0


# --- formatting ---

def _format_age(posted_at: datetime | None) -> str:
    if posted_at is None:
        return "unknown age"
    now = datetime.now(timezone.utc)
    p = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=timezone.utc)
    days = max(0, (now - p).days)
    if days == 0:
        return "today"
    if days == 1:
        return "1d old"
    return f"{days}d old"


def _format_job(idx: int, job: Job, prioritize: tuple[str, ...] = DEFAULT_PRIORITIZE) -> str:
    title = html.escape(job.title)
    company = html.escape(job.company)
    salary = html.escape(job.salary) if job.salary else "salary not listed"
    age = _format_age(job.posted_at)
    locs = html.escape(", ".join(job.locations)) if job.locations else "remote"
    pref = " · ★ preferred location" if is_prioritized(job, prioritize) else ""
    url = html.escape(str(job.url))
    return (
        f"<b>{idx}. {title}</b> — {company}\n"
        f"   {salary} · {age} · {locs}{pref}\n"
        f"   <a href=\"{url}\">Apply</a>"
    )


def format_jobs_message(
    jobs: list[Job],
    header: str | None = None,
    prioritize: tuple[str, ...] = DEFAULT_PRIORITIZE,
) -> list[str]:
    """Split a job list into Telegram-sized chunks."""
    header = header or f"<b>{len(jobs)} new job{'s' if len(jobs) != 1 else ''}</b>"
    chunks: list[str] = []
    current = header
    for i, job in enumerate(jobs, 1):
        block = _format_job(i, job, prioritize)
        if len(current) + len(block) + 2 > MAX_MESSAGE_CHARS:
            chunks.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}"
    chunks.append(current)
    return chunks


# --- auth ---

def _is_allowed(update: Update, settings: Settings) -> bool:
    user = update.effective_user
    if user is None:
        return False
    if settings.tg_allowed_user_id is None:
        log.warning(
            "no TG_ALLOWED_USER_ID set — rejecting request from user_id=%d (chat_id=%s). "
            "Set TG_ALLOWED_USER_ID=%d in .env and restart.",
            user.id,
            update.effective_chat.id if update.effective_chat else None,
            user.id,
        )
        return False
    return user.id == settings.tg_allowed_user_id


# --- handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    repo: Repo = context.application.bot_data["repo"]
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return

    if not _is_allowed(update, settings):
        await update.message.reply_text(
            f"This bot is private.\nYour user_id is {user.id}.\n"
            "Set TG_ALLOWED_USER_ID in .env and restart the bot if this is you."
        )
        return

    await asyncio.to_thread(repo.add_subscriber, chat.id, user.id)
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton(FETCH_BUTTON_LABEL)]], resize_keyboard=True
    )
    times = ", ".join(f"{h:02d}:{m:02d}" for h, m in settings.schedule_times)
    await update.message.reply_text(
        f"Jobs bot ready.\nScheduled fetches: {times} ({settings.tz.key}).\n"
        f"Tap '{FETCH_BUTTON_LABEL}' or send /fetch to run now.",
        reply_markup=keyboard,
    )


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return
    await _safe_send(context.bot, chat.id, f"user_id: {user.id}\nchat_id: {chat.id}")


async def cmd_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_allowed(update, settings):
        return
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id, "Fetching…")
    await _run_and_report(context, [chat_id])


async def _run_and_report(context: ContextTypes.DEFAULT_TYPE, chat_ids: list[int]) -> None:
    settings: Settings = context.application.bot_data["settings"]
    profile: SearchProfile = context.application.bot_data["profile"]
    repo: Repo = context.application.bot_data["repo"]
    try:
        jobs = await asyncio.to_thread(
            run_pipeline,
            boards=settings.boards,
            max_pages=settings.max_pages,
            max_age_days=settings.max_age_days,
            keywords=profile.include_keywords,
            exclude=profile.exclude_keywords,
            exclude_ineligible=profile.eligibility_enabled,
            eligible_regions=profile.eligible_regions,
            blocked_regions=profile.blocked_regions,
            block_us_states=profile.block_us_states,
            prioritize=profile.prioritize,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("pipeline failed")
        for cid in chat_ids:
            await context.bot.send_message(cid, f"Fetch failed: {html.escape(str(exc))}")
        return

    new_jobs = await asyncio.to_thread(repo.filter_new, jobs)
    log.info("pipeline: %d total, %d new (vs DB)", len(jobs), len(new_jobs))

    if not new_jobs:
        for cid in chat_ids:
            await _safe_send(context.bot, cid, "No new jobs.")
        return

    chunks = format_jobs_message(new_jobs, prioritize=profile.prioritize)
    for cid in chat_ids:
        for chunk in chunks:
            await _safe_send(
                context.bot,
                cid,
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

    await asyncio.to_thread(repo.mark_reported, new_jobs)


async def on_fetch_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # The text matched our regex, so behave like /fetch.
    await cmd_fetch(update, context)


# --- scheduled job ---

async def scheduled_fetch(context: ContextTypes.DEFAULT_TYPE) -> None:
    repo: Repo = context.application.bot_data["repo"]
    chat_ids = await asyncio.to_thread(repo.list_subscriber_chat_ids)
    if not chat_ids:
        log.info("scheduled fetch: no subscribers, skipping")
        return
    log.info("scheduled fetch: pushing to %d subscriber(s)", len(chat_ids))
    await _run_and_report(context, chat_ids)


# --- lifecycle ---

async def _safe_send(bot, chat_id: int, text: str, **kwargs) -> None:
    """send_message with retry on transient NetworkError / TimedOut.

    Vietnamese ISPs occasionally drop the first connect to api.telegram.org's CDN.
    A short backoff + retry recovers from these without losing the message.
    """
    last_exc: Exception | None = None
    for attempt in range(1, SEND_RETRIES + 1):
        try:
            await bot.send_message(chat_id, text, **kwargs)
            return
        except (NetworkError, TimedOut) as exc:
            last_exc = exc
            log.warning(
                "send_message attempt %d/%d failed (%s); retrying in %.1fs",
                attempt,
                SEND_RETRIES,
                exc,
                SEND_BACKOFF_SEC,
            )
            await asyncio.sleep(SEND_BACKOFF_SEC * attempt)
    log.error("send_message gave up after %d retries: %s", SEND_RETRIES, last_exc)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch-all error handler — log and keep the bot alive."""
    log.error("handler error", exc_info=context.error)


async def _notify_started(app: Application) -> None:
    """Broadcast a 'Bot started!' message to every known subscriber on startup."""
    repo: Repo = app.bot_data["repo"]
    settings: Settings = app.bot_data["settings"]
    chat_ids = await asyncio.to_thread(repo.list_subscriber_chat_ids)
    if not chat_ids:
        log.info("startup: no subscribers yet, skipping 'Bot started!' notification")
        return
    times = ", ".join(f"{h:02d}:{m:02d}" for h, m in settings.schedule_times)
    msg = f"Bot started.\nScheduled fetches: {times} ({settings.tz.key})."
    for cid in chat_ids:
        await _safe_send(app.bot, cid, msg)


def build_app(settings: Settings, repo: Repo, profile: SearchProfile | None = None) -> Application:
    # Beefier HTTP client — Vietnamese ISP/Telegram CDN combo benefits from
    # longer connect/read timeouts and a larger pool.
    request = HTTPXRequest(
        connect_timeout=15.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=10.0,
    )
    app = (
        Application.builder()
        .token(settings.tg_bot_token)
        .request(request)
        .post_init(_notify_started)
        .build()
    )
    app.bot_data["settings"] = settings
    app.bot_data["repo"] = repo
    app.bot_data["profile"] = profile or load_profile()
    app.add_error_handler(_on_error)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("fetch", cmd_fetch))
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(f"^{FETCH_BUTTON_LABEL}$"),
            on_fetch_button,
        )
    )

    for hour, minute in settings.schedule_times:
        app.job_queue.run_daily(
            scheduled_fetch,
            time=time(hour, minute, tzinfo=settings.tz),
            name=f"fetch_{hour:02d}{minute:02d}",
        )

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # httpx is chatty at INFO
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    settings = load_settings()
    profile = load_profile()
    repo = Repo(settings.db_path)
    log.info(
        "Bot booting. role=%r db=%s reported_so_far=%d allowed_user_id=%s schedule=%s tz=%s",
        profile.role,
        settings.db_path,
        repo.count_reported(),
        settings.tg_allowed_user_id,
        settings.schedule_times,
        settings.tz.key,
    )

    app = build_app(settings, repo, profile)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
