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

# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = "8977910657:AAG9zbaj4CK-39uNSp0VAA_1yEiH5cb_wQE"

VERSION = "v4.2 MP4 Inline (system ffmpeg)"

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "nfts.sqlite3"

# Максимальная сторона ИТОГОВОГО изображения.
MAX_RENDER_DIMENSION = 1024

# Максимальная частота воспроизведения.
MAX_FPS = 60

# Ограничение длительности. 0 = без ограничения.
MAX_DURATION_SECONDS = 0

# Качество Gifski.
GIF_QUALITY = 100
GIF_MOTION_QUALITY = 100
GIF_LOSSY_QUALITY = 100

# Дополнительное усилие сжатия gifski.
GIF_EXTRA_COMPRESSION = True

# Суперсэмплинг.
SSAA_FACTOR = 2
SSAA_MAX_DIMENSION = 4096

# --- MP4 / ffmpeg ---
# CRF для x264: меньше = лучше качество, больше = меньше файл.
MP4_CRF = 17
# preset x264.
MP4_PRESET = "slow"
# Профиль и уровень H.264.
MP4_PROFILE = "high"
MP4_LEVEL = "4.2"
# Пиксельный формат (обязателен для совместимости).
MP4_PIX_FMT = "yuv420p"

# Отправлять в чат MP4 как анимацию + оригинальный GIF документом.
SEND_ANIMATION_MP4 = True
SEND_ORIGINAL_AS_DOCUMENT = True

# Одновременные конвертации.
MAX_CONCURRENT_RENDERS = 1

# Тайм-ауты.
DOWNLOAD_TIMEOUT = 120
RENDER_TIMEOUT = 1800
FFMPEG_TIMEOUT = 1800

MAX_LOTTIE_SIZE = 100 * 1024 * 1024
MAX_GIF_SIZE_BYTES = 0

# ============================================================
# ЛОГИРОВАНИЕ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

log = logging.getLogger("nft-gif-bot")

# ============================================================
# TELEGRAM
# ============================================================

if (
    not BOT_TOKEN
    or BOT_TOKEN == "ВСТАВЬ_СВОЙ_ТОКЕН_СЮДА"
):
    raise RuntimeError(
        "Не указан BOT_TOKEN. "
        "Вставь токен от @BotFather в код, "
        "в переменную BOT_TOKEN."
    )

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

render_semaphore = asyncio.Semaphore(
    MAX_CONCURRENT_RENDERS
)

slug_locks = {}

NFT_URL_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/nft/([A-Za-z0-9_-]+)",
    re.I,
)

LOTTIE_URL = (
    "https://nft.fragment.com/gift/{slug}.lottie.json"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)

# ============================================================
# БАЗА ДАННЫХ
# ============================================================

def db_connect():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    BASE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with db_connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS nfts (
                slug TEXT PRIMARY KEY,
                title TEXT,
                model TEXT,
                backdrop TEXT,
                symbol TEXT,
                page_url TEXT,
                gif_file_id TEXT,
                mpeg4_file_id TEXT,
                added_by INTEGER,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Миграция со старой схемы.
        cols = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(nfts)"
            ).fetchall()
        }

        if "mpeg4_file_id" not in cols:
            conn.execute(
                "ALTER TABLE nfts ADD COLUMN mpeg4_file_id TEXT"
            )
            log.info(
                "База обновлена: добавлено поле mpeg4_file_id."
            )

        conn.commit()

def parse_slug(text):
    match = NFT_URL_RE.search(text or "")
    return match.group(1) if match else None

def clean_html(value):
    return " ".join(
        BeautifulSoup(
            value or "",
            "html.parser",
        ).get_text(
            " ",
            strip=True,
        ).split()
    )

