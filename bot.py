
import asyncio
import html
import logging
import os
import re
import sqlite3
import tempfile
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineQuery, InlineQueryResultCachedGif

# ========== 需要修改的配置 ==========
BOT_TOKEN = "8977910657:AAFn1ZohJDaUFUDsE4ka2YBH85-ENak0HoE"
# ===================================

DB_PATH = Path(__file__).resolve().parent / "nfts_test.sqlite3"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nft-gif-bot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

NFT_URL_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/nft/([A-Za-z0-9_-]+)", re.I)
LOTTIE_URL = "https://nft.fragment.com/gift/{slug}.lottie.json"


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nfts (
                slug TEXT PRIMARY KEY,
                title TEXT,
                model TEXT,
                backdrop TEXT,
                symbol TEXT,
                page_url TEXT,
                gif_file_id TEXT,
                added_by INTEGER,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def parse_slug(text):
    m = NFT_URL_RE.search(text or "")
    return m.group(1) if m else None


def clean_html(value):
    return " ".join(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True).split())


async def fetch_metadata(slug):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(f"https://t.me/nft/{slug}") as resp:
            if resp.status != 200:
                raise ValueError(f"页面返回 HTTP {resp.status}")
            page = await resp.text()

    soup = BeautifulSoup(page, "html.parser")
    fields = {"model": "", "backdrop": "", "symbol": ""}

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        key = clean_html(str(cells[0])).lower().rstrip(":")
        val = clean_html(str(cells[1]))
        if key in fields and val:
            fields[key] = val

    return {
        "slug": slug,
        "title": slug,
        "model": fields["model"],
        "backdrop": fields["backdrop"],
        "symbol": fields["symbol"],
        "page_url": f"https://t.me/nft/{slug}",
    }


async def lottie_to_gif_file_id(slug, chat_id):
    """Скачать Lottie → конвертировать в GIF через pyrlottie → отправить → вернуть file_id."""
    try:
        from pyrlottie import convSingleLottie, LottieFile, FileMap, run
    except ImportError:
        raise RuntimeError("pyrlottie не установлен. Добавь в requirements.txt: pyrlottie")

    url = LOTTIE_URL.format(slug=slug)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise ValueError(f"Не удалось скачать Lottie: HTTP {resp.status}")
            lottie_data = await resp.read()

    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = os.path.join(tmpdir, "anim.json")
        gif_path = os.path.join(tmpdir, "anim.gif")

        with open(json_path, "wb") as f:
            f.write(lottie_data)

        # pyrlottie.run — синхронная блокирующая функция со своим event loop.
        # Запускаем её в отдельном потоке, чтобы не конфликтовать с aiogram.
        await asyncio.to_thread(
            run,
            convSingleLottie(
                FileMap(LottieFile(json_path), {gif_path}),
                1,
            ),
        )

        if not os.path.exists(gif_path) or os.path.getsize(gif_path) == 0:
            raise RuntimeError("GIF не создан (возможно, Lottie несовместим с pyrlottie)")

        with open(gif_path, "rb") as gif_file:
            msg = await bot.send_animation(
                chat_id=chat_id,
                animation=gif_file,
                caption=f"🎁 {slug}",
            )

        if not msg.animation:
            raise RuntimeError("Telegram не вернул animation")

        return msg.animation.file_id


def save_nft(data, gif_file_id, user_id):
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO nfts (slug, title, model, backdrop, symbol, page_url, gif_file_id, added_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title=excluded.title,
                model=excluded.model,
                backdrop=excluded.backdrop,
                symbol=excluded.symbol,
                page_url=excluded.page_url,
                gif_file_id=excluded.gif_file_id,
                added_by=excluded.added_by
        """, (
            data["slug"], data["title"], data["model"], data["backdrop"],
            data["symbol"], data["page_url"], gif_file_id, user_id
        ))


def get_nft(slug):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM nfts WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None


def get_nfts(query="", limit=50):
    with db_connect() as conn:
        if query.strip():
            q = f"%{query.strip()}%"
            rows = conn.execute("""
                SELECT * FROM nfts
                WHERE slug LIKE ? OR model LIKE ? OR backdrop LIKE ? OR symbol LIKE ?
                ORDER BY added_at DESC LIMIT ?
            """, (q, q, q, q, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM nfts ORDER BY added_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


def format_caption(nft):
    return (
        f"<b>🎁 {html.escape(nft['slug'])}</b>\n\n"
        f"🧩 <b>Модель:</b> {html.escape(nft.get('model') or '—')}\n"
        f"🎨 <b>Фон:</b> {html.escape(nft.get('backdrop') or '—')}\n"
        f"🔣 <b>Pattern:</b> {html.escape(nft.get('symbol') or '—')}\n\n"
        f"<a href=\"{html.escape(nft['page_url'])}\">Открыть NFT</a>"
    )


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🎁 <b>NFT GIF Bot</b>\n\n"
        "Отправь ссылку на NFT-подарок:\n"
        "<code>https://t.me/nft/название-номер</code>\n\n"
        "Бот скачает анимацию, конвертирует в GIF и сохранит.\n"
        "Потом ищи в любом чате: <code>@этот_бот</code>\n\n"
        "Отправлять NFT может любой пользователь.",
        parse_mode="HTML",
    )


@dp.message(F.text)
async def handle_text(message: Message):
    slug = parse_slug(message.text or "")
    if not slug:
        await message.answer("❌ Отправь ссылку вида https://t.me/nft/xxx-1")
        return

    # Если уже есть в базе с GIF — сразу отдаём
    existing = get_nft(slug)
    if existing and existing.get("gif_file_id"):
        await message.answer_animation(
            animation=existing["gif_file_id"],
            caption=format_caption(existing),
            parse_mode="HTML",
        )
        return

    status = await message.answer("🔎 Получаю данные NFT…")

    try:
        data = await fetch_metadata(slug)
        await status.edit_text("🎬 Конвертирую Lottie → GIF…")

        gif_file_id = await lottie_to_gif_file_id(slug, message.chat.id)
        save_nft(data, gif_file_id, message.from_user.id if message.from_user else 0)

        await status.edit_text(
            f"✅ <b>Готово!</b>\n\n"
            f"🎁 {html.escape(slug)}\n"
            f"🧩 Модель: {html.escape(data['model'] or '—')}\n"
            f"🎨 Фон: {html.escape(data['backdrop'] or '—')}\n"
            f"🔣 Pattern: {html.escape(data['symbol'] or '—')}\n\n"
            f"Теперь ищи в inline-режиме: @{(await bot.get_me()).username}",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.exception("Не удалось обработать %s", slug)
        await status.edit_text(
            f"❌ <b>Не удалось</b>\n\n"
            f"<code>{html.escape(str(exc)[:500])}</code>",
            parse_mode="HTML",
        )


@dp.inline_query()
async def inline_search(query: InlineQuery):
    items = get_nfts(query.query.strip(), limit=50)
    results = []

    for nft in items:
        if not nft.get("gif_file_id"):
            continue
        results.append(
            InlineQueryResultCachedGif(
                id=nft["slug"],
                gif_file_id=nft["gif_file_id"],
                caption=format_caption(nft),
                parse_mode="HTML",
            )
        )

    await query.answer(results=results, cache_time=1, is_personal=True)


async def main():
    init_db()
    me = await bot.get_me()
    log.info("Бот @%s запущен", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
