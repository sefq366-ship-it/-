import asyncio
import html
import logging
import os
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineQuery, InlineQueryResultCachedGif, FSInputFile

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8977910657:AAFn1ZohJDaUFUDsE4ka2YBH85-ENak0HoE"
# ==============================

VERSION = "v1.8 (Gifski High Quality + Speed Fix)"
DB_PATH = Path(__file__).resolve().parent / "nfts.sqlite3"

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
                raise ValueError(f"Ошибка страницы: {resp.status}")
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
    try:
        from rlottie_python import LottieAnimation
        from PIL import Image
    except ImportError:
        raise RuntimeError("Установите rlottie-python[full] и Pillow")

    url = LOTTIE_URL.format(slug=slug)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise ValueError(f"Не удалось скачать Lottie: {resp.status}")
            lottie_data = await resp.read()

    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = os.path.join(tmpdir, "anim.json")
        gif_path = os.path.join(tmpdir, "anim.gif")

        # Сохраняем Lottie JSON в файл
        with open(json_path, "wb") as f:
            f.write(lottie_data)

        def _convert_with_gifski():
            anim = LottieAnimation.from_file(json_path)
            orig_w, orig_h = anim.lottie_animation_get_size()
            total_frames = anim.lottie_animation_get_totalframe()

            # 1. Фикс замедления: увеличиваем FPS в 2.5 раза
            original_fps = int(anim.lottie_animation_get_framerate())
            fps = min(int(original_fps * 2.5), 60)

            # 2. Увеличиваем размер для качества
            scale = 2
            out_w, out_h = int(orig_w * scale), int(orig_h * scale)

            frame_files = []
            for i in range(total_frames):
                frame_path = os.path.join(tmpdir, f"frame_{i:04d}.png")
                frame_img = anim.render_pillow_frame(frame_num=i, width=out_w, height=out_h)
                frame_img.save(frame_path, "PNG")
                frame_files.append(frame_path)

            anim.lottie_animation_destroy()

            # 3. Сборка gifski с максимальным качеством
            cmd = [
                "gifski",
                "-o", gif_path,
                "--fps", str(fps),
                "--quality", "95",   # Высокое качество
                "--extra",           # Доп. оптимизация качества
                *frame_files
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Gifski error: {result.stderr[:300]}")

        await asyncio.to_thread(_convert_with_gifski)

        if not os.path.exists(gif_path) or os.path.getsize(gif_path) == 0:
            raise RuntimeError("GIF не создан")

        gif_input = FSInputFile(gif_path, filename=f"{slug}.gif")
        msg = await bot.send_animation(chat_id=chat_id, animation=gif_input, caption=f"🎁 {slug}")
        if not msg.animation:
            raise RuntimeError("Telegram не вернул animation")
        return msg.animation.file_id


def save_nft(data, gif_file_id, user_id):
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO nfts (slug, title, model, backdrop, symbol, page_url, gif_file_id, added_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title=excluded.title, model=excluded.model, backdrop=excluded.backdrop,
                symbol=excluded.symbol, page_url=excluded.page_url, gif_file_id=excluded.gif_file_id,
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
    me = await bot.get_me()
    await message.answer(
        f"🎁 <b>NFT GIF Bot</b>\n"
        f"<i>{VERSION}</i>\n\n"
        "Отправь ссылку на NFT:\n"
        "<code>https://t.me/nft/название-номер</code>\n\n"
        f"Потом ищи в любом чате: <code>@{me.username}</code>",
        parse_mode="HTML",
    )


@dp.message(F.text)
async def handle_text(message: Message):
    slug = parse_slug(message.text or "")
    if not slug:
        await message.answer("❌ Отправь ссылку вида https://t.me/nft/xxx-1")
        return

    existing = get_nft(slug)
    if existing and existing.get("gif_file_id"):
        await message.answer_animation(
            animation=existing["gif_file_id"],
            caption=format_caption(existing),
            parse_mode="HTML",
        )
        return

    status = await message.answer("🔎 Получаю данные…")
    try:
        data = await fetch_metadata(slug)
        await status.edit_text("🎬 Рендерю кадры и собираю GIF (Gifski Extra Quality)…")

        gif_file_id = await lottie_to_gif_file_id(slug, message.chat.id)
        save_nft(data, gif_file_id, message.from_user.id if message.from_user else 0)

        me = await bot.get_me()
        await status.edit_text(
            f"✅ <b>Готово!</b>\n\n"
            f"🎁 {html.escape(slug)}\n"
            f"🧩 Модель: {html.escape(data['model'] or '—')}\n"
            f"🎨 Фон: {html.escape(data['backdrop'] or '—')}\n"
            f"🔣 Pattern: {html.escape(data['symbol'] or '—')}\n\n"
            f"Теперь ищи в inline-режиме: @{me.username}",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.exception("Ошибка %s", slug)
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
    log.info("Бот @%s запущен, версия %s", me.username, VERSION)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
