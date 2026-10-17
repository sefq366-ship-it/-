import asyncio
import html
import logging
import re
import sqlite3
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineQuery, InlineQueryResultPhoto

# ==========================================================
# 1) ВСТАВЬ НОВЫЙ ТОКЕН МЕЖДУ КАВЫЧКАМИ НИЖЕ.
# Старый токен, который уже отправлялся в чат, сначала отзови
# в @BotFather командой /revoke.
# ==========================================================
BOT_TOKEN = "8977910657:AAFn1ZohJDaUFUDsE4ka2YBH85-ENak0HoE"
ADMIN_ID = 1012040843

# База данных создаётся рядом с этим файлом.
# Если Bothost имеет постоянное хранилище, можно указать его путь,
# например: DB_PATH = Path("/путь/к/persistent/nfts.sqlite3")
DB_PATH = Path(__file__).resolve().parent / "nfts.sqlite3"

if BOT_TOKEN == "ВСТАВЬ_СЮДА_НОВЫЙ_ТОКЕН" or not BOT_TOKEN.strip():
    raise RuntimeError("Открой main.py и вставь токен в BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("nft-bot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

NFT_URL_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/nft/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


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
                description TEXT,
                page_url TEXT NOT NULL,
                photo_url TEXT NOT NULL,
                added_by INTEGER,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def parse_slug(text):
    match = NFT_URL_RE.search(text or "")
    return match.group(1) if match else None


def clean_html(value):
    return " ".join(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True).split())


def extract_metadata(page, slug):
    soup = BeautifulSoup(page, "html.parser")
    description = ""

    meta = soup.find("meta", attrs={"name": re.compile(r"^twitter:description$", re.I)})
    if meta and meta.get("content"):
        description = html.unescape(meta["content"]).strip()

    if not description:
        meta = soup.find("meta", attrs={"property": "og:description"})
        if meta and meta.get("content"):
            description = html.unescape(meta["content"]).strip()

    fields = {"model": "", "backdrop": "", "symbol": ""}
    for key, label in (("model", "Model"), ("backdrop", "Backdrop"), ("symbol", "Symbol")):
        pattern = (
            rf"{label}:\s*(.*?)"
            rf"(?=\s+(?:Model|Backdrop|Symbol|Comment|Owner|Quantity):|$)"
        )
        found = re.search(pattern, description, re.I)
        if found:
            fields[key] = found.group(1).strip()

    # Попытка извлечь характеристики из HTML-таблицы.
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        key = clean_html(str(cells[0])).lower().rstrip(":")
        value = clean_html(str(cells[1]))
        if key in fields and value:
            fields[key] = value

    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = html.unescape(og_title["content"]).strip()
    if not title:
        title_tag = soup.find("title")
        title = clean_html(str(title_tag)) if title_tag else slug

    return {
        "slug": slug,
        "title": title,
        "model": fields["model"],
        "backdrop": fields["backdrop"],
        "symbol": fields["symbol"],
        "description": description,
        "page_url": f"https://t.me/nft/{slug}",
        "photo_url": f"https://nft.fragment.com/gift/{slug}.small.jpg",
    }


async def fetch_nft(slug):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
        )
    }
    timeout = aiohttp.ClientTimeout(total=25)

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(f"https://t.me/nft/{slug}", allow_redirects=True) as response:
            if response.status != 200:
                raise ValueError(f"Страница NFT вернула HTTP {response.status}")
            page = await response.text()

        data = extract_metadata(page, slug)

        # Проверяем, что миниатюра Fragment действительно доступна.
        async with session.get(data["photo_url"]) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if response.status != 200 or not content_type.startswith("image/"):
                raise ValueError(
                    "Не удалось получить миниатюру Fragment. "
                    "Проверь ссылку или попробуй позже."
                )
        return data


