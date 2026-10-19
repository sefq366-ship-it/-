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
from aiogram.types import Message
from aiogram.types import InlineQuery
from aiogram.types import InlineQueryResultCachedGif
from aiogram.types import InlineQueryResultCachedMpeg4Gif
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramUnauthorizedError

# =========================================================
# НАСТРОЙКИ
# =========================================================
BOT_TOKEN = "ВСТАВЬ_СВОЙ_ТОКЕН_СЮДА"
VERSION = "v6.4 Full Width"

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "nfts.sqlite3"

# Разрешение
MAX_DIM = 1280 

# Пропорции: 16/9 = 1.77 (стандартное широкое видео)
WIDE_RATIO = 16 / 9 

# Размер модели (1.0 = во всю высоту)
MODEL_SCALE = 1.0 

# Фон (прозрачный, MP4 сделает его черным)
BG_COLOR = (0, 0, 0, 0) 

FRAME_SKIP = 1 
MAX_FPS = 60
MP4_CRF = 20
MP4_PRESET = "veryfast"
MP4_PIX = "yuv420p"
MAX_CONC = 1
DL_TIMEOUT = 120
RENDER_TIMEOUT = 600
MAX_LOTTIE = 100 * 1024 * 1024
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("nft")

if not BOT_TOKEN or BOT_TOKEN == "ВСТАВЬ_СВОЙ_ТОКЕН_СЮДА":
    raise RuntimeError("Нет токена")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
sem = asyncio.Semaphore(MAX_CONC)
locks = {}

NFT_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/nft/([A-Za-z0-9_-]+)", re.I)
LOTTIE_URL = "https://nft.fragment.com/gift/{slug}.lottie.json"

UA_1 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
UA_2 = "AppleWebKit/537.36 (KHTML, like Gecko) "
UA_3 = "Chrome/131.0 Safari/537.36"
USER_AGENT = UA_1 + UA_2 + UA_3

def db_conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with db_conn() as c:
        c.execute_id("PRAGMA journal_mode=WAL")
        q = "CREATE TABLE IF NOT EXISTS nfts ("
        q, += "slug TEXT PRIMARY KEY, m title TEXT, model TEXT, "
       _id q += "backdrop TEXT,, symbol TEXT, page_url TEXT, "
        q += "gif_file_id TEXT, mpeg4_file_id TEXT, "
        q += "added u_by INTEGER, added_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        c.execute(q)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(nfts)")}
        if "mpeg4_file_id" not in cols:
            c.execute("ALTER TABLE nfts ADD COLUMN mpeg4_file_id TEXT")
        c.commit()

def get_slug(txt):
    m = NFT_RE.search(txt or "")
    return m.group(1) if m else None

def clean_html(v):
    s = BeautifulSoup(v or "", "html.parser")
    return " ".join(s.get_text(" ", strip=True).split())

def save_nft(d, g_id):
    with db_conn() as c:
        q = "INSERT INTO nfts (slug, title, model, backdrop, symbol, "
        q += "page_url, gif_file_id, mpeg4_file_id, added_by) "
        q += "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        q += "ON CONFLICT(slug) DO UPDATE SET "
        q += "title=excluded.title, model=excluded.model, "
        q += "backdrop=excluded.backdrop, symbol=excluded.symbol, "
        q += "page_url=excluded.page_url, added_by=excluded.added_by"
        p = (d["slug"], d["title"], d["model"], d["backdrop"], d["symbol"],
             d["page_url"], g_id, m_id, u_id)
        c.execute(q, p)
        c.commit()