def save_nft(data, gif_file_id, mpeg4_file_id, user_id):
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO nfts (
                slug,
                title,
                model,
                backdrop,
                symbol,
                page_url,
                gif_file_id,
                mpeg4_file_id,
                added_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(slug) DO UPDATE SET
                title = excluded.title,
                model = excluded.model,
                backdrop = excluded.backdrop,
                symbol = excluded.symbol,
                page_url = excluded.page_url,
                gif_file_id = COALESCE(
                    excluded.gif_file_id,
                    nfts.gif_file_id
                ),
                mpeg4_file_id = COALESCE(
                    excluded.mpeg4_file_id,
                    nfts.mpeg4_file_id
                ),
                added_by = excluded.added_by
        """, (
            data["slug"],
            data["title"],
            data["model"],
            data["backdrop"],
            data["symbol"],
            data["page_url"],
            gif_file_id,
            mpeg4_file_id,
            user_id,
        ))

        conn.commit()

def get_nft(slug):
    with db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM nfts WHERE slug = ?",
            (slug,),
        ).fetchone()

    return dict(row) if row else None

def get_nfts(query="", limit=50):
    with db_connect() as conn:
        if query.strip():
            q = f"%{query.strip()}%"

            rows = conn.execute("""
                SELECT *
                FROM nfts
                WHERE slug LIKE ?
                   OR model LIKE ?
                   OR backdrop LIKE ?
                   OR symbol LIKE ?
                ORDER BY added_at DESC
                LIMIT ?
            """, (
                q,
                q,
                q,
                q,
                limit,
            )).fetchall()

        else:
            rows = conn.execute("""
                SELECT *
                FROM nfts
                ORDER BY added_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

    return [dict(row) for row in rows]

# ============================================================
# МЕТАДАННЫЕ NFT
# ============================================================

async def fetch_metadata(slug):
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
    ) as session:

        async with session.get(
            f"https://t.me/nft/{slug}"
        ) as resp:

            if resp.status != 200:
                raise ValueError(
                    f"Ошибка страницы NFT: HTTP {resp.status}"
                )

            page = await resp.text()

    soup = BeautifulSoup(page, "html.parser")

    fields = {
        "model": "",
        "backdrop": "",
        "symbol": "",
    }

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])

        if len(cells) < 2:
            continue

        key = clean_html(
            str(cells[0])
        ).lower().rstrip(":")

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

# ============================================================
# ПРОВЕРКА ИНСТРУМЕНТОВ
# ============================================================

def check_gifski():
    executable = shutil.which("gifski")

    if not executable:
        raise RuntimeError(
            "Не найден Gifski. "
            "Установи программу gifski и проверь PATH."
        )

    return executable

def check_ffmpeg():
    executable = shutil.which("ffmpeg")

    if not executable:
        raise RuntimeError(
            "Не найден ffmpeg. "
            "Установи ffmpeg (например: apt install ffmpeg)."
        )

    log.info("ffmpeg найден: %s", executable)

    return executable

# ============================================================
# ЗАГРУЗКА LOTTIE
# ============================================================

async def download_lottie(slug, output_path):
    url = LOTTIE_URL.format(slug=slug)

    timeout = aiohttp.ClientTimeout(
        total=DOWNLOAD_TIMEOUT,
        connect=20,
        sock_read=60,
    )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
    ) as session:

        async with session.get(url) as resp:

            if resp.status != 200:
                raise ValueError(
                    f"Ошибка загрузки Lottie: HTTP {resp.status}"
                )

            data = await resp.read()

    if not data:
        raise RuntimeError(
            "Сервер вернул пустую Lottie-анимацию."
        )

    if len(data) > MAX_LOTTIE_SIZE:
        raise RuntimeError(
            "Исходная Lottie превышает допустимый размер."
        )

    output_path.write_bytes(data)

    log.info(
        "Lottie загружена: %s, %.2f МБ",
        slug,
        len(data) / 1024 / 1024,
    )

# ============================================================
# LOTTIE -> PNG -> GIF -> MP4
# ============================================================

