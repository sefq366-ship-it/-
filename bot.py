import asyncio
import html
import logging
import math
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time

from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    InlineQuery,
    InlineQueryResultCachedGif,
    FSInputFile,
)

# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = "8977910657:AAFn1ZohJDaUFUDsE4ka2YBH85-ENak0HoE"

VERSION = "v3.0 Ultra Quality"

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "nfts.sqlite3"

# Максимальная сторона изображения при рендеринге.
# Можно изменить на 1024, 1536 или 2048.
MAX_RENDER_DIMENSION = 2048

# Максимальный FPS результата.
# Фактическая частота не должна превышать исходную.
MAX_FPS = 60

# Ограничение продолжительности анимации.
# 0 означает отсутствие ограничения.
MAX_DURATION_SECONDS = 0

# Параметры Gifski.
GIF_QUALITY = 100
GIF_MOTION_QUALITY = 100
GIF_LOSSY_QUALITY = 100

# Ограничение параллельных конвертаций.
MAX_CONCURRENT_RENDERS = 1

# Максимальный размер результата в байтах.
# 0 означает отсутствие собственного ограничения.
MAX_GIF_SIZE_BYTES = 0

# Тайм-аут загрузки исходной анимации.
DOWNLOAD_TIMEOUT = 120

# Тайм-аут конвертации.
RENDER_TIMEOUT = 900

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

if not BOT_TOKEN or BOT_TOKEN == "ВАШ_ТОКЕН_ЗДЕСЬ":
    raise RuntimeError(
        "Укажи настоящий BOT_TOKEN в начале файла main.py"
    )

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

render_semaphore = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)

# Блокировка одновременной обработки одного NFT.
slug_locks = {}

NFT_URL_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/nft/([A-Za-z0-9_-]+)",
    re.I,
)

LOTTIE_URL = "https://nft.fragment.com/gift/{slug}.lottie.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)


# ============================================================
# SQLITE
# ============================================================

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    BASE_DIR.mkdir(parents=True, exist_ok=True)

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
                added_by INTEGER,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()


def parse_slug(text):
    match = NFT_URL_RE.search(text or "")
    return match.group(1) if match else None


def clean_html(value):
    return " ".join(
        BeautifulSoup(
            value or "",
            "html.parser"
        ).get_text(" ", strip=True).split()
    )