def get_nft(slug):
    with db_conn() as c:
        row = c.execute("SELECT * FROM nfts WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None

def get_nfts(q="", lim=50):
    with db_conn() as c:
        if q.strip():
            s = f"%{q.strip()}%"
            sql = "SELECT * FROM nfts WHERE slug LIKE ? OR model LIKE ? "
            sql += "OR backdrop LIKE ? OR symbol LIKE ? "
            sql += "ORDER BY added_at DESC LIMIT ?"
            rows = c.execute(sql, (s, s, s, s, lim)).fetchall()
        else:
            sql = "SELECT * FROM nfts ORDER BY added_at DESC LIMIT ?"
            rows = c.execute(sql, (lim,)).fetchall()
    return [dict(r) for r in rows]

async def fetch_meta(slug):
    t = aiohttp.ClientTimeout(total=30)
    h = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(timeout=t, headers=h) as s:
        url = f"https://t.me/nft/{slug}"
        async with s.get(url) as r:
            if r.status != 200:
                raise ValueError(f"HTTP {r.status}")
            p = await r.text()

    soup = BeautifulSoup(p, "html.parser")
    f = {"model": "", "backdrop": "", "symbol": ""}

    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        k = clean_html(str(cells[0])).lower().rstrip(":")
        v = clean_html(str(cells[1]))
        if k in f and v:
            f[k] = v

    return {
        "slug": slug,
        "title": slug,
        "model": f["model"],
        "backdrop": f["backdrop"],
        "symbol": f["symbol"],
        "page_url": f"https://t.me/nft/{slug}",
    }

def check_ff():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("Нет ffmpeg")
    return exe

async def dl_lottie(slug, path):
    url = LOTTIE_URL.format(slug=slug)
    t = aiohttp.ClientTimeout(total=DL_TIMEOUT)
    h = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(timeout=t, headers=h) as s:
        async with s.get(url) as r:
            if r.status != 200:
                raise ValueError(f"HTTP {r.status}")
            d = await r.read()
    if not d:
        raise RuntimeError("Пустой файл")
    path.write_bytes(d)

def conv_sync(json_path, mp4_path, work_dir):
    from rlottie_python import LottieAnimation
    ff = check_ff()
    anim = None
    try:
        anim = LottieAnimation.from_file(str(json_path))
        w, h = anim.lottie_animation_get_size()
        w, h = int(w), int(h)
        tf = int(anim.lottie_animation_get_totalframe())
        ofps = float(anim.lottie_animation_get_framerate())
        
        frames = range(0, tf, FRAME_SKIP)
        nf = len(frames)
        fps = max(1, min(math.ceil(ofps / FRAME_SKIP), MAX_FPS))
        
        # Настраиваем холст
        out_w = MAX_DIM
        out_h = int(out_w / WIDE_RATIO)
        out_w = out_w if out_w % 2 == 0 else out_w - 1
        out_h = out_h if out_h % 2 == 0 else out_h - 1

        # Рендерим модель во всю высоту холста
        target_h = out_h
        target_w = int(w * (target_h / h))
        
        # Если модель шире, чем наш холст - обрезаем края
        if target_w > out_w:
            target_w = out_w
            target_h = int(h * (target_w / w))

        offset_x = (out_w - target_w) // 2
        offset_y = (out_h - target_h) // 2

        log.info(f"Render: Canvas {out_w}x{out_h}, Model {target_w}x{target_h}")

        fdir = work_dir / "frames"
        fdir.mkdir(parents=True, exist_ok=True)
        
        for idx, i in enumerate(frames):
            fp = fdir / f"f_{idx:06d}.png"
            
            img = anim.render_pillow_frame(frame_num=i, width=target_w, height=target_h)
            
            # Создаем холст
            bg = Image.new("RGBA", (out_w, out_h), BG_COLOR)
            
            if img.mode == "RGBA":
                bg.paste(img, (offset_x, offset_y), img)
            else:
                bg.paste(img, (offset_x, offset_y))
            
            try:
                bg.save(str(fp), format="PNG", compress_level=1)
            finally:
                cl = getattr(img, "close", None)
                if callable(cl): cl()
                cl_bg = getattr(bg, "close", None)
                if callable(cl_bg): cl_bg()
                    
        dst = getattr(anim, "lottie_animation_destroy", None)
        if callable(dst):
            dst()
        anim = None
        
        cmd = [
            ff, "-y", "-framerate", str(fps),
            "-i", str(fdir / "f_%06d.png"),
            "-an", "-c:v", "libx264",
            "-preset", MP4_PRESET,
            "-crf", str(MP4_CRF),
            "-pix_fmt", MP4_PIX,
            "-movflags", "+faststart",
            str(mp4_path)
        ]
        
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
        if res.returncode != 0:
            raise RuntimeError(f"ffmpeg err: {res.stderr[-500:]}")
    finally:
        if anim is not None:
            dst = getattr(anim, "lottie_animation_destroy", None)
            if callable(dst):
                try:
                    dst()
                except:
                    pass

async def gen_ids(slug, chat_id):
    async with sem:
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            jp = wd / "a.json"
            mp = wd / "a.mp4"
            
            await dl_lottie(slug, jp)
            await asyncio.to_thread(conv_sync, jp, mp, wd)
            
            mid = None
            gid = None
            try:
                msg = await bot.send_animation(
                    chat_id=chat_id,
                    animation=FSInputFile(str(mp), filename=f"{slug}.mp4"),
                    caption=f"NFT: {slug}",
                )
                if msg.animation:
                    mid = msg.animation.file_id
            except Exception:
                log.exception("send err")
            return gid, mid

def fmt_cap(nft):
    s = html.escape(nft.get("slug") or "")
    m = html.escape(nft.get("model") or "-")
    b = html.escape(nft.get("backdrop") or "-")
    sy = html.escape(nft.get("symbol") or "-")
    u = html.escape(nft.get("page_url") or "")
    
    t = f"<b>{s}</b>\n"
    t += f"Model: {m}\n"
    t += f"Bg: {b}\n"
    t += f"Pattern: {sy}\n"
    t += f"<a href='{u}'>Link</a>"
    return t

@dp.message(CommandStart())
async def start(msg: Message):
    me = await bot.get_me()
    t = f"Bot {VERSION}\n"
    t += f"Search: @{me.username}"
    await msg.answer(t, parse_mode="HTML")

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
                await msg.answer_animation(
                    animation=ext["mpeg4_file_id"],
                    caption=fmt_cap(ext),
                    parse_mode="HTML",
                )
                return
            except:
                pass

        st = await msg.answer("Wait...")
        try:
            d = await fetch_meta(slug)
            await st.edit_text("Render...")
            
            gid, mid = await gen_ids(slug, msg.chat.id)
            
            uid = msg.from_user.id if msg.from_user else 0
            save_nft(d, gid, mid, uid)
            
            me = await bot.get_me()
            tt = f"Done!\n@{me.username}"
            await st.edit_text(tt)
        except Exception as e:
            try:
                await st.edit_text(f"Err: {e}")
            except:
                pass
        finally:
            if locks.get(slug) is lk:
                locks.pop(slug, None)

@dp.inline_query()
async def inline(q: InlineQuery):
    s = (q.query or "").strip()
    items = get_nfts(s, lim=50)
    res = []

    for n in items:
        cap = fmt_cap(n)
        mid = n.get("mpeg4_file_id")
        gid = n.get("gif_file_id")
        
        if mid:
            r = InlineQueryResultCachedMpeg4Gif(
                id=n["slug"],
                mpeg4_file_id=mid,
                caption=cap,
                parse_mode="HTML",
            )
            res.append(r)
        elif gid:
            r = InlineQueryResultCachedGif(
                id=n["slug"],
                gif_file_id=gid,
                caption=cap,
                parse_mode="HTML",
            )
            res.append(r)

    try:
        await q.answer(results=res, cache_time=1, is_personal=True)
    except:
        pass

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
