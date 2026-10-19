import asyncio
import html
import logging
import math
import shutil
import sqlite3
import subprocess
import tempfile
import re

from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup
from PIL import Image

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    InlineQuery,
    InlineQueryResultCachedGif,
    InlineQueryResultCachedMpeg4Gif,
    FSInputFile,
)
from aiogram.exceptions import TelegramUnauthorizedError

BOT_TOKEN = "ВСТАВЬ_СВОЙ_ТОКЕН_СЮДА"

VERSION = "v5.1 Fast MP4"
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "nfts.sqlite3"

MAX_RENDER_DIMENSION = 1024
MAX_FPS = 60
FRAME_SKIP = 1
MP4_CRF = 20
MP4_PRESET = "veryfast"
MP4_PIX_FMT = "yuv420p"
MAX_CONCURRENT_RENDERS = 1
DOWNLOAD_TIMEOUT = 120
RENDER_TIMEOUT = 600
MAX_LOTTIE_SIZE = 100 * 1024 * 1024

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("nft-gif-bot")

if not BOT_TOKEN or BOT_TOKEN == "ВСТАВЬ_СВОЙ_ТОКЕН_СЮДА":
    raise RuntimeError("Не указан BOT_TOKEN.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
render_semaphore = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)
slug_locks = {}

NFT_URL_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/nft/([A-Za-z0-9_-]+)", re.I)
LOTTIE_URL = "https://nft.fragment.com/gift/{slug}.lottie.json"

# Разбиваем User-Agent на кусочки, чтобы телефон не сломал строку
UA_PART_1 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
UA_PART_2 = "AppleWebKit/537.36 (KHTML, like Gecko) "
UA_PART_3 = "Chrome/131.0 Safari/537.36"
USER_AGENT = UA_PART_1 + UA_PART_2 + UA_PART_3

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with db_connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        sql = "CREATE TABLE IF NOT EXISTS nfts ("
        sql += "slug TEXT PRIMARY KEY, "
        sql += "title TEXT, "
        sql += "model TEXT, "
        sql += "backdrop TEXT, "
        sql += "symbol TEXT, "
        sql += "page_url TEXT, "
        sql += "gif_file_id TEXT, "
        sql += "mpeg4_file_id TEXT, "
        sql += "added_by INTEGER, "
        sql += "added_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        conn.execute(sql)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(nfts)").fetchall()}
        if "mpeg4_file_id" not in cols:
            conn.execute("ALTER TABLE nfts ADD COLUMN mpeg4_file_id TEXT")
        conn.commit()

def parse_slug(text):
    match = NFT_URL_RE.search(text or "")
    return match.group(1) if match else None

def clean_html(value):
    return " ".join(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True).split())

def save_nft(data, gif_file_id, mpeg4_file_id, user_id):
    with db_connect() as conn:
        s = data["slug"]
        t = data["title"]
        m = data["model"]
        b = data["backdrop"]
        sy = data["symbol"]
        u = data["page_url"]
        
        sql = "INSERT INTO nfts (slug, title, model, backdrop, symbol, "
        sql += "page_url, gif_file_id, mpeg4_file_id, added_by) "
        sql += "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        sql += "ON CONFLICT(slug) DO UPDATE SET title=excluded.title, "
        sql += "model=excluded.model, backdrop=excluded.backdrop, "
        sql += "symbol=excluded.symbol, page_url=excluded.page_url, "
        sql += "added_by=excluded.added_by"
        
        conn.execute(sql, (s, t, m, b, sy, u, gif_file_id, mpeg4_file_id, user_id))
        conn.commit()

def get_nft(slug):
    with db_connect() as conn:
        q = "SELECT * FROM nfts WHERE slug = ?"
        row = conn.execute(q, (slug,)).fetchone()
    return dict(row) if row else None

def get_nfts(query="", limit=50):
    with db_connect() as conn:
        if query.strip():
            q = f"%{query.strip()}%"
            sql = "SELECT * FROM nfts WHERE slug LIKE ? OR model LIKE ? "
            sql += "OR backdrop LIKE ? OR symbol LIKE ? "
            sql += "ORDER BY added_at DESC LIMIT ?"
            rows = conn.execute(sql, (q, q, q, q, limit)).fetchall()
        else:
            sql = "SELECT * FROM nfts ORDER BY added_at DESC LIMIT ?"
            rows = conn.execute(sql, (limit,)).fetchall()
    return [dict(row) for row in rows]

async def fetch_metadata(slug):
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        url = f"https://t.me/nft/{slug}"
        async with session.get(url) as resp:
            if resp.status != 200:
                raise ValueError(f"Ошибка страницы NFT: HTTP {resp.status}")
            page = await resp.text()

    soup = BeautifulSoup(page, "html.parser")
    fields = {"model": "", "backdrop": "", "symbol": ""}

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        key = clean_html(str(cells[0])).lower().rstrip(":")
        value = clean_html(str(cells[1]))
        if key in fields and value:
            fields[key] = value

    return {
        "slug": slug,
        "title": slug,
        "model": fields["model"],
        "backdrop": fields["backdrop"],
        "symbol": fields["symbol"],
        "page_url": f"https://t.me/nft/{slug}",
    }