def save_nft(data, gif_file_id, user_id):
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
                added_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(slug) DO UPDATE SET
                title = excluded.title,
                model = excluded.model,
                backdrop = excluded.backdrop,
                symbol = excluded.symbol,
                page_url = excluded.page_url,
                gif_file_id = excluded.gif_file_id,
                added_by = excluded.added_by
        """, (
            data["slug"],
            data["title"],
            data["model"],
            data["backdrop"],
            data["symbol"],
            data["page_url"],
            gif_file_id,
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
            """, (q, q, q, q, limit)).fetchall()

        else:
            rows = conn.execute("""
                SELECT *
                FROM nfts
                ORDER BY added_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

    return [dict(row) for row in rows]


# ============================================================
# NFT METADATA
# ============================================================

async def fetch_metadata(slug):
    timeout = aiohttp.ClientTimeout(total=30)

    headers = {
        "User-Agent": USER_AGENT,
    }

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


# ============================================================
# ПРОВЕРКА ЗАВИСИМОСТЕЙ
# ============================================================

def check_gifski():
    executable = shutil.which("gifski")

    if not executable:
        raise RuntimeError(
            "Не найден gifski. Установи Gifski "
            "и проверь, что команда gifski доступна в PATH."
        )

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

        async with session.get(
            url,
            headers=headers,
        ) as resp:

            if resp.status != 200:
                raise ValueError(
                    f"Не удалось скачать Lottie: HTTP {resp.status}"
                )

            content_type = resp.headers.get(
                "Content-Type", ""
            ).lower()

            data = await resp.read()

    if not data:
        raise RuntimeError("Сервер вернул пустую анимацию.")

    if len(data) > 100 * 1024 * 1024:
        raise RuntimeError(
            "Исходная Lottie превышает 100 МБ."
        )

    output_path.write_bytes(data)

    log.info(
        "Lottie загружена: %s, %.2f МБ, Content-Type=%s",
        slug,
        len(data) / 1024 / 1024,
        content_type,
    )


# ============================================================
# РЕНДЕРИНГ И КОНВЕРТАЦИЯ
# ============================================================

def convert_lottie_to_gif_sync(
    json_path: Path,
    gif_path: Path,
    work_dir: Path,
):
    """
    Синхронная конвертация.

    Lottie -> PNG frames -> Gifski -> GIF.

    Важно:
    - исходные кадры не пропускаются;
    - сохраняется исходная частота кадров;
    - размер увеличивается без изменения пропорций;
    - каждый кадр записывается на диск;
    - все PNG не хранятся одновременно в RAM.
    """

    try:
        from rlottie_python import LottieAnimation
    except ImportError as exc:
        raise RuntimeError(
            "Не установлена библиотека rlottie-python. "
            "Проверь зависимости хостинга."
        ) from exc

    gifski_executable = check_gifski()

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
                f"Некорректный размер Lottie: {orig_w}x{orig_h}"
            )

        if total_frames <= 0:
            raise RuntimeError(
                "В Lottie отсутствуют кадры."
            )

        if not math.isfinite(original_fps) or original_fps <= 0:
            raise RuntimeError(
                f"Некорректный FPS Lottie: {original_fps}"
            )

        # Не увеличиваем FPS искусственно.
        fps = max(
            1,
            min(round(original_fps), MAX_FPS),
        )

        duration = total_frames / original_fps

        log.info(
            "Lottie: %sx%s, frames=%s, fps=%.3f, duration=%.2fs",
            orig_w,
            orig_h,
            total_frames,
            original_fps,
            duration,
        )

        if (
            MAX_DURATION_SECONDS > 0
            and duration > MAX_DURATION_SECONDS
        ):
            raise RuntimeError(
                f"Анимация слишком длинная: {duration:.1f} сек."
            )

        # Масштабирование с сохранением пропорций.
        # Маленькие исходники увеличиваются, если позволяют
        # настройки MAX_RENDER_DIMENSION.
        scale = MAX_RENDER_DIMENSION / max(orig_w, orig_h)

        out_w = max(1, round(orig_w * scale))
        out_h = max(1, round(orig_h * scale))

        log.info(
            "Размер рендера: %sx%s",
            out_w,
            out_h,
        )

        frames_dir = work_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        frame_files = []

        # Для каждого исходного кадра создаём PNG.
        # Сохраняем каждый PNG на диск, а не в оперативную память.
        for i in range(total_frames):
            frame_path = frames_dir / f"frame_{i:06d}.png"

            frame_img = anim.render_pillow_frame(
                frame_num=i,
                width=out_w,
                height=out_h,
            )

            try:
                # PNG без потерь на промежуточном этапе.
                frame_img.save(
                    frame_path,
                    format="PNG",
                    optimize=False,
                )
            finally:
                close_method = getattr(
                    frame_img,
                    "close",
                    None,
                )

                if callable(close_method):
                    close_method()

            frame_files.append(str(frame_path))

            if (i + 1) % 100 == 0:
                log.info(
                    "Отрендерено кадров: %s/%s",
                    i + 1,
                    total_frames,
                )

        # Освобождаем ресурсы рендерера до запуска Gifski.
        destroy = getattr(
            anim,
            "lottie_animation_destroy",
            None,
        )

        if callable(destroy):
            destroy()

        anim = None

        # Максимальные параметры качества Gifski.
        cmd = [
            gifski_executable,
            "--output",
            str(gif_path),
            "--fps",
            str(fps),
            "--quality",
            str(GIF_QUALITY),
            "--motion-quality",
            str(GIF_MOTION_QUALITY),
            "--lossy-quality",
            str(GIF_LOSSY_QUALITY),
            *frame_files,
        ]

        log.info(
            "Запуск Gifski: frames=%s, fps=%s",
            len(frame_files),
            fps,
        )

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
                + (result.stderr or result.stdout or "неизвестная ошибка")[:2000]
            )

        if not gif_path.exists():
            raise RuntimeError(
                "Gifski не создал итоговый GIF."
            )

        gif_size = gif_path.stat().st_size

        if gif_size <= 0:
            raise RuntimeError(
                "Создан пустой GIF."
            )

        if (
            MAX_GIF_SIZE_BYTES > 0
            and gif_size > MAX_GIF_SIZE_BYTES
        ):
            raise RuntimeError(
                "GIF превышает установленный лимит размера: "
                f"{gif_size} байт."
            )

        log.info(
            "GIF готов: %s, %.2f МБ",
            gif_path,
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
                anim,
                "lottie_animation_destroy",
                None,
            )

            if callable(destroy):
                try:
                    destroy()
                except Exception:
                    log.exception(
                        "Не удалось корректно освободить Lottie."
                    )


async def lottie_to_gif_file_id(slug, chat_id):
    async with render_semaphore:
        with tempfile.TemporaryDirectory(
            prefix="nft_gif_"
        ) as tmp:

            work_dir = Path(tmp)

            json_path = work_dir / "anim.json"
            gif_path = work_dir / "anim.gif"

            await download_lottie(
                slug,
                json_path,
            )

            info = await asyncio.to_thread(
                convert_lottie_to_gif_sync,
                json_path,
                gif_path,
                work_dir,
            )

            log.info(
                "Отправка GIF в Telegram: %s, %sx%s, %s кадров",
                slug,
                info["width"],
                info["height"],
                info["frames"],
            )

            gif_input = FSInputFile(
                str(gif_path),
                filename=f"{slug}.gif",
            )

            msg = await bot.send_animation(
                chat_id=chat_id,
                animation=gif_input,
                caption=f"NFT: {slug}",
            )

            if not msg.animation:
                raise RuntimeError(
                    "Telegram не вернул объект animation."
                )

            return msg.animation.file_id


# ============================================================
# ФОРМАТИРОВАНИЕ
# ============================================================

def format_caption(nft):
    slug = html.escape(nft.get("slug") or "")
    model = html.escape(nft.get("model") or "—")
    backdrop = html.escape(nft.get("backdrop") or "—")
    symbol = html.escape(nft.get("symbol") or "—")
    page_url = html.escape(
        nft.get("page_url") or "",
        quote=True,
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
        f"Затем ищи NFT в любом чате:\n"
        f"<code>@{me.username}</code>",
        parse_mode="HTML",
    )


# ============================================================
# ОБРАБОТКА ССЫЛОК
# ============================================================

@dp.message(F.text)
async def handle_text(message: Message):
    slug = parse_slug(message.text or "")

    if not slug:
        await message.answer(
            "❌ Отправь ссылку на NFT:\n"
            "https://t.me/nft/название-номер"
        )
        return

    # Не обрабатываем один NFT одновременно несколько раз.
    lock = slug_locks.setdefault(
        slug,
        asyncio.Lock(),
    )

    async with lock:
        existing = get_nft(slug)

        # Если GIF уже есть, используем Telegram file_id.
        if existing and existing.get("gif_file_id"):
            try:
                await message.answer_animation(
                    animation=existing["gif_file_id"],
                    caption=format_caption(existing),
                    parse_mode="HTML",
                )
                return

            except Exception:
                log.exception(
                    "Не удалось отправить сохранённый GIF %s",
                    slug,
                )

        status = await message.answer(
            "🔎 Получаю данные NFT..."
        )

        try:
            data = await fetch_metadata(slug)

            await status.edit_text(
                "🎬 Рендерю анимацию в высоком разрешении...\n"
                "Это может занять некоторое время."
            )

            gif_file_id = await lottie_to_gif_file_id(
                slug,
                message.chat.id,
            )

            save_nft(
                data,
                gif_file_id,
                message.from_user.id if message.from_user else 0,
            )

            me = await bot.get_me()

            await status.edit_text(
                f"✅ <b>Готово!</b>\n\n"
                f"🎁 {html.escape(slug)}\n"
                f"🧩 Модель: {html.escape(data['model'] or '—')}\n"
                f"🎨 Фон: {html.escape(data['backdrop'] or '—')}\n"
                f"🔣 Pattern: {html.escape(data['symbol'] or '—')}\n\n"
                f"Версия: {VERSION}\n"
                f"Теперь ищи NFT в inline-режиме:\n"
                f"<code>@{me.username}</code>",
                parse_mode="HTML",
            )

        except Exception as exc:
            log.exception(
                "Ошибка обработки NFT %s",
                slug,
            )

            error_text = html.escape(
                str(exc)[:1200]
            )

            try:
                await status.edit_text(
                    f"❌ <b>Не удалось обработать NFT</b>\n\n"
                    f"<code>{error_text}</code>",
                    parse_mode="HTML",
                )

            except Exception:
                log.exception(
                    "Не удалось отправить сообщение об ошибке."
                )

        finally:
            # Удаляем блокировку, если это всё ещё та же задача.
            if slug_locks.get(slug) is lock:
                slug_locks.pop(slug, None)


# ============================================================
# INLINE-РЕЖИМ
# ============================================================

@dp.inline_query()
async def inline_query_handler(query: InlineQuery):
    search = (query.query or "").strip()

    items = get_nfts(
        search,
        limit=50,
    )

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

    await query.answer(
        results=results,
        cache_time=1,
        is_personal=True,
    )


# ============================================================
# ЗАПУСК
# ============================================================

async def main():
    init_db()

    check_gifski()

    me = await bot.get_me()

    log.info(
        "Бот @%s запущен. Версия %s",
        me.username,
        VERSION,
    )

    log.info(
        "Максимальное разрешение: %s",
        MAX_RENDER_DIMENSION,
    )

    log.info(
        "Максимальный FPS: %s",
        MAX_FPS,
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        log.info("Бот остановлен.")
