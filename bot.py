import asyncio
import html
import logging
import math
import shutil
import sqlite3
import subprocess
import tempfile
import re
import json
import io
from pathlib import Path
import aiohttp
from bs4 import BeautifulSoup
from PIL import Image
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineQuery, InlineQueryResultCachedGif, InlineQueryResultCachedMpeg4Gif, FSInputFile
from aiogram.exceptions import TelegramUnauthorizedError

# Импорты для работы со слоями
from lottie.parsers.tgs import parse_tgs
from lottie.exporters.cairo import export_png
from lottie.objects import Composition, Layer

# ==============================================================================
# ⚙️ НАСТРОЙКИ
# ==============================================================================
BOT_TOKEN = "BOT_TOKEN"
VERSION = "v25.0 True Layer Split"

CARD_W = 1280
CARD_H = 720
MODEL_SCALE = 1.0 

FPS = 30
FRAME_SKIP = 2 
MP4_CRF = 22
MP4_PRESET = "ultrafast"

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "nfts.sqlite3"
MP4_PIX = "yuv420p"
MAX_CONC = 1
DL_TIMEOUT = 120
RENDER_TIMEOUT = 600

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("nft")

if not BOT_TOKEN or BOT_TOKEN == "ВСТАВЬ_СВОЙ_ТОКЕН_СЮДА":
    raise RuntimeError("Нет токена")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
sem = asyncio.Semaphore(MAX_CONC)
locks = {}

NFT_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/nft/([A-Za-z0-9_-]+)", re.I)
LOTTIE_URL = "https://nft.fragment.com/gift/{slug}.lottie.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

def db_conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with db_conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        q = "CREATE TABLE IF NOT EXISTS nfts (slug TEXT PRIMARY KEY, title TEXT, model TEXT, backdrop TEXT, symbol TEXT, page_url TEXT, gif_file_id TEXT, mpeg4_file_id TEXT, added_by INTEGER, added_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        c.execute(q)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(nfts)")}
        if "mpeg4_file_id" not in cols:
            c.execute("ALTER TABLE nfts ADD COLUMN mpeg4_file_id TEXT")
        c.commit()

def get_slug(txt):
    m = NFT_RE.search(txt or "")
    return m.group(1) if m else None

def clean_html(v):
    return " ".join(BeautifulSoup(v or "", "html.parser").get_text(" ", strip=True).split())

def save_nft(d, g_id, m_id, u_id):
    with db_conn() as c:
        q = "INSERT INTO nfts (slug, title, model, backdrop, symbol, page_url, gif_file_id, mpeg4_file_id, added_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        q += "ON CONFLICT(slug) DO UPDATE SET title=excluded.title, model=excluded.model, backdrop=excluded.backdrop, symbol=excluded.symbol, page_url=excluded.page_url, added_by=excluded.added_by"
        c.execute(q, (d["slug"], d["title"], d["model"], d["backdrop"], d["symbol"], d["page_url"], g_id, m_id, u_id))
        c.commit()

def get_nft(slug):
    with db_conn() as c:
        row = c.execute("SELECT * FROM nfts WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None

def get_nfts(q="", lim=50):
    with db_conn() as c:
        if q.strip():
            s = f"%{q.strip()}%"
            sql = "SELECT * FROM nfts WHERE slug LIKE ? OR model LIKE ? OR backdrop LIKE ? OR symbol LIKE ? ORDER BY added_at DESC LIMIT ?"
            rows = c.execute(sql, (s, s, s, s, lim)).fetchall()
        else:
            rows = c.execute("SELECT * FROM nfts ORDER BY added_at DESC LIMIT ?", (lim,)).fetchall()
    return [dict(r) for r in rows]

async def fetch_meta(slug):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), headers={"User-Agent": UA}) as s:
        async with s.get(f"https://t.me/nft/{slug}") as r:
            if r.status != 200: raise ValueError(f"HTTP {r.status}")
            p = await r.text()
    soup = BeautifulSoup(p, "html.parser")
    f = {"model": "", "backdrop": "", "symbol": ""}
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2: continue
        k = clean_html(str(cells[0])).lower().rstrip(":")
        if k in f: f[k] = clean_html(str(cells[1]))
    return {"slug": slug, "title": slug, "model": f["model"], "backdrop": f["backdrop"], "symbol": f["symbol"], "page_url": f"https://t.me/nft/{slug}"}

def check_ff():
    exe = shutil.which("ffmpeg")
    if not exe: raise RuntimeError("Нет ffmpeg")
    return exe

async def dl_file(url, path):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=DL_TIMEOUT), headers={"User-Agent": UA}) as s:
        async with s.get(url) as r:
            if r.status != 200: raise ValueError(f"HTTP {r.status}")
            d = await r.read()
    path.write_bytes(d)