def check_ffmpeg():
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("Не найден ffmpeg.")
    return executable

async def download_lottie(slug, output_path):
    url = LOTTIE_URL.format(slug=slug)
    timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT, connect=20, sock_read=60)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise ValueError(f"Ошибка загрузки Lottie: HTTP {resp.status}")
            data = await resp.read()

    if not data:
        raise RuntimeError("Сервер вернул пустую Lottie.")
    if len(data) > MAX_LOTTIE_SIZE:
        raise RuntimeError("Исходная Lottie превышает размер.")

    output_path.write_bytes(data)
    log.info("Lottie загружена: %s, %.2f МБ", slug, len(data) / 1024 / 1024)

def convert_lottie_to_mp4_sync(json_path, mp4_path, work_dir):
    try:
        from rlottie_python import LottieAnimation
    except ImportError as exc:
        raise RuntimeError("Не установлена rlottie-python.") from exc

    ffmpeg = check_ffmpeg()
    anim = None

    try:
        anim = LottieAnimation.from_file(str(json_path))
        
        orig_w, orig_h = anim.lottie_animation_get_size()
        orig_w, orig_h = int(orig_w), int(orig_h)
        total_frames = int(       anim.lottie_animation_get_totalframe())
        original_fps = float(anim.lottie_animation_get_framerate())

        if orig_w <= 0 or orig_h <= 0 or total_frames <= 0:
            raise RuntimeError("Некорректные размеры или нет кадров.")

        frames_to_render = range(0, total_frames, FRAME_SKIP)
        num_rendered_frames = len(frames_to_render)
        
        fps }

 = max(1, min(math.ceil(original   _fps / FRAME_SKIP), MAX_FPS finally))

        scale = MAX_RENDER_DIM:
ENSION / max(orig_w, orig_h)
        out       _w = max(2, round(orig_w * scale))
        out_h = max(2, round(orig_h * scale))
        
        out_w = out_w if out_w % 2 == 0 else out_w - 1
        out_h = out_h if out_h % 2 == 0 else out_h - 1

        log.info("Рендеринг: %sx%s -> %sx%s, кадров: %s", orig_w, orig_h, out_w, out_h, num_rendered_frames)

        frames_dir = work_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        for idx, i in enumerate(frames_to_render):
            frame_path = frames_dir / f"frame_{idx:06d}.png"
            frame_img = anim.render_pillow_frame(frame_num=i, width=out_w, height=out_h)
            
            try:
                frame_img.save(str(frame_path), format="PNG", compress_level=1)
            finally:
                close_method = getattr(frame_img, "close", None)
                if callable(close_method):
                    close_method()

        destroy = getattr(anim, "lottie_animation_destroy", None)
        if callable(destroy):
            destroy()
        anim = None

        cmd = [
            ffmpeg, "-y",
            "-framerate", str(fps),
            "-i", str(frames_dir / "frame_%06d.png"),
            "-an",
            "-c:v", "libx264",
            "-preset", MP4_PRESET,
            "-crf", str(MP4_CRF),
            "-pix_fmt", MP4_PIX_FMT,
            "-movflags", "+faststart",
            str(mp4_path)
        ]

        log.info("Кодирование MP4...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT)

        if result.returncode != 0:
            raise RuntimeError(f"Ошибка ffmpeg: {result.stderr[-1000:]}")

        log.info("MP4 готов: %.2f МБ", mp4_path.stat().st_size / 1024 / 1024)

        return {
            "width": out_w,
            "height": out_h,
            "frames": num_rendered_frames,
            "fps": fps,
            "size": mp4_path.stat().st_size,
 if anim is not None:
            destroy = getattr(anim, "lottie_animation_destroy", None)
            if callable(destroy):
                try:
                    destroy()
                except Exception:
                    pass

async def lottie_to_file_ids(slug, chat_id):
    async with render_semaphore:
        with tempfile.TemporaryDirectory(prefix="nft_mp4_") as tmp:
            work_dir = Path(tmp)
            json_path = work_dir / "anim.json"
            mp4_path = work_dir / "anim.mp4"

            await download_lottie(slug, json_path)

            info = await asyncio.to_thread(
                convert_lottie_to_mp4_sync,
                json_path,
                mp4_path,
                work_dir,
            )

            mpeg4_file_id = None
            gif_file_id = None

            log.info("Отправка MP4 в Telegram: %s", slug)
            try:
                msg = await bot.send_animation(
                    chat_id=chat_id,
                    animation=FSInputFile(str(mp4_path), filename=f"{slug}.mp4"),
                    caption=f"NFT: {slug}",
                )
                if msg.animation:
                    mpeg4_file_id = msg.animation.file_id
            except Exception:
                log.exception("send_animation(MP4) не удался: %s", slug)

            return gif_file_id, mpeg4_file_id

def format_caption(nft):
    slug = html.escape(nft.get("slug") or "")
    model = html.escape(nft.get("model") or "—")
    backdrop = html.escape(nft.get("backdrop") or "—")
    symbol = html.escape(nft.get("symbol") or "—")
    page_url = html.escape(nft.get("page_url") or "", quote=True)

    text = f"<b>🎁 {slug}</b>\n\n"
    text += f"🧩 <b>Модель:</b> {model}\n"
    text += f"🎨 <b>Фон:</b> {backdrop}\n"
    text += f"🔣 <b>Pattern:</b> {symbol}\n\n"
    text += f'<a href="{page_url}">Открыть NFT</a>'
    return text

@dp.message(CommandStart())
async def start(message: Message):
    me = await bot.get_me()
    text = f"🎁 <b>NFT GIF Bot</b>\n<i>{VERSION}</i>\n\n"
    text += "Отправь ссылку на NFT:\n"
    text += "<code>https://t.me/nft/название-номер</code>\n\n"
    text += f"Inline-поиск: <code>@{me.username}</code>"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text)
async def handle_text(message: Message):
    slug = parse_slug(message.text or "")
    if not slug:
        await message.answer("❌ Отправь ссылку вида:\nhttps://t.me/nft/название-номер")
        return

    lock = slug_locks.setdefault(slug, asyncio.Lock())

    async with lock:
        existing = get_nft(slug)
        if existing and existing.get("mpeg4_file_id"):
            try:
                await message.answer_animation(
                    animation=existing["mpeg4_file_id"],
                    caption=format_caption(existing),
                    parse_mode="HTML",
                )
                return
            except Exception:
                log.exception("Ошибка отправки из кэша: %s", slug)

        status = await message.answer("🔎 Получаю информацию об NFT...")

        try:
            data = await fetch_metadata(slug)
            await status.edit_text("🎬 Создаю быструю MP4-анимацию...\nПожалуйста, подожди.")

            gif_file_id, mpeg4_file_id = await lottie_to_file_ids(slug, message.chat.id)
            
            uid = message.from_user.id if message.from_user else 0
            save_nft(data, gif_file_id, mpeg4_file_id, uid)

            me = await bot.get_me()
            success_text = f"✅ <b>Готово!</b>\n\n"
            success_text += f"🎁 {html.escape(slug)}\n"
            success_text += f"🧩 Модель: {html.escape(data['model'] or '—')}\n"
            success_text += f"🎨 Фон: {html.escape(data['backdrop'] or '—')}\n"
            success_text += f"🔣 Pattern: {html.escape(data['symbol'] or '—')}\n\n"
            success_text += f"Версия: {VERSION}\n"
            success_text += f"Inline-поиск: <code>@{me.username}</code>"
            await status.edit_text(success_text, parse_mode="HTML")

        except Exception as exc:
            log.exception("Ошибка обработки NFT %s", slug)
            try:
                err_text = f"❌ <b>Ошибка обработки NFT</b>\n\n"
                err_text += f"<code>{html.escape(str(exc)[:1200])}</code>"
                await status.edit_text(err_text, parse_mode="HTML")
            except Exception:
                pass
        finally:
            if slug_locks.get(slug) is lock:
                slug_locks.pop(slug, None)

@dp.inline_query()
async def inline_query_handler(query: InlineQuery):
    search = (query.query or "").strip()
    items = get_nfts(search, limit=50)
    results = []

    for nft in items:
        if nft.get("mpeg4_file_id"):
            results.append(
                InlineQueryResultCachedMpeg4Gif(
                    id=nft["slug"],
                    mpeg4_file_id=nft["mpeg4_file_id"],
                    caption=format_caption(nft),
                    parse_mode="HTML",
                )
            )
            continue
        if nft.get("gif_file_id"):
            results.append(
                InlineQueryResultCachedGif(
                    id=nft["slug"],
                    gif_file_id=nft["gif_file_id"],
                    caption=format_caption(nft),
                    parse_mode="HTML",
                )
            )

    try:
        await query.answer(results=results, cache_time=1, is_personal=True)
    except Exception:
        log.exception("Ошибка ответа на inline query")

async def main():
    init_db()
    log.info("Проверяю подключение к Telegram...")
    try:
        check_ffmpeg()
        me = await bot.get_me()
        log.info("Авторизация успешна. Бот @%s", me.username)
        log.info("Версия: %s", VERSION)

        await dp.start_polling(bot, close_bot_session=False)

    except TelegramUnauthorizedError:
        log.critical("Telegram отклонил токен. Проверь BOT_TOKEN.")
        raise
    finally:
        await bot.session.close()
        log.info("Сессия Telegram закрыта.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Бот остановлен.")