def convert_lottie_to_gif_sync(json_path, gif_path, work_dir):
    try:
        from rlottie_python import LottieAnimation
    except ImportError as exc:
        raise RuntimeError(
            "Не установлена rlottie-python. "
            "Проверь requirements.txt."
        ) from exc

    gifski = check_gifski()
    anim = None

    try:
        anim = LottieAnimation.from_file(str(json_path))

        orig_w, orig_h = anim.lottie_animation_get_size()
        orig_w = int(orig_w)
        orig_h = int(orig_h)

        total_frames = int(
            anim.lottie_animation_get_totalframe()
        )
        original_fps = float(
            anim.lottie_animation_get_framerate()
        )

        if orig_w <= 0 or orig_h <= 0:
            raise RuntimeError(
                f"Некорректный размер: {orig_w}x{orig_h}"
            )

        if total_frames <= 0:
            raise RuntimeError("В анимации нет кадров.")

        if not math.isfinite(original_fps) or original_fps <= 0:
            raise RuntimeError(
                f"Некорректный FPS: {original_fps}"
            )

        duration = total_frames / original_fps

        if (
            MAX_DURATION_SECONDS > 0
            and duration > MAX_DURATION_SECONDS
        ):
            raise RuntimeError(
                f"Анимация длится {duration:.1f} сек. "
                "Превышено допустимое время."
            )

        fps = max(
            1,
            min(math.ceil(original_fps), MAX_FPS),
        )

        scale = MAX_RENDER_DIMENSION / max(orig_w, orig_h)
        out_w = max(1, round(orig_w * scale))
        out_h = max(1, round(orig_h * scale))

        if SSAA_FACTOR > 1:
            render_w = min(
                out_w * SSAA_FACTOR,
                SSAA_MAX_DIMENSION,
            )
            render_h = min(
                out_h * SSAA_FACTOR,
                SSAA_MAX_DIMENSION,
            )
        else:
            render_w = out_w
            render_h = out_h

        log.info(
            "Рендеринг %s: %sx%s -> %sx%s (рендер %sx%s), "
            "frames=%s, fps=%.3f, duration=%.2fs",
            json_path.name,
            orig_w,
            orig_h,
            out_w,
            out_h,
            render_w,
            render_h,
            total_frames,
            original_fps,
            duration,
        )

        frames_dir = work_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        frame_files = []

        for i in range(total_frames):
            frame_path = frames_dir / f"frame_{i:06d}.png"

            frame_img = anim.render_pillow_frame(
                frame_num=i,
                width=render_w,
                height=render_h,
            )

            try:
                if (render_w, render_h) != (out_w, out_h):
                    frame_img = frame_img.resize(
                        (out_w, out_h),
                        Image.Resampling.LANCZOS,
                    )

                frame_img.save(
                    str(frame_path),
                    format="PNG",
                    optimize=False,
                )

            finally:
                close_method = getattr(
                    frame_img, "close", None
                )
                if callable(close_method):
                    close_method()

            frame_files.append(str(frame_path))

            if (i + 1) % 100 == 0:
                log.info(
                    "Обработано кадров: %s/%s",
                    i + 1,
                    total_frames,
                )

        destroy = getattr(
            anim, "lottie_animation_destroy", None
        )
        if callable(destroy):
            destroy()
        anim = None

        cmd = [
            gifski,
            "--output", str(gif_path),
            "--fps", str(fps),
            "--quality", str(GIF_QUALITY),
            "--motion-quality", str(GIF_MOTION_QUALITY),
            "--lossy-quality", str(GIF_LOSSY_QUALITY),
        ]

        if GIF_EXTRA_COMPRESSION:
            cmd.append("--extra")

        cmd.extend(frame_files)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=RENDER_TIMEOUT,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Ошибка Gifski: "
                + (
                    result.stderr
                    or result.stdout
                    or "неизвестная ошибка"
                )[:2000]
            )

        if not gif_path.exists():
            raise RuntimeError("Gifski не создал GIF.")

        gif_size = gif_path.stat().st_size

        if gif_size <= 0:
            raise RuntimeError("Итоговый GIF пуст.")

        if (
            MAX_GIF_SIZE_BYTES > 0
            and gif_size > MAX_GIF_SIZE_BYTES
        ):
            raise RuntimeError(
                f"GIF слишком большой: {gif_size} байт."
            )

        log.info(
            "GIF готов: %sx%s, %s кадров, %.2f МБ",
            out_w,
            out_h,
            total_frames,
            gif_size / 1024 / 1024,
        )

        return {
            "width": out_w,
            "height": out_h,
            "frames": total_frames,
            "fps": fps,
            "duration": duration,
            "size": gif_size,
        }

    finally:
        if anim is not None:
            destroy = getattr(
                anim, "lottie_animation_destroy", None
            )
            if callable(destroy):
                try:
                    destroy()
                except Exception:
                    log.exception(
                        "Ошибка освобождения Lottie."
                    )


def convert_gif_to_mp4_sync(
    gif_path: Path,
    mp4_path: Path,
    fps: float,
    size: int,
):
    """
    Конвертация GIF -> MP4 (H.264, без звука).
    yuv420p обязателен для совместимости с Telegram.
    """
    ffmpeg = check_ffmpeg()

    # scale=size:-2 гарантирует чётные размеры (требование H.264).
    vf = (
        f"scale='min({size},iw)':-2:flags=lanczos,"
        f"pad=ceil(iw/2)*2:ceil(ih/2)*2"
    )

    cmd = [
        ffmpeg,
        "-y",
        "-i", str(gif_path),
        "-an",
        "-c:v", "libx264",
        "-preset", MP4_PRESET,
        "-crf", str(MP4_CRF),
        "-profile:v", MP4_PROFILE,
        "-level", MP4_LEVEL,
        "-pix_fmt", MP4_PIX_FMT,
        "-vf", vf,
        "-movflags", "+faststart",
        "-r", str(fps),
        str(mp4_path),
    ]

    log.info(
        "Конвертация в MP4: crf=%s preset=%s profile=%s",
        MP4_CRF,
        MP4_PRESET,
        MP4_PROFILE,
    )

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Ошибка ffmpeg: "
            + (
                result.stderr
                or result.stdout
                or "неизвестная ошибка"
            )[-2000:]
        )

    if not mp4_path.exists() or mp4_path.stat().st_size <= 0:
        raise RuntimeError("ffmpeg не создал MP4.")

    log.info(
        "MP4 готов: %.2f МБ",
        mp4_path.stat().st_size / 1024 / 1024,
    )


