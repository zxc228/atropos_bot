import asyncio
from aiogram import Bot
from config import Config

async def get_chat_id():
    bot = Bot(token=Config.TOKEN)
    chat = await bot.get_chat("@linkforz")  # Замени на @username канала
    print(f"Chat ID: {chat.id}")
    await bot.session.close()

asyncio.run(get_chat_id())
