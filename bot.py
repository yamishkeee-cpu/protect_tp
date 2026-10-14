import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from handlers import router

# 1. Токен бота берём из переменной окружения BOT_TOKEN (не храним в коде)
BOT_TOKEN = "8860516710:AAFm6Jpj3-JncapVqjtzzhrPpvwggzqbsY0"
if not BOT_TOKEN:
    raise SystemExit("Не задан BOT_TOKEN. Запуск: BOT_TOKEN=<токен от @BotFather> python bot.py")

# Все сообщения отправляются с HTML-разметкой (<b>жирный</b>)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==================== ЗАПУСК БОТА ====================
async def main():
    dp.include_router(router)
    print("Бот запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