def isolate_layers(json_path, bg_path, model_path):
    """Разделяет оригинальный Lottie на фон (с паттерном) и модель"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    layers = data.get("layers", [])
    bg_layers = []
    model_layers = []

    for layer in layers:
        name = layer.get("nm", "").lower()
        # Модель обычно содержит слово model, gift, или это единственный анимированный слой
        if "model" in name or "gift" in name:
            model_layers.append(layer)
        else:
            bg_layers.append(layer)

    if not model_layers:
        # Если не нашли по имени, берем последний слой как модель (обычно модель сверху)
        model_layers = [layers[-1]]
        bg_layers = layers[:-1]

    # Сохраняем фон (растянутый)
    bg_data = data.copy()
    bg_data["layers"] = bg_layers
    with open(bg_path, "w", encoding="utf-8") as f:
        json.dump(bg_data, f)

    # Сохраняем модель
    model_data = data.copy()
    model_data["layers"] = model_layers
    with open(model_path, "w", encoding="utf-8") as f:
        json.dump(model_data, f)

def conv_sync(json_path, mp4_path, work_dir, nft_data):
    ff = check_ff()
    
    bg_json = work_dir / "bg.json"
    model_json = work_dir / "model.json"
    
    isolate_layers(json_path, bg_json, model_json)
    
    # Загружаем композиции
    with open(bg_json, "r", encoding="utf-8") as f:
        bg_anim = parse_tgs(f, Composition)
    
    with open(model_json, "r", encoding="utf-8") as f:
        model_anim = parse_tgs(f, Composition)

    # Задаем размеры холста
    bg_anim.width = CARD_W
    bg_anim.height = CARD_H
    
    model_h = int(CARD_H * MODEL_SCALE)
    model_w = model_h
    model_anim.width = model_w
    model_anim.height = model_h

    tf = int(bg_anim.out_point)
    ofps = float(bg_anim.frame_rate)
    frames = range(0, tf, FRAME_SKIP)
    fps = max(1, min(math.ceil(ofps / FRAME_SKIP), FPS))

    offset_y = (CARD_H - model_h) // 2
    offset_x = (CARD_W - model_w) // 2

    fdir = work_dir / "frames"
    fdir.mkdir(parents=True, exist_ok=True)

    for idx, i in enumerate(frames):
        fp = fdir / f"f_{idx:06d}.png"
        
        # 1. Рендерим растянутый фон с паттерном
        bg_img = export_png(bg_anim, frame=i, width=CARD_W, height=CARD_H)
        
        # 2. Рендерим модель
        model_img = export_png(model_anim, frame=i, width=model_w, height=model_h)
        
        # 3. Склеиваем
        bg_img.paste(model_img, (offset_x, offset_y), model_img)
        
        bg_img.convert("RGB").save(str(fp), format="PNG", compress_level=0)
        
        bg_img.close()
        model_img.close()

    cmd = [
        ff, "-y", "-framerate", str(fps), "-i", str(fdir / "f_%06d.png"),
        "-an", "-c:v", "libx264", "-preset", MP4_PRESET, "-crf", str(MP4_CRF),
        "-pix_fmt", MP4_PIX, "-threads", "0", "-movflags", "+faststart", str(mp4_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg err: {res.stderr[-500:]}")

async def gen_ids(slug, chat_id):
    async with sem:
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            jp = wd / "a.json"
            mp = wd / "a.mp4"
            
            await dl_file(LOTTIE_URL.format(slug=slug), jp)
            d = await fetch_meta(slug)
            await asyncio.to_thread(conv_sync, jp, mp, wd, d)
            
            mid = None
            try:
                msg = await bot.send_animation(chat_id=chat_id, animation=FSInputFile(str(mp), filename=f"{slug}.mp4"), caption=f"NFT: {slug}")
                if msg.animation: mid = msg.animation.file_id
            except Exception:
                log.exception("send err")
            return None, mid, d

def fmt_cap(nft):
    s = html.escape(nft.get("slug") or "")
    m = html.escape(nft.get("model") or "-")
    b = html.escape(nft.get("backdrop") or "-")
    sy = html.escape(nft.get("symbol") or "-")
    u = html.escape(nft.get("page_url") or "")
    return f"<b>{s}</b>\nModel: {m}\nBg: {b}\nPattern: {sy}\n<a href='{u}'>Link</a>"

@dp.message(CommandStart())
async def start(msg: Message):
    me = await bot.get_me()
    await msg.answer(f"Bot {VERSION}\nSearch: @{me.username}", parse_mode="HTML")

@dp.message(F.text)
async def handle_txt(msg: Message):
    slug = get_slug(msg.text or "")
    if not slug:
        await msg.answer("Send link")
        return

    lk = locks.setdefault(slug, asyncio.Lock())
    async with lk:
        ext = get_nft(slug)
        if ext and ext.get("mpeg4_file_id"):
            try:
                await msg.answer_animation(animation=ext["mpeg4_file_id"], caption=fmt_cap(ext), parse_mode="HTML")
                return
            except: pass

        st = await msg.answer("Wait...")
        try:
            gid, mid, d = await gen_ids(slug, msg.chat.id)
            save_nft(d, gid, mid, msg.from_user.id if msg.from_user else 0)
            me = await bot.get_me()
            await st.edit_text(f"Done!\n@{me.username}")
        except Exception as e:
            await st.edit_text(f"Err: {e}")
        finally:
            if locks.get(slug) is lk: locks.pop(slug, None)

@dp.inline_query()
async def inline(q: InlineQuery):
    items = get_nfts((q.query or "").strip(), lim=50)
    res = []
    for n in items:
        cap = fmt_cap(n)
        mid, gid = n.get("mpeg4_file_id"), n.get("gif_file_id")
        if mid:
            res.append(InlineQueryResultCachedMpeg4Gif(id=n["slug"], mpeg4_file_id=mid, caption=cap, parse_mode="HTML"))
        elif gid:
            res.append(InlineQueryResultCachedGif(id=n["slug"], gif_file_id=gid, caption=cap, parse_mode="HTML"))
    try:
        await q.answer(results=res, cache_time=1, is_personal=True)
    except: pass

async def main():
    init_db()
    try:
        check_ff()
        me = await bot.get_me()
        print(f"Started @{me.username}")
        await dp.start_polling(bot, close_bot_session=False)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