def save_nft(data, user_id):
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO nfts
            (slug, title, model, backdrop, symbol, description,
             page_url, photo_url, added_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title=excluded.title,
                model=excluded.model,
                backdrop=excluded.backdrop,
                symbol=excluded.symbol,
                description=excluded.description,
                page_url=excluded.page_url,
                photo_url=excluded.photo_url,
                added_by=excluded.added_by
        """, (
            data["slug"], data["title"], data["model"], data["backdrop"],
            data["symbol"], data["description"], data["page_url"],
            data["photo_url"], user_id
        ))


def get_nfts(query="", limit=50):
    with db_connect() as conn:
        if query.strip():
            q = f"%{query.strip()}%"
            rows = conn.execute("""
                SELECT * FROM nfts
                WHERE slug LIKE ? OR title LIKE ? OR model LIKE ?
                   OR backdrop LIKE ? OR symbol LIKE ?
                ORDER BY added_at DESC LIMIT ?
            """, (q, q, q, q, q, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM nfts ORDER BY added_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(row) for row in rows]


def format_caption(nft):
    slug = html.escape(nft.get("slug") or "")
    model = html.escape(nft.get("model") or "Не найдено")
    backdrop = html.escape(nft.get("backdrop") or "Не найдено")
    symbol = html.escape(nft.get("symbol") or "Не найдено")
    page_url = html.escape(nft.get("page_url") or "https://t.me")
    return (
        f"<b>🎁 {slug}</b>\n\n"
        f"🧩 <b>Модель:</b> {model}\n"
        f"🎨 <b>Фон:</b> {backdrop}\n"
        f"🔣 <b>Pattern:</b> {symbol}\n\n"
        f"<a href=\"{page_url}\">Открыть NFT</a>"
    )


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет! 🎁\n\n"
        "Отправь ссылку на NFT-подарок, например:\n"
        "<code>https://t.me/nft/astralshard-1</code>\n\n"
        "После сохранения ищи его в любом чате:\n"
        "<code>@ИмяБота</code> — все сохранённые NFT\n"
        "<code>@ИмяБота astralshard-1</code> — поиск по запросу.\n\n"
        "Добавлять NFT может только администратор.",
        parse_mode="HTML",
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await start(message)


@dp.message(F.text)
async def handle_text(message: Message):
    slug = parse_slug(message.text or "")
    if not slug:
        await message.answer("Отправь ссылку вида https://t.me/nft/название-номер")
        return

    if not message.from_user or message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Добавлять NFT может только администратор.")
        return

    status = await message.answer("🔎 Получаю данные NFT…")
    try:
        data = await fetch_nft(slug)
        save_nft(data, message.from_user.id)
        await status.edit_text(
            "✅ <b>Готово! NFT сохранён.</b>\n\n"
            f"🎁 {html.escape(slug)}\n"
            f"🧩 Модель: {html.escape(data['model'] or 'не найдена')}\n"
            f"🎨 Фон: {html.escape(data['backdrop'] or 'не найден')}\n"
            f"🔣 Pattern: {html.escape(data['symbol'] or 'не найден')}\n\n"
            "Теперь найди его через Inline Mode.",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.exception("Не удалось сохранить NFT %s", slug)
        await status.edit_text(
            "❌ Не удалось сохранить NFT.\n"
            f"<code>{html.escape(str(exc)[:400])}</code>",
            parse_mode="HTML",
        )


@dp.inline_query()
async def inline_search(query: InlineQuery):
    search_text = (query.query or "").strip()
    items = get_nfts(search_text, limit=50)
    results = []

    for nft in items:
        slug = nft["slug"]
        results.append(
            InlineQueryResultPhoto(
                id=slug,
                photo_url=nft["photo_url"],
                thumbnail_url=nft["photo_url"],
                title=nft.get("title") or slug,
                description=(
                    f"Модель: {nft.get('model') or '—'} | "
                    f"Фон: {nft.get('backdrop') or '—'} | "
                    f"Pattern: {nft.get('symbol') or '—'}"
                )[:250],
                caption=format_caption(nft),
                parse_mode="HTML",
            )
        )

    await query.answer(results=results, cache_time=1, is_personal=True)


async def main():
    init_db()
    me = await bot.get_me()
    log.info("Бот запущен: @%s; admin_id=%s; database=%s", me.username, ADMIN_ID, DB_PATH)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
