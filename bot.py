import os
import asyncio
import json
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, BotCommand
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties

# Токен берем из переменных окружения (для безопасности при хостинге)
TOKEN = os.environ["BOT_TOKEN"]

# ID темы, где ссылки полностью разрешены (ОБМЕННИК)
ALLOWED_THREAD_ID = 3447

WARNINGS_FILE = "warnings.json"
SETTINGS_FILE = "settings.json"

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher()

# Общий паттерн для любых ссылок
LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/)",
    re.IGNORECASE
)


# ============================================
# РАБОТА С ФАЙЛАМИ
# ============================================

def load_warnings():
    try:
        with open(WARNINGS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except:
        return {}


def save_warnings(data):
    with open(WARNINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except:
        return {
            "max_warnings": 5,
            "welcome_enabled": True,
            "log_channel_id": None
        }


def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


warnings = load_warnings()
settings = load_settings()


def contains_link(text: str) -> bool:
    if not text:
        return False
    return bool(LINK_PATTERN.search(text))


def is_bybit_link(text: str) -> bool:
    """Проверка на ссылку i.bybit.com"""
    if not text:
        return False
    return "i.bybit.com" in text.lower()


# ============================================
# КОМАНДЫ ДЛЯ АДМИНИСТРАТОРОВ
# ============================================

async def get_admins(chat_id):
    """Получить список ID администраторов чата"""
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
    
    text = "📊 <b>Статистика предупреждений</b>\n\n"
    for user_id, count in list(warnings.items())[:10]:
        text += f"👤 ID: {user_id} → {count}/{settings['max_warnings']}\n"
    
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("clear_warnings"))
async def clear_warnings_cmd(message: Message):
    if message.from_user.id not in await get_admins(message.chat.id):
        await message.answer("❌ Только для администраторов!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /clear_warnings @username или ID")
        return
    
    target = args[1]
    user_id = target.replace("@", "")
    
    if user_id in warnings:
        del warnings[user_id]
        save_warnings(warnings)
        await message.answer(f"✅ Предупреждения для {target} сброшены")
    else:
        await message.answer(f"❌ У {target} нет предупреждений")


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
        if new_max < 1 or new_max > 20:
            await message.answer("❌ Количество должно быть от 1 до 20")
            return
        
        settings["max_warnings"] = new_max
        save_settings(settings)
        await message.answer(f"✅ Максимум предупреждений изменён на {new_max}")
    except:
        await message.answer("❌ Введите число!")


@dp.message(Command("info"))
async def bot_info(message: Message):
    await message.answer(
        f"🤖 <b>Информация о боте</b>\n\n"
        f"📌 Разрешённая папка: {ALLOWED_THREAD_ID}\n"
        f"⚠️ Максимум предупреждений: {settings['max_warnings']}\n"
        f"📊 Активных предупреждений: {len(warnings)}\n"
        f"🕐 Время работы: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        parse_mode="HTML"
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        f"🛡️ <b>Бот-модератор ссылок</b>\n\n"
        f"<u>Правила:</u>\n"
        f"• В папке «ОБМЕННИК» ссылки РАЗРЕШЕНЫ\n"
        f"• Ссылки i.bybit.com разрешены ТОЛЬКО в папке «ОБМЕННИК»\n"
        f"• В остальных папках ссылки ЗАПРЕЩЕНЫ\n"
        f"• За {settings['max_warnings']} нарушений → блокировка\n\n"
        f"<u>Команды админов:</u>\n"
        f"/stats — статистика\n"
        f"/clear_warnings — сбросить предупреждения\n"
        f"/set_warnings — изменить лимит\n"
        f"/info — информация\n"
        f"/help — помощь",
        parse_mode="HTML"
    )


@dp.message(F.new_chat_members)
async def welcome_new_member(message: Message):
    if not settings.get("welcome_enabled", True):
        return
    
    for member in message.new_chat_members:
        if member.id == bot.id:
            continue
        
        await message.answer(
            f"👋 Добро пожаловать, {member.full_name}!\n\n"
            f"📌 <b>Правила чата:</b>\n"
            f"• Ссылки разрешены только в папке «ОБМЕННИК»\n"
            f"• Ссылки i.bybit.com — только в папке «ОБМЕННИК»\n"
            f"• За {settings['max_warnings']} нарушений → блокировка",
            parse_mode="HTML"
        )


# ============================================
# ОСНОВНАЯ ПРОВЕРКА ССЫЛОК
# ============================================

@dp.message()
async def check_links(message: Message):
    # Пропускаем команды
    if message.text and message.text.startswith('/'):
        return
    
    # Пропускаем ботов
    if message.from_user.is_bot:
        return
    
    if not message.text:
        return

    # Получаем ID темы
    thread_id = getattr(message, 'message_thread_id', None)
    
    # ============================================
    # ПРАВИЛО 1: Bybit ссылки (проверяем ПЕРВЫМИ!)
    # ============================================
    if is_bybit_link(message.text):
        # Если Bybit ссылка НЕ в папке ОБМЕННИК
        if thread_id != ALLOWED_THREAD_ID:
            await message.delete()
            
            user_id = str(message.from_user.id)
            
            # Добавляем предупреждение
            warnings[user_id] = warnings.get(user_id, 0) + 1
            save_warnings(warnings)
            
            attempts = warnings[user_id]
            max_warnings = settings.get("max_warnings", 5)
            
            await message.answer(
                f"⚠️ {message.from_user.full_name}, ордера разрешены только в разделе «ОБМЕННИК»\n"
                f"📌 Предупреждение: {attempts}/{max_warnings}"
            )
            
            # Проверяем на бан
            if attempts >= max_warnings:
                try:
                    await bot.ban_chat_member(
                        chat_id=message.chat.id,
                        user_id=message.from_user.id
                    )
                    await message.answer(
                        f"🚫 {message.from_user.full_name} был ЗАБЛОКИРОВАН\n"
                        f"📌 Причина: {max_warnings} нарушений"
                    )
                    warnings.pop(user_id, None)
                    save_warnings(warnings)
                except Exception as e:
                    print(f"Ошибка при блокировке: {e}")
            return
        else:
            # Bybit ссылка в папке ОБМЕННИК - разрешена
            return
    
    # ============================================
    # ПРАВИЛО 2: Обычные ссылки
    # ============================================
    
    # Проверяем наличие ссылки
    if not contains_link(message.text):
        return
    
    # Если это папка ОБМЕННИК - любые ссылки разрешены
    if thread_id == ALLOWED_THREAD_ID:
        return

    # ВСЕ ОСТАЛЬНЫЕ ПАПКИ - ссылки запрещены
    user_id = str(message.from_user.id)
    
    try:
        chat_member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if chat_member.status == 'kicked':
            return
    except:
        pass

    await message.delete()

    warnings[user_id] = warnings.get(user_id, 0) + 1
    save_warnings(warnings)

    attempts = warnings[user_id]
    max_warnings = settings.get("max_warnings", 5)

    if attempts < max_warnings:
        await message.answer(
            f"⚠️ {message.from_user.full_name}, ссылки здесь запрещены!\n"
            f"📌 Предупреждение: {attempts}/{max_warnings}"
        )
    else:
        try:
            await bot.ban_chat_member(
                chat_id=message.chat.id,
                user_id=message.from_user.id
            )
            await message.answer(
                f"🚫 {message.from_user.full_name} был ЗАБЛОКИРОВАН\n"
                f"📌 Причина: {max_warnings} нарушений"
            )
            warnings.pop(user_id, None)
            save_warnings(warnings)
        except Exception as e:
            print(f"Ошибка при блокировке: {e}")


# ============================================
# ЗАПУСК
# ============================================

async def set_commands():
    commands = [
        BotCommand(command="stats", description="📊 Статистика нарушений"),
        BotCommand(command="clear_warnings", description="🗑️ Сбросить предупреждения"),
        BotCommand(command="set_warnings", description="⚙️ Изменить лимит предупреждений"),
        BotCommand(command="info", description="ℹ️ Информация о боте"),
        BotCommand(command="help", description="🆘 Помощь"),
    ]
    await bot.set_my_commands(commands)


async def main():
    print("=" * 50)
    print("🚀 БОТ ЗАПУЩЕН")
    print(f"✅ Папка «ОБМЕННИК» (ID: {ALLOWED_THREAD_ID})")
    print("   → Любые ссылки РАЗРЕШЕНЫ")
    print("   → Ссылки i.bybit.com - только здесь")
    print(f"⚠️ Максимум предупреждений: {settings['max_warnings']}")
    print("❌ Во всех остальных папках ссылки ЗАПРЕЩЕНЫ")
    print("=" * 50)
    
    await set_commands()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())