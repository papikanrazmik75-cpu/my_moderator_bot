import os
import sys
import asyncio
import json
import re
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict

from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.types import Message, BotCommand, Update
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("moderator_bot")

TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_THREAD_ID = 3447

WARNINGS_FILE = "warnings.json"
SETTINGS_FILE = "settings.json"

WATCHDOG_INTERVAL_SEC = int(os.getenv("WATCHDOG_INTERVAL_SEC", "60"))
API_CHECK_TIMEOUT_SEC = int(os.getenv("API_CHECK_TIMEOUT_SEC", "15"))
POLLING_RESTART_DELAY_SEC = int(os.getenv("POLLING_RESTART_DELAY_SEC", "5"))
POLLING_TIMEOUT_SEC = int(os.getenv("POLLING_TIMEOUT_SEC", "30"))
SESSION_TIMEOUT_SEC = int(os.getenv("SESSION_TIMEOUT_SEC", "60"))
STALE_RESTART_AFTER_SEC = int(os.getenv("STALE_RESTART_AFTER_SEC", "180"))

session = AiohttpSession(timeout=SESSION_TIMEOUT_SEC)
bot = Bot(
    token=TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode="HTML"),
)
dp = Dispatcher()

bot_state: Dict[str, Any] = {
    "polling_active": False,
    "last_update_at": None,
    "last_handler_at": None,
    "last_api_check_at": None,
    "last_api_ok": None,
    "last_api_error": None,
    "updates_handled": 0,
    "handler_errors": 0,
    "polling_restarts": 0,
    "started_at": datetime.now(timezone.utc).isoformat(),
}

LINK_PATTERN = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/)", re.IGNORECASE)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def mark_update_received() -> None:
    now = utc_now().isoformat()
    bot_state["last_update_at"] = now
    bot_state["updates_handled"] += 1


def mark_handler_finished() -> None:
    bot_state["last_handler_at"] = utc_now().isoformat()


class ActivityMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        mark_update_received()
        event_name = type(event).__name__
        logger.info("Incoming update: %s", event_name)
        try:
            result = await handler(event, data)
            mark_handler_finished()
            logger.info("Handled update: %s", event_name)
            return result
        except Exception:
            bot_state["handler_errors"] += 1
            logger.exception("Handler error for update: %s", event_name)
            raise


dp.update.middleware(ActivityMiddleware())


@dp.errors()
async def dispatcher_errors_handler(event: Update, exception: Exception):
    bot_state["handler_errors"] += 1
    logger.exception("Unhandled dispatcher error: %s", exception)
    return True


