import asyncio
from aiogram import Bot, Dispatcher, Router, types

# 1. Токен вашего бота, полученный от @BotFather
BOT_TOKEN = "8803078943:AAF3RdQmYCeZqP_Z_kIYsGEBIk-IKoauQVc"

# Инициализируем бота, диспетчер и роутер
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()


# 2. Создаем функцию-обработчик сообщений
# Декоратор проверяет, что текст сообщения в нижнем регистре равен "привет"
@router.message(lambda message: message.text and message.text.lower() == "привет")
async def answer_hello(message: types.Message):
    # Бот отвечает пользователю
    await message.answer("Привет!")


# 3. Главная функция для запуска бота
async def main():
    # Регистрируем наш роутер в диспетчере
    dp.include_router(router)

    print("Бот запущен и готов к работе...")
    # Запускаем постоянный опрос серверов Telegram (Polling)
    await dp.start_polling(bot)


if __name__ == "__main__":
    # Запуск асинхронного кода
    asyncio.run(main())