# ============================================================
# ГЕНЕРАЦИЯ И ОТПРАВКА
# ============================================================

async def lottie_to_file_ids(slug, chat_id):
    """
    Возвращает (gif_file_id, mpeg4_file_id).
    """
    async with render_semaphore:
        with tempfile.TemporaryDirectory(
            prefix="nft_gif_",
        ) as tmp:

            work_dir = Path(tmp)
            json_path = work_dir / "anim.json"
            gif_path = work_dir / "anim.gif"
            mp4_path = work_dir / "anim.mp4"

            await download_lottie(slug, json_path)

            info = await asyncio.to_thread(
                convert_lottie_to_gif_sync,
                json_path,
                gif_path,
                work_dir,
            )

            # GIF -> MP4
            try:
                await asyncio.to_thread(
                    convert_gif_to_mp4_sync,
                    gif_path,
                    mp4_path,
                    float(info["fps"]),
                    int(max(info["width"], info["height"])),
                )
            except Exception:
                log.exception(
                    "Не удалось сконвертировать в MP4, "
                    "работаем без MP4: %s",
                    slug,
                )
                mp4_path = None

            gif_file_id = None
            mpeg4_file_id = None

            # Основная анимация в чат.
            if SEND_ANIMATION_MP4 and mp4_path is not None:
                log.info(
                    "Отправка MP4 в Telegram: %s, %.2f МБ",
                    slug,
                    mp4_path.stat().st_size / 1024 / 1024,
                )

                try:
                    msg = await bot.send_animation(
                        chat_id=chat_id,
                        animation=FSInputFile(
                            str(mp4_path),
                            filename=f"{slug}.mp4",
                        ),
                        caption=f"NFT: {slug}",
                    )

                    if msg.animation:
                        mpeg4_file_id = msg.animation.file_id

                except Exception:
                    log.exception(
                        "send_animation(MP4) не удался: %s",
                        slug,
                    )

            # Fallback: GIF анимацией.
            if mpeg4_file_id is None:
                log.info(
                    "Отправка GIF анимацией: %s, %.2f МБ",
                    slug,
                    info["size"] / 1024 / 1024,
                )

                try:
                    msg = await bot.send_animation(
                        chat_id=chat_id,
                        animation=FSInputFile(
                            str(gif_path),
                            filename=f"{slug}.gif",
                        ),
                        caption=f"NFT: {slug}",
                    )

                    if msg.animation:
                        gif_file_id = msg.animation.file_id

                except Exception:
                    log.exception(
                        "send_animation(GIF) не удался: %s",
                        slug,
                    )

            # Оригинальный GIF документом.
            if SEND_ORIGINAL_AS_DOCUMENT:
                try:
                    await bot.send_document(
                        chat_id=chat_id,
                        document=FSInputFile(
                            str(gif_path),
                            filename=f"{slug}.gif",
                        ),
                        caption=(
                            f"Оригинал без пережатия: {slug}"
                        ),
                    )
                except Exception:
                    log.exception(
                        "Не удалось отправить документ: %s",
                        slug,
                    )

            return gif_file_id, mpeg4_file_id


# ============================================================
# ПОДПИСЬ NFT
# ============================================================

def format_caption(nft):
    slug = html.escape(nft.get("slug") or "")
    model = html.escape(nft.get("model") or "—")
    backdrop = html.escape(nft.get("backdrop") or "—")
    symbol = html.escape(nft.get("symbol") or "—")
    page_url = html.escape(
        nft.get("page_url") or "", quote=True
    )

    return (
        f"<b>🎁 {slug}</b>\n\n"
        f"🧩 <b>Модель:</b> {model}\n"
        f"🎨 <b>Фон:</b> {backdrop}\n"
        f"🔣 <b>Pattern:</b> {symbol}\n\n"
        f'<a href="{page_url}">Открыть NFT</a>'
    )

# ============================================================
# /START
# ============================================================

