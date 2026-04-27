import os
import asyncio
import json
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, BotCommand
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties

TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_THREAD_ID = 3447

WARNINGS_FILE = "warnings.json"
SETTINGS_FILE = "settings.json"

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

LINK_PATTERN = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/)", re.IGNORECASE)

def load_warnings():
    try:
        with open(WARNINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_warnings(data):
    with open(WARNINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
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
    except:
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
    except:
        await message.answer("❌ Введите число")

@dp.message(Command("info"))
async def bot_info(message: Message):
    await message.answer(f"🤖 Бот-модератор\n📌 Разрешённая папка: {ALLOWED_THREAD_ID}\n⚠️ Лимит: {settings['max_warnings']}\n📊 Активных: {len(warnings)}")

@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(f"🛡️ Правила:\n• Ссылки только в папке ОБМЕННИК\n• i.bybit.com — только в ОБМЕННИКЕ\n• {settings['max_warnings']} нарушений → бан\n\nКоманды:\n/stats\n/clear_warnings\n/set_warnings\n/info\n/help")

@dp.message(F.new_chat_members)
async def welcome_new_member(message: Message):
    for member in message.new_chat_members:
        if member.id != bot.id:
            await message.answer(f"👋 Добро пожаловать, {member.full_name}!\n📌 Ссылки только в папке «ОБМЕННИК»")

@dp.message()
async def check_links(message: Message):
    if message.text and message.text.startswith('/'):
        return
    if message.from_user.is_bot:
        return
    if not message.text:
        return

    thread_id = getattr(message, 'message_thread_id', None)
    
    if is_bybit_link(message.text):
        if thread_id != ALLOWED_THREAD_ID:
            await message.delete()
            user_id = str(message.from_user.id)
            warnings[user_id] = warnings.get(user_id, 0) + 1
            save_warnings(warnings)
            attempts = warnings[user_id]
            max_w = settings["max_warnings"]
            await message.answer(f"⚠️ {message.from_user.full_name}, ордера разрешены только в разделе «ОБМЕННИК»\n📌 Предупреждение: {attempts}/{max_w}")
            if attempts >= max_w:
                try:
                    await bot.ban_chat_member(message.chat.id, message.from_user.id)
                    await message.answer(f"🚫 {message.from_user.full_name} заблокирован")
                    warnings.pop(user_id, None)
                    save_warnings(warnings)
                except Exception as e:
                    print(f"Ошибка бана: {e}")
            return
        else:
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
        await message.answer(f"⚠️ {message.from_user.full_name}, ссылки здесь запрещены!\n📌 Предупреждение: {attempts}/{max_w}")
    else:
        try:
            await bot.ban_chat_member(message.chat.id, message.from_user.id)
            await message.answer(f"🚫 {message.from_user.full_name} заблокирован")
            warnings.pop(user_id, None)
            save_warnings(warnings)
        except Exception as e:
            print(f"Ошибка бана: {e}")

async def set_commands():
    commands = [
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="clear_warnings", description="Сбросить предупреждения"),
        BotCommand(command="set_warnings", description="Изменить лимит"),
        BotCommand(command="info", description="Информация"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)

async def main():
    print("=" * 50)
    print("🚀 БОТ ЗАПУЩЕН")
    print(f"✅ Папка «ОБМЕННИК» (ID: {ALLOWED_THREAD_ID})")
    print(f"⚠️ Максимум предупреждений: {settings['max_warnings']}")
    print("=" * 50)
    await set_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
