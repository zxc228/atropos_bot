import asyncpg
import yt_dlp
import re
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, CallbackQuery
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import Config

TOKEN = Config.TOKEN
DB_PARAMS = Config.DB_PARAMS
CHANNEL_ID = Config.CHANNEL_ID

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

db_pool = None

async def set_commands(bot: Bot):
    commands = [
        types.BotCommand(command="start", description="Запустить бота"),
        types.BotCommand(command="save", description="Сохранить видео"),
        types.BotCommand(command="list", description="Посмотреть список видео"),
    ]
    await bot.set_my_commands(commands)

async def on_startup(dp):
    global db_pool
    db_pool = await asyncpg.create_pool(**DB_PARAMS)
    await set_commands(bot)

async def on_shutdown(dp):
    await db_pool.close()

def is_valid_youtube_url(url: str) -> bool:
    youtube_regex = re.compile(r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+$')
    return bool(youtube_regex.match(url))

def escape_markdown(text: str) -> str:
    """Экранирует спецсимволы для MarkdownV2."""
    escape_chars = r"*_[]()~`>#+-=|{}.!"
    return re.sub(r"([" + re.escape(escape_chars) + r"])", r"\\\1", text)

def get_video_title(url: str) -> str:
    try:
        ydl_opts = {"quiet": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("title", "Неизвестное видео")
    except Exception as e:
        print(f"Ошибка получения названия видео: {e}")
        return None

@dp.message_handler(commands=["start"])
async def start_command(message: Message):
    text = "👋 Привет! Я бот для сохранения YouTube-ссылок.\n\n" \
           "📌 *Доступные команды:*\n" \
           "/save - сохранить видео\n" \
           "/list - список видео"
    
    await message.reply(escape_markdown(text), parse_mode="MarkdownV2")

@dp.message_handler(commands=["save"])
async def save_video_step_1(message: Message):
    await message.reply("🔗 Отправь мне ссылку на YouTube-видео.")
    dp.register_message_handler(save_video_step_2, content_types=types.ContentType.TEXT)

async def save_video_step_2(message: Message):
    youtube_url = message.text.strip()

    if not is_valid_youtube_url(youtube_url):
        await message.reply("⚠ Это не похоже на ссылку YouTube! Попробуйте ещё раз.")
        return

    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM videos WHERE youtube_url = $1", youtube_url)

    if existing:
        await message.reply("⚠ Это видео уже есть в базе!")
        return

    title = get_video_title(youtube_url)

    if not title:
        await message.reply("⚠ Не удалось получить информацию о видео. Возможно, оно удалено или недоступно. Попробуйте другую ссылку.")
        return

    author = message.from_user.username or message.from_user.full_name

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO videos (youtube_url, title, author) VALUES ($1, $2, $3)",
                           youtube_url, title, author)

    text = f"✅ *Добавлено видео:*\n📌 {escape_markdown(title)}\n🔗 {escape_markdown(youtube_url)}\n👤 {escape_markdown(author)}"

    await message.reply(text, parse_mode="MarkdownV2")
    await bot.send_message(CHANNEL_ID, text, parse_mode="MarkdownV2")

@dp.message_handler(commands=["list"])
async def list_videos(message: Message, page: int = 1):
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM videos")
        rows = await conn.fetch("SELECT youtube_url, title, author FROM videos ORDER BY created_at DESC LIMIT 5 OFFSET $1", (page - 1) * 5)

    if not rows:
        await message.reply("😔 Нет сохранённых видео.")
        return

    text = f"📋 *Видео (страница {page} из {((count - 1) // 5) + 1}):*\n\n"
    for row in rows:
        text += f"🎥 *{escape_markdown(row['title'])}*\n🔗 {escape_markdown(row['youtube_url'])}\n👤 {escape_markdown(row['author'])}\n\n"

    keyboard = InlineKeyboardMarkup()
    if page > 1:
        keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data=f"list:{page - 1}"))
    if page * 5 < count:
        keyboard.add(InlineKeyboardButton("➡️ Вперёд", callback_data=f"list:{page + 1}"))

    await message.reply(escape_markdown(text), reply_markup=keyboard, parse_mode="MarkdownV2")

@dp.callback_query_handler(lambda c: c.data.startswith("list:"))
async def list_pagination(call: CallbackQuery):
    page = int(call.data.split(":")[1])
    await list_videos(call.message, page)
    await call.answer()

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