@dp.message(CommandStart())
async def start(message: Message):
    me = await bot.get_me()

    await message.answer(
        f"🎁 <b>NFT GIF Bot</b>\n"
        f"<i>{VERSION}</i>\n\n"
        "Отправь ссылку на NFT:\n"
        "<code>https://t.me/nft/название-номер</code>\n\n"
        f"Inline-поиск: <code>@{me.username}</code>",
        parse_mode="HTML",
    )

# ============================================================
# ОБРАБОТКА ССЫЛКИ
# ============================================================

@dp.message(F.text)
async def handle_text(message: Message):
    slug = parse_slug(message.text or "")

    if not slug:
        await message.answer(
            "❌ Отправь ссылку вида:\n"
            "https://t.me/nft/название-номер"
        )
        return

    lock = slug_locks.setdefault(slug, asyncio.Lock())

    async with lock:
        existing = get_nft(slug)

        if existing and (
            existing.get("mpeg4_file_id")
            or existing.get("gif_file_id")
        ):
            try:
                if existing.get("mpeg4_file_id"):
                    await message.answer_animation(
                        animation=existing["mpeg4_file_id"],
                        caption=format_caption(existing),
                        parse_mode="HTML",
                    )
                else:
                    await message.answer_animation(
                        animation=existing["gif_file_id"],
                        caption=format_caption(existing),
                        parse_mode="HTML",
                    )
                return

            except Exception:
                log.exception(
                    "Не удалось отправить сохранённый файл: %s",
                    slug,
                )

        status = await message.answer(
            "🔎 Получаю информацию об NFT..."
        )

        try:
            data = await fetch_metadata(slug)

            await status.edit_text(
                "🎬 Создаю анимацию максимального качества "
                "(GIF + MP4)...\n"
                "Пожалуйста, подожди."
            )

            gif_file_id, mpeg4_file_id = await lottie_to_file_ids(
                slug,
                message.chat.id,
            )

            save_nft(
                data,
                gif_file_id,
                mpeg4_file_id,
                message.from_user.id
                if message.from_user
                else 0,
            )

            me = await bot.get_me()

            await status.edit_text(
                f"✅ <b>Готово!</b>\n\n"
                f"🎁 {html.escape(slug)}\n"
                f"🧩 Модель: "
                f"{html.escape(data['model'] or '—')}\n"
                f"🎨 Фон: "
                f"{html.escape(data['backdrop'] or '—')}\n"
                f"🔣 Pattern: "
                f"{html.escape(data['symbol'] or '—')}\n\n"
                f"Версия: {VERSION}\n"
                f"Inline-поиск: <code>@{me.username}</code>",
                parse_mode="HTML",
            )

        except Exception as exc:
            log.exception(
                "Ошибка обработки NFT %s",
                slug,
            )

            try:
                await status.edit_text(
                    "❌ <b>Ошибка обработки NFT</b>\n\n"
                    f"<code>{html.escape(str(exc)[:1200])}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                log.exception(
                    "Не удалось отправить сообщение об ошибке."
                )

        finally:
            if slug_locks.get(slug) is lock:
                slug_locks.pop(slug, None)

# ============================================================
# INLINE-РЕЖИМ
# ============================================================

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
        await query.answer(
            results=results,
            cache_time=1,
            is_personal=True,
        )
    except Exception:
        log.exception("Ошибка ответа на inline query")

# ============================================================
# ЗАПУСК И ЗАКРЫТИЕ СЕССИИ
# ============================================================

async def main():
    init_db()

    log.info("Проверяю подключение к Telegram...")

    try:
        check_gifski()
        check_ffmpeg()

        me = await bot.get_me()

        log.info(
            "Авторизация успешна. Бот @%s",
            me.username,
        )
        log.info("Версия: %s", VERSION)
        log.info(
            "Разрешение рендера: до %s px "
            "(суперсэмплинг x%s)",
            MAX_RENDER_DIMENSION,
            SSAA_FACTOR,
        )
        log.info(
            "MP4: crf=%s, preset=%s, profile=%s",
            MP4_CRF,
            MP4_PRESET,
            MP4_PROFILE,
        )

        await dp.start_polling(
            bot,
            close_bot_session=False,
        )

    except TelegramUnauthorizedError:
        log.critical(
            "Telegram отклонил токен. "
            "Проверь BOT_TOKEN в коде."
        )
        raise

    finally:
        await bot.session.close()
        log.info("Сессия Telegram закрыта.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Бот остановлен.")
    except TelegramUnauthorizedError:
        log.critical(
            "Запуск невозможен: недействительный токен."
        )
