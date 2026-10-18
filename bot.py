
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
ADMIN_ID = 1012040843
# ===================================

DB_PATH = Path(__file__).resolve().parent / "nfts_test.sqlite3"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nft-gif-test")

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


async def lottie_to_gif_file_id(slug):
    """使用 pyrlottie 将 Lottie JSON 转为 GIF 并上传获取 file_id"""
    try:
        from pyrlottie import convSingleLottie, LottieFile, FileMap, run
    except ImportError:
        raise RuntimeError("pyrlottie 未安装。请在 requirements.txt 中添加：pyrlottie")

    url = LOTTIE_URL.format(slug=slug)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise ValueError(f"Lottie 下载失败: HTTP {resp.status}")
            lottie_data = await resp.read()

    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = os.path.join(tmpdir, "anim.json")
        gif_path = os.path.join(tmpdir, "anim.gif")

        with open(json_path, "wb") as f:
            f.write(lottie_data)

        # pyrlottie 转换（单文件）
        run(
            convSingleLottie(
                FileMap(LottieFile(json_path), {gif_path}),
                1,  # 线程数
            )
        )

        if not os.path.exists(gif_path) or os.path.getsize(gif_path) == 0:
            raise RuntimeError("GIF 生成失败（可能 Lottie 格式不兼容 pyrlottie）")

        with open(gif_path, "rb") as gif_file:
            msg = await bot.send_animation(
                chat_id=ADMIN_ID,
                animation=gif_file,
                caption=f"测试 GIF: {slug}",
            )

        if not msg.animation:
            raise RuntimeError("Telegram 未返回 animation 对象")

        return msg.animation.file_id


def save_nft(data, gif_file_id, user_id):
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO nfts (slug, title, model, backdrop, symbol, page_url, gif_file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title=excluded.title,
                model=excluded.model,
                backdrop=excluded.backdrop,
                symbol=excluded.symbol,
                page_url=excluded.page_url,
                gif_file_id=excluded.gif_file_id
        """, (
            data["slug"], data["title"], data["model"],
            data["backdrop"], data["symbol"], data["page_url"], gif_file_id
        ))


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
        "🧪 <b>Тест GIF (pyrlottie)</b>\n\n"
        "Отправь ссылку на NFT:\n"
        "<code>https://t.me/nft/название-номер</code>",
        parse_mode="HTML",
    )


@dp.message(F.text)
async def handle_text(message: Message):
    slug = parse_slug(message.text or "")
    if not slug:
        await message.answer("❌ Отправь ссылку вида https://t.me/nft/xxx-1")
        return

    if not message.from_user or message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Только администратор.")
        return

    status = await message.answer("🔎 Получаю метаданные…")

    try:
        data = await fetch_metadata(slug)
        await status.edit_text("🎬 Конвертирую Lottie → GIF через pyrlottie…")

        gif_file_id = await lottie_to_gif_file_id(slug)
        save_nft(data, gif_file_id, message.from_user.id)

        await status.edit_text(
            f"✅ <b>成功！</b>\n\n"
            f"🎁 {html.escape(slug)}\n"
            f"🧩 Модель: {html.escape(data['model'] or '—')}\n"
            f"🎨 Фон: {html.escape(data['backdrop'] or '—')}\n"
            f"🔣 Pattern: {html.escape(data['symbol'] or '—')}\n\n"
            f"Теперь проверь inline-режим: @твой_бот",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.exception("失败: %s", slug)
        await status.edit_text(
            f"❌ <b>失败</b>\n\n"
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
    log.info("Бот @%s запущен, admin=%s", me.username, ADMIN_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