def load_warnings():
    try:
        with open(WARNINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load warnings: %s", exc)
        return {}


def save_warnings(data):
    with open(WARNINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load settings: %s", exc)
        return {"max_warnings": 5, "welcome_enabled": True}


def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


warnings = load_warnings()
settings = load_settings()


def contains_link(text: str) -> bool:
    return bool(LINK_PATTERN.search(text)) if text else False


def is_bybit_link(text: str) -> bool:
    return "i.bybit.com" in text.lower() if text else False


async def get_admins(chat_id):
    try:
        admins = await bot.get_chat_administrators(chat_id)
        return [admin.user.id for admin in admins]
    except Exception as exc:
        logger.warning("Failed to fetch admins for chat %s: %s", chat_id, exc)
        return []


@dp.message(Command("stats"))
async def show_stats(message: Message):
    if message.from_user.id not in await get_admins(message.chat.id):
        await message.answer("❌ Только для администраторов!")
        return
    if not warnings:
        await message.answer("📊 Нет активных предупреждений")
        return
    text = "📊 Статистика предупреждений\n\n"
    for uid, count in list(warnings.items())[:10]:
        text += f"👤 ID: {uid} → {count}/{settings['max_warnings']}\n"
    await message.answer(text)


@dp.message(Command("clear_warnings"))
async def clear_warnings_cmd(message: Message):
    if message.from_user.id not in await get_admins(message.chat.id):
        await message.answer("❌ Только для администраторов!")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /clear_warnings @username")
        return
    target = args[1].replace("@", "")
    if target in warnings:
        del warnings[target]
        save_warnings(warnings)
        await message.answer(f"✅ Предупреждения для {target} сброшены")
    else:
        await message.answer(f"❌ Нет предупреждений у {target}")


@dp.message(Command("set_warnings"))
async def set_max_warnings(message: Message):
    if message.from_user.id not in await get_admins(message.chat.id):
        await message.answer("❌ Только для администраторов!")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /set_warnings 5")
        return
    try:
        new_max = int(args[1])
        if 1 <= new_max <= 20:
            settings["max_warnings"] = new_max
            save_settings(settings)
            await message.answer(f"✅ Лимит изменён на {new_max}")
        else:
            await message.answer("❌ Число от 1 до 20")
    except Exception:
        await message.answer("❌ Введите число")


@dp.message(Command("info"))
async def bot_info(message: Message):
    await message.answer(
        f"🤖 Бот-модератор\n"
        f"📌 Разрешённая папка: {ALLOWED_THREAD_ID}\n"
        f"⚠️ Лимит: {settings['max_warnings']}\n"
        f"📊 Активных: {len(warnings)}"
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        f"🛡️ Правила:\n"
        f"• Ссылки только в папке ОБМЕННИК\n"
        f"• i.bybit.com — только в ОБМЕННИКЕ\n"
        f"• {settings['max_warnings']} нарушений → бан\n\n"
        f"Команды:\n/stats\n/clear_warnings\n/set_warnings\n/info\n/help"
    )


@dp.message(F.new_chat_members)
async def welcome_new_member(message: Message):
    for member in message.new_chat_members:
        if member.id != bot.id:
            await message.answer(
                f"👋 Добро пожаловать, {member.full_name}!\n"
                f"📌 Ссылки только в папке «ОБМЕННИК»"
            )


@dp.message()
async def check_links(message: Message):
    if message.text and message.text.startswith("/"):
        return
    if message.from_user is None or message.from_user.is_bot:
        return
    if not message.text:
        return

    thread_id = getattr(message, "message_thread_id", None)

    if is_bybit_link(message.text):
        if thread_id != ALLOWED_THREAD_ID:
            await message.delete()
            user_id = str(message.from_user.id)
            warnings[user_id] = warnings.get(user_id, 0) + 1
            save_warnings(warnings)
            attempts = warnings[user_id]
            max_w = settings["max_warnings"]
            await message.answer(
                f"⚠️ {message.from_user.full_name}, ордера разрешены только в разделе «ОБМЕННИК»\n"
                f"📌 Предупреждение: {attempts}/{max_w}"
            )
            if attempts >= max_w:
                try:
                    await bot.ban_chat_member(message.chat.id, message.from_user.id)
                    await message.answer(f"🚫 {message.from_user.full_name} заблокирован")
                    warnings.pop(user_id, None)
                    save_warnings(warnings)
                except Exception as exc:
                    logger.exception("Ban failed for user %s: %s", user_id, exc)
            return
        return

    if not contains_link(message.text):
        return

    if thread_id == ALLOWED_THREAD_ID:
        return

    await message.delete()
    user_id = str(message.from_user.id)
    warnings[user_id] = warnings.get(user_id, 0) + 1
    save_warnings(warnings)
    attempts = warnings[user_id]
    max_w = settings["max_warnings"]

    if attempts < max_w:
        await message.answer(
            f"⚠️ {message.from_user.full_name}, ссылки здесь запрещены!\n"
            f"📌 Предупреждение: {attempts}/{max_w}"
        )
    else:
        try:
            await bot.ban_chat_member(message.chat.id, message.from_user.id)
            await message.answer(f"🚫 {message.from_user.full_name} заблокирован")
            warnings.pop(user_id, None)
            save_warnings(warnings)
        except Exception as exc:
            logger.exception("Ban failed for user %s: %s", user_id, exc)


async def set_commands():
    commands = [
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="clear_warnings", description="Сбросить предупреждения"),
        BotCommand(command="set_warnings", description="Изменить лимит"),
        BotCommand(command="info", description="Информация"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)


async def check_telegram_api() -> bool:
    bot_state["last_api_check_at"] = utc_now().isoformat()
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=API_CHECK_TIMEOUT_SEC)
        bot_state["last_api_ok"] = True
        bot_state["last_api_error"] = None
        logger.info("Telegram API check OK: @%s", me.username)
        return True
    except Exception as exc:
        bot_state["last_api_ok"] = False
        bot_state["last_api_error"] = repr(exc)
        logger.exception("Telegram API check failed")
        return False


def is_bot_healthy() -> bool:
    return bool(bot_state["polling_active"] and bot_state["last_api_ok"])


async def _polling_once():
    bot_state["polling_active"] = True
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await set_commands()
        logger.info("Starting Telegram polling (timeout=%ss)", POLLING_TIMEOUT_SEC)
        await dp.start_polling(
            bot,
            handle_signals=False,
            polling_timeout=POLLING_TIMEOUT_SEC,
        )
    finally:
        bot_state["polling_active"] = False


async def supervisor():
    logger.info(
        "Supervisor started (watchdog=%ss, api_timeout=%ss, stale_restart=%ss)",
        WATCHDOG_INTERVAL_SEC,
        API_CHECK_TIMEOUT_SEC,
        STALE_RESTART_AFTER_SEC,
    )
    while True:
        consecutive_api_failures = 0
        polling_task = asyncio.create_task(_polling_once(), name="tg-polling")

        while True:
            done, _ = await asyncio.wait({polling_task}, timeout=WATCHDOG_INTERVAL_SEC)
            if polling_task in done:
                break

            api_ok = await check_telegram_api()
            logger.info(
                "Heartbeat: polling_active=%s api_ok=%s updates=%s handler_errors=%s "
                "restarts=%s last_update=%s last_handler=%s",
                bot_state["polling_active"],
                api_ok,
                bot_state["updates_handled"],
                bot_state["handler_errors"],
                bot_state["polling_restarts"],
                bot_state["last_update_at"],
                bot_state["last_handler_at"],
            )

            if api_ok:
                consecutive_api_failures = 0
                continue

            consecutive_api_failures += 1
            stale_for = consecutive_api_failures * WATCHDOG_INTERVAL_SEC
            logger.error(
                "Watchdog: API unreachable for ~%ss (failure #%s)",
                stale_for,
                consecutive_api_failures,
            )
            if stale_for >= STALE_RESTART_AFTER_SEC:
                logger.error("Watchdog: forcing polling restart (stale/hung detected)")
                polling_task.cancel()
                break

        try:
            await polling_task
            logger.warning("Polling task ended without exception")
        except asyncio.CancelledError:
            logger.warning("Polling task was cancelled by watchdog")
        except Exception:
            logger.exception("Polling task crashed")
        finally:
            bot_state["polling_active"] = False

        bot_state["polling_restarts"] += 1
        logger.warning(
            "Restarting polling in %ss (restart #%s)",
            POLLING_RESTART_DELAY_SEC,
            bot_state["polling_restarts"],
        )
        await asyncio.sleep(POLLING_RESTART_DELAY_SEC)


async def handle_root(_request):
    status = "healthy" if is_bot_healthy() else "degraded"
    return web.json_response(
        {
            "status": status,
            "message": "Bot is running",
            "polling_active": bot_state["polling_active"],
            "last_api_ok": bot_state["last_api_ok"],
            "last_update_at": bot_state["last_update_at"],
            "updates_handled": bot_state["updates_handled"],
        }
    )


async def handle_health(request):
    healthy = is_bot_healthy()
    payload = {
        "status": "ok" if healthy else "degraded",
        "polling_active": bot_state["polling_active"],
        "last_api_ok": bot_state["last_api_ok"],
        "last_api_check_at": bot_state["last_api_check_at"],
        "last_update_at": bot_state["last_update_at"],
        "last_handler_at": bot_state["last_handler_at"],
        "updates_handled": bot_state["updates_handled"],
        "handler_errors": bot_state["handler_errors"],
        "polling_restarts": bot_state["polling_restarts"],
        "last_api_error": bot_state["last_api_error"],
    }
    return web.json_response(payload, status=200 if healthy else 503)


async def start_health_server():
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health server listening on 0.0.0.0:%s", port)


def install_global_error_handlers(loop: asyncio.AbstractEventLoop) -> None:
    def handle_async_exception(_loop, context):
        message = context.get("message", "Unhandled asyncio exception")
        exc = context.get("exception")
        if exc:
            logger.error("%s\n%s", message, "".join(traceback.format_exception(exc)))
        else:
            logger.error("Asyncio context error: %s", context)

    loop.set_exception_handler(handle_async_exception)

    def handle_uncaught(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical(
            "Uncaught exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )

    sys.excepthook = handle_uncaught


async def main():
    loop = asyncio.get_running_loop()
    install_global_error_handlers(loop)

    logger.info("=" * 50)
    logger.info("BOT STARTED")
    logger.info("Allowed thread ID: %s", ALLOWED_THREAD_ID)
    logger.info("Max warnings: %s", settings["max_warnings"])
    logger.info("=" * 50)

    await check_telegram_api()
    await asyncio.gather(start_health_server(), supervisor())


if __name__ == "__main__":
    asyncio.run(main())
