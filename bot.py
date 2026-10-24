# ===== АВТОУСТАНОВКА БИБЛИОТЕК =====
import subprocess
import sys
import importlib

REQUIRED_LIBS = {
    "aiogram": "aiogram",
    "aiosqlite": "aiosqlite",
    "aiohttp": "aiohttp",
    "pyppeteer": "pyppeteer",
    "bs4": "beautifulsoup4",
    "PIL": "pillow",
}

for module_name, pip_name in REQUIRED_LIBS.items():
    try:
        importlib.import_module(module_name)
    except ImportError:
        print(f"[auto-install] Устанавливаю {pip_name}...", flush=True)
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", "--quiet", pip_name])
            print(f"[auto-install] {pip_name} установлен", flush=True)
        except Exception as e:
            print(f"[auto-install] Ошибка установки {pip_name}: {e}", flush=True)
# ====================================

import asyncio
import logging
import aiosqlite
import json
import re
import time
import shutil
import html
import aiohttp
import os
import io
import tempfile
import subprocess
import math
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup
from PIL import Image

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InlineQueryResultCachedPhoto,
    InputTextMessageContent, BufferedInputFile,
    LabeledPrice, PreCheckoutQuery,
    ChosenInlineResult, FSInputFile, InputMediaAnimation
)
import pyppeteer

from messages import MESSAGES

# ---------- КОНФИГ ----------
BOT_TOKEN = "09787"
ADMIN_IDS = [1012040843]
DB_PATH = "sales.db"
BOT_URL = "https://t.me/Stars2ProfitBot"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

db = None
browser_instance = None
gif_render_lock = asyncio.Lock()

# ---------- ЭМОДЗИ ----------
EMOJI_COLLECTION_FALLBACK = "🎁"
EMOJI_DIAMOND  = '<tg-emoji emoji-id="5296742257146241213">💎</tg-emoji>'
EMOJI_MONEY    = '<tg-emoji emoji-id="5902206159095339799">🤑</tg-emoji>'
EMOJI_DOLLAR   = '<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji>'
EMOJI_LINK     = '<tg-emoji emoji-id="6028171274939797252">🔗</tg-emoji>'

EMOJI_MODEL_FALLBACK    = "🎨"
EMOJI_BACKDROP_FALLBACK = "⚫"
EMOJI_SYMBOL_FALLBACK   = "🌸"

# ---------- ТРОТТЛИНГ ----------
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit=0.3):
        self.rate_limit = rate_limit
        self.users_last_call = defaultdict(float)

    async def __call__(self, handler, event, data):
        user_id = None
        if hasattr(event, 'from_user') and event.from_user:
            user_id = event.from_user.id
        elif hasattr(event, 'message') and event.message:
            user_id = event.message.from_user.id
        if user_id:
            now = time.monotonic()
            if now - self.users_last_call[user_id] < self.rate_limit:
                return
            self.users_last_call[user_id] = now
        try:
            return await handler(event, data)
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            if isinstance(event, Message):
                try:
                    await event.answer("❌ Внутренняя ошибка. Попробуйте позже.")
                except:
                    pass
            return

dp.message.middleware(ThrottlingMiddleware(0.5))
dp.callback_query.middleware(ThrottlingMiddleware(0.3))

# ---------- FSM ----------
class AddProfit(StatesGroup):
    waiting_for_nft_link = State()
    waiting_for_buy_amount = State()
    waiting_for_category = State()
    waiting_for_sell_amount = State()
    waiting_for_royalty = State()

class PendingBuy(StatesGroup):
    waiting_for_nft_link = State()
    waiting_for_buy_amount = State()
    waiting_for_category = State()
    waiting_for_royalty = State()

class CompletePending(StatesGroup):
    waiting_for_select = State()
    waiting_for_confirm = State()
    waiting_for_sell_amount = State()
    waiting_for_royalty = State()

class CalcStates(StatesGroup):
    waiting_for_amount = State()

class AlertStates(StatesGroup):
    waiting_for_price = State()

class SetRoyalty(StatesGroup):
    waiting_for_royalty = State()

class SetGoal(StatesGroup):
    waiting_for_goal = State()

class SetStarRate(StatesGroup):
    waiting_for_rate = State()

class SetChangeAlert(StatesGroup):
    waiting_for_percent = State()

class BroadcastState(StatesGroup):
    waiting_for_message = State()

class EditProfit(StatesGroup):
    waiting_for_buy_amount = State()
    waiting_for_category = State()
    waiting_for_nft_link = State()
    waiting_for_sell_amount = State()
    waiting_for_royalty = State()

class DeleteConfirm(StatesGroup):
    waiting = State()

class DeletePendingConfirm(StatesGroup):
    waiting = State()

class AddAdminState(StatesGroup):
    waiting_for_id = State()

class RemoveAdminState(StatesGroup):
    waiting_for_id = State()

class DonateStars(StatesGroup):
    waiting_for_amount = State()

class TimerAdd(StatesGroup):
    waiting_for_nft_link = State()
    waiting_for_days = State()

class GifSettingsStates(StatesGroup):
    waiting_for_value = State()

# ---------- ЯЗЫК ----------
async def get_user_lang(user_id):
    conn = await get_db()
    cur = await conn.execute("SELECT lang FROM user_settings WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return row[0] if row else "ru"

async def set_user_lang(user_id, lang):
    conn = await get_db()
    await conn.execute("INSERT OR REPLACE INTO user_settings (user_id, lang) VALUES (?,?)", (user_id, lang))
    await conn.commit()

# ---------- БАЗА ДАННЫХ ----------
async def get_db():
    global db
    if db is None:
        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
    return db

async def get_gif_settings():
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM gif_settings WHERE id=1")
    row = await cur.fetchone()
    if not row:
        return {"width": 1024, "height": 576, "fps": 30, "frame_skip": 3, "crf": 23, "preset": "veryfast"}
    return dict(row)

async def init_db():
    conn = await get_db()
    await conn.executescript('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT,
            nft_link TEXT,
            nft_image TEXT,
            thumb_file_id TEXT,
            nft_name TEXT,
            date TEXT,
            buy_amount REAL,
            sell_amount REAL,
            gram_price REAL DEFAULT 0,
            gram_price_buy REAL DEFAULT 0,
            gram_price_sell REAL DEFAULT 0,
            profit_gram REAL,
            profit_usd REAL,
            royalty_gram REAL DEFAULT 0,
            gift_name TEXT,
            model TEXT,
            model_rarity TEXT,
            model_emoji_id TEXT,
            backdrop TEXT,
            backdrop_rarity TEXT,
            backdrop_emoji_id TEXT,
            symbol TEXT,
            symbol_rarity TEXT,
            symbol_emoji_id TEXT,
            collection_emoji_id TEXT,
            gif_file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pending_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT,
            nft_link TEXT,
            thumb_file_id TEXT,
            date TEXT,
            buy_amount REAL,
            gram_price REAL DEFAULT 0,
            gram_price_buy REAL DEFAULT 0,
            royalty_gram REAL DEFAULT 0,
            gift_name TEXT,
            model TEXT,
            model_rarity TEXT,
            model_emoji_id TEXT,
            backdrop TEXT,
            backdrop_rarity TEXT,
            backdrop_emoji_id TEXT,
            symbol TEXT,
            symbol_rarity TEXT,
            symbol_emoji_id TEXT,
            collection_emoji_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_royalty (
            user_id INTEGER PRIMARY KEY,
            royalty_gram REAL DEFAULT 0.3,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            joined_date TIMESTAMP,
            last_activity TIMESTAMP,
            referred_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS profit_goals (
            user_id INTEGER PRIMARY KEY,
            goal_gram REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notified INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS gram_alerts (
            user_id INTEGER PRIMARY KEY,
            target_price REAL,
            enabled INTEGER DEFAULT 1,
            notified INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS user_star_rates (
            user_id INTEGER PRIMARY KEY,
            star_rate REAL DEFAULT 0.013,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_change_alerts (
            user_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            percent REAL DEFAULT 5.0,
            disabled_until REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS gram_price_log (
            timestamp REAL PRIMARY KEY,
            price REAL
        );
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            lang TEXT DEFAULT 'ru'
        );
        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            date TEXT,
            telegram_payment_charge_id TEXT
        );
        CREATE TABLE IF NOT EXISTS timers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_type TEXT,
            nft_link TEXT,
            stars_amount INTEGER,
            event_time REAL,
            description TEXT,
            notified INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS user_earnings_reports (
            user_id INTEGER PRIMARY KEY,
            weekly INTEGER DEFAULT 1,
            monthly INTEGER DEFAULT 1,
            yearly INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS user_collections (
            user_id INTEGER,
            collection_name TEXT,
            last_used TIMESTAMP,
            use_count INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, collection_name)
        );
        CREATE TABLE IF NOT EXISTS referrals (
            user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER,
            date_joined TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS inline_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            deal_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_type TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reported INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS gif_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            width INTEGER DEFAULT 1024,
            height INTEGER DEFAULT 576,
            fps INTEGER DEFAULT 30,
            frame_skip INTEGER DEFAULT 3,
            crf INTEGER DEFAULT 23,
            preset TEXT DEFAULT 'veryfast'
        );
        INSERT OR IGNORE INTO gif_settings (id) VALUES (1);
        CREATE TABLE IF NOT EXISTS gif_cache (
            slug TEXT PRIMARY KEY,
            file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            slug TEXT NOT NULL,
            sale_id INTEGER,
            state TEXT DEFAULT 'bought',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    for col, typ in [('nft_link', 'TEXT'), ('gram_price', 'REAL DEFAULT 0'), ('gram_price_buy', 'REAL DEFAULT 0'), ('royalty_gram', 'REAL DEFAULT 0'), ('thumb_file_id', 'TEXT')]:
        try: await conn.execute(f"ALTER TABLE pending_sales ADD COLUMN {col} {typ}")
        except: pass
    for col in ['nft_image', 'nft_name', 'collection_emoji_id', 'gif_file_id', 'thumb_file_id']:
        try: await conn.execute(f"ALTER TABLE sales ADD COLUMN {col} TEXT")
        except: pass
    for col, typ in [('gram_price_buy', 'REAL DEFAULT 0'), ('gram_price_sell', 'REAL DEFAULT 0')]:
        try: await conn.execute(f"ALTER TABLE sales ADD COLUMN {col} {typ}")
        except: pass
    nft_cols = [('gift_name', 'TEXT'), ('model', 'TEXT'), ('model_rarity', 'TEXT'), ('model_emoji_id', 'TEXT'), ('backdrop', 'TEXT'), ('backdrop_rarity', 'TEXT'), ('backdrop_emoji_id', 'TEXT'), ('symbol', 'TEXT'), ('symbol_rarity', 'TEXT'), ('symbol_emoji_id', 'TEXT'), ('collection_emoji_id', 'TEXT')]
    for col, typ in nft_cols:
        try: await conn.execute(f"ALTER TABLE sales ADD COLUMN {col} {typ}")
        except: pass
        try: await conn.execute(f"ALTER TABLE pending_sales ADD COLUMN {col} {typ}")
        except: pass
    try: await conn.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
    except: pass
    try: await conn.execute("ALTER TABLE user_change_alerts ADD COLUMN disabled_until REAL DEFAULT 0")
    except: pass
    for admin_id in ADMIN_IDS:
        try: await conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (admin_id,))
        except: pass
    await conn.commit()

# ---------- ЛОГИРОВАНИЕ ----------
async def log_action(user_id: int, username: str, action: str, details: str = ""):
    try:
        conn = await get_db()
        await conn.execute("INSERT INTO action_logs (user_id, username, action, details) VALUES (?,?,?,?)", (user_id, username or "", action, details[:500]))
        await conn.execute("DELETE FROM action_logs WHERE id NOT IN (SELECT id FROM action_logs ORDER BY id DESC LIMIT 500)")
        await conn.commit()
    except Exception as e:
        logger.error(f"Log action error: {e}")

async def log_error(error_type: str, details: str):
    try:
        conn = await get_db()
        await conn.execute("INSERT INTO error_logs (error_type, details) VALUES (?,?)", (error_type, details[:2000]))
        await conn.execute("DELETE FROM error_logs WHERE id NOT IN (SELECT id FROM error_logs ORDER BY id DESC LIMIT 500)")
        await conn.commit()
    except Exception as e:
        logger.error(f"Log error failure: {e}")

# ---------- КУРС ----------
gram_cache = {"price": 0.0, "timestamp": 0}

async def get_gram_price():
    if gram_cache["price"] > 0 and (time.time() - gram_cache["timestamp"]) < 300:
        return gram_cache["price"]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd", timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = data.get("the-open-network", {}).get("usd")
                    if price and price > 0:
                        gram_cache["price"] = price
                        gram_cache["timestamp"] = time.time()
                        return price
    except Exception as e:
        logger.warning(f"get_gram_price error: {e}")
    return gram_cache["price"] if gram_cache["price"] > 0 else 1.5

def compute_profit_usd(buy_amount, sell_amount, royalty, gram_price_buy, gram_price_sell, fallback_gram_price=0.0):
    try:
        gp_buy  = float(gram_price_buy or 0)
        gp_sell = float(gram_price_sell or 0)
        if gp_buy > 0 and gp_sell > 0:
            cost_usd    = float(buy_amount)  * gp_buy
            revenue_usd = float(sell_amount) * gp_sell
            royalty_usd = float(royalty or 0) * gp_sell
            return round(revenue_usd - cost_usd - royalty_usd, 2)
        profit_gram = float(sell_amount) - float(buy_amount) - float(royalty or 0)
        gp = float(fallback_gram_price or 0)
        return round(profit_gram * gp, 2)
    except Exception as e:
        logger.warning(f"[compute_profit_usd] {e}")
        return 0.0

def get_profit_emoji(p):
    if p > 1: return "🚀"
    elif p > 0.5: return "💎"
    elif p > 0: return "📈"
    elif p == 0: return "➖"
    elif p > -0.5: return "📉"
    else: return "💀"

def make_progress_bar(value, max_value, length=12):
    if max_value <= 0:
        return "░" * length + " 0%"
    filled = int(length * min(value, max_value) / max_value)
    bar = "█" * filled + "░" * (length - filled)
    pct = value / max_value * 100
    return f"{bar} {pct:.1f}%"

async def is_admin(user_id):
    conn = await get_db()
    cur = await conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    return await cur.fetchone() is not None

async def add_admin(user_id):
    conn = await get_db()
    await conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    await conn.commit()

async def remove_admin(user_id):
    conn = await get_db()
    await conn.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    await conn.commit()

async def add_user_collection(user_id, collection_name):
    conn = await get_db()
    await conn.execute("INSERT INTO user_collections (user_id, collection_name, last_used, use_count) VALUES (?,?,datetime('now'),1) ON CONFLICT(user_id, collection_name) DO UPDATE SET last_used=datetime('now'), use_count=use_count+1", (user_id, collection_name))
    await conn.commit()

async def get_user_star_rate(user_id):
    conn = await get_db()
    cur = await conn.execute("SELECT star_rate FROM user_star_rates WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return row[0] if row else 0.013

async def save_user_star_rate(user_id, rate):
    conn = await get_db()
    await conn.execute("INSERT OR REPLACE INTO user_star_rates (user_id, star_rate, updated_at) VALUES (?,?,datetime('now'))", (user_id, rate))
    await conn.commit()

async def get_user_royalty(user_id):
    conn = await get_db()
    cur = await conn.execute("SELECT royalty_gram FROM user_royalty WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return row[0] if row else 0.3

async def get_user_change_alert(user_id):
    conn = await get_db()
    cur = await conn.execute("SELECT enabled, percent, disabled_until FROM user_change_alerts WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    if row: return bool(row[0]), row[1], row[2] or 0
    return False, 5.0, 0

async def set_user_change_alert(user_id, enabled, percent=5.0):
    conn = await get_db()
    await conn.execute("INSERT OR REPLACE INTO user_change_alerts (user_id, enabled, percent) VALUES (?,?,?)", (user_id, int(enabled), percent))
    await conn.commit()

async def check_goal_achievement(user_id):
    conn = await get_db()
    cur = await conn.execute("SELECT goal_gram, notified FROM profit_goals WHERE user_id=?", (user_id,))
    goal_row = await cur.fetchone()
    if not goal_row: return
    goal_gram, notified = goal_row
    if notified: return
    cur = await conn.execute("SELECT SUM(profit_gram) FROM sales WHERE user_id=?", (user_id,))
    total_profit = (await cur.fetchone())[0] or 0
    if total_profit >= goal_gram:
        await conn.execute("UPDATE profit_goals SET notified=1 WHERE user_id=?", (user_id,))
        await conn.commit()
        lang = await get_user_lang(user_id)
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=MESSAGES[lang]["goal_set_new"], callback_data="set_goal")],
                [InlineKeyboardButton(text=MESSAGES[lang]["goal_later"], callback_data="goal_later")]
            ])
            await bot.send_message(user_id, MESSAGES[lang]["goal_achieved"].format(goal=f"{goal_gram:.2f}", total=f"{total_profit:.4f}"), reply_markup=kb)
            await log_action(user_id, "", "goal_achieved", f"Цель {goal_gram:.2f} GRAM")
        except Exception as e:
            logger.error(f"Goal notification error: {e}")

async def activate_referral(user_id: int):
    conn = await get_db()
    cur = await conn.execute("SELECT referrer_id, is_active FROM referrals WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    if not row: return
    referrer_id, is_active = row
    if is_active: return
    await conn.execute("UPDATE referrals SET is_active=1 WHERE user_id=?", (user_id,))
    await conn.commit()
    if referrer_id:
        try:
            await bot.send_message(referrer_id, f"🎉 <b>Ваш реферал активен!</b>\n\nПользователь сделал первую сделку.\nВам начислено <b>+10 очков</b> репутации.")
        except: pass

def get_referral_level(points: int, lang: str = "ru") -> str:
    msgs = MESSAGES[lang]
    if points >= 500: return msgs["referrals_level_platinum"]
    elif points >= 200: return msgs["referrals_level_gold"]
    elif points >= 50: return msgs["referrals_level_silver"]
    else: return msgs["referrals_level_bronze"]

def get_next_level_points(points: int) -> int:
    if points < 50: return 50 - points
    elif points < 200: return 200 - points
    elif points < 500: return 500 - points
    return 0

def _esc(s):
    if s is None:
        return ""
    return html.escape(str(s))

def parse_gift_info_from_link(nft_link: str):
    if not nft_link: return None, None, None
    link = nft_link.strip().split("?")[0].split("#")[0].rstrip("/")
    if "/nft/" not in link: return None, None, None
    try:
        gift_part = link.split("/nft/")[1]
        gift_segment = gift_part.split("/")[0]
        if "-" not in gift_segment: return None, None, None
        slug_raw, number_raw = gift_segment.rsplit("-", 1)
        if not number_raw.isdigit(): return None, None, None
        number = int(number_raw)
        slug = slug_raw.lower()
        gift_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', slug_raw).replace("Durovs", "Durov's")
        gift_name = re.sub(r'\bs\s', "'s ", gift_name).strip()
        return gift_name, slug, number
    except: return None, None, None

async def get_gift_from_fragment(slug: str, number: int):
    url = f"https://nft.fragment.com/gift/{slug}-{number}.json"
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}) as resp:
                if resp.status != 200: return None
                data = json.loads(await resp.text())
                attrs = data.get("attributes") or []
                result = {}
                for attr in attrs:
                    t, v = (attr.get("trait_type") or "").lower(), attr.get("value")
                    if t == "model": result["model_name"] = v
                    elif t == "backdrop": result["backdrop_name"] = v
                    elif t == "symbol": result["symbol_name"] = v
                result["gift_name"] = data.get("name") or None
                result["image"] = data.get("image") or None
                return result if any(result.get(k) for k in ("model_name", "backdrop_name", "symbol_name")) else None
    except: return None

def _parse_tme_description(description: str) -> dict:
    result = {}
    if not description: return result
    for raw_line in description.split("\n"):
        line = raw_line.strip()
        if not line: continue
        m = re.match(r'^Model\s*:\s*(.+)$', line, re.IGNORECASE)
        if m: result["model_name"] = m.group(1).strip().rstrip("."); continue
        m = re.match(r'^Backdrop\s*:\s*(.+)$', line, re.IGNORECASE)
        if m: result["backdrop_name"] = m.group(1).strip().rstrip("."); continue
        m = re.match(r'^Symbol\s*:\s*(.+)$', line, re.IGNORECASE)
        if m: result["symbol_name"] = m.group(1).strip().rstrip("."); continue
    if result: return result
    m = re.search(r'appearance\s+(.+?)\s+on\s+an?\s+(.+?)\s+background\s+with\s+(.+?)\s+icons?', description, re.IGNORECASE)
    if m: return {"model_name": m.group(1).strip(), "backdrop_name": m.group(2).strip(), "symbol_name": m.group(3).strip()}
    for key, field in (("model_name", "Model"), ("backdrop_name", "Backdrop"), ("symbol_name", "Symbol")):
        m = re.search(rf'{field}\s*:\s*([^.\n]+)', description, re.IGNORECASE)
        if m: result[key] = m.group(1).strip()
    return result

async def get_gift_from_tme(nft_link: str):
    url = nft_link.strip()
    if not url.startswith("http"): url = "https://" + url
    url = url.rstrip("/")
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"}, allow_redirects=True) as resp:
                if resp.status != 200: return None
                html_text = await resp.text()
                m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html_text)
                if not m: m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']', html_text)
                if not m: return None
                description = html.unescape(m.group(1))
                result = _parse_tme_description(description)
                return result if any(result.get(k) for k in ("model_name", "backdrop_name", "symbol_name")) else None
    except: return None

async def get_gift_catalog_from_changes(gift_name: str):
    if not gift_name: return None
    slug = gift_name.lower().strip().replace("’", "").replace("'", "").replace("`", "").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    if not slug: return None
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"https://api.changes.tg/emoji/{slug}", headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}) as resp:
                if resp.status != 200: return None
                data = json.loads(await resp.text())
                catalog = {"models": {}, "backdrops": {}, "symbols": {}, "collection_emoji_id": data.get("originalCustomEmojiId")}
                def fmt_rarity(val):
                    if val is None: return None
                    try:
                        v = float(val)
                        return f"{int(v) if v == int(v) else v}%"
                    except: return f"{val}%"
                for src_key, dst_key in (("models", "models"), ("backdrops", "backdrops"), ("patterns", "symbols")):
                    for item in (data.get(src_key) or []):
                        if isinstance(item, dict) and item.get("name"):
                            catalog[dst_key][item["name"].lower()] = {"name": item["name"], "rarity": fmt_rarity(item.get("rarity")), "emoji_id": item.get("customEmojiId")}
                for old_key, dst_key in (("model", "models"), ("backdrop", "backdrops"), ("pattern", "symbols")):
                    item = data.get(old_key)
                    if isinstance(item, dict) and item.get("name"):
                        key = item["name"].lower()
                        if key not in catalog[dst_key]:
                            catalog[dst_key][key] = {"name": item.get("name"), "rarity": fmt_rarity(item.get("rarity")), "emoji_id": item.get("customEmojiId")}
                return catalog
    except: return None

def _find_in_catalog(catalog: dict, section: str, name: str):
    if not catalog or not name: return None
    bucket = catalog.get(section) or {}
    key = name.strip().lower()
    if key in bucket: return bucket[key]
    def norm(s): return re.sub(r"[^a-z0-9]", "", s.lower())
    nkey = norm(name)
    for k, v in bucket.items():
        if norm(k) == nkey: return v
    return None

async def parse_nft_link(nft_link: str):
    gift_name, slug, number = parse_gift_info_from_link(nft_link)
    if not gift_name or slug is None or number is None: return None
    result = {"gift_name": gift_name}
    catalog = await get_gift_catalog_from_changes(gift_name)
    source_data = await get_gift_from_fragment(slug, number)
    if not source_data:
        source_data = await get_gift_from_tme(nft_link)
    if not source_data:
        if catalog and catalog.get("collection_emoji_id"): result["collection_emoji_id"] = catalog["collection_emoji_id"]
        return result
    if source_data.get("gift_name"): result["gift_name"] = source_data["gift_name"]
    if source_data.get("image"): result["nft_image"] = source_data["image"]

    for name_key, section, out_prefix in (("model_name", "models", "model"), ("backdrop_name", "backdrops", "backdrop"), ("symbol_name", "symbols", "symbol")):
        real_name = source_data.get(name_key)
        if not real_name: continue
        result[out_prefix] = real_name
        match = _find_in_catalog(catalog, section, real_name)
        if match:
            result[f"{out_prefix}_rarity"] = match.get("rarity")
            result[f"{out_prefix}_emoji_id"] = match.get("emoji_id")
        else:
            result[f"{out_prefix}_rarity"] = None
            result[f"{out_prefix}_emoji_id"] = None
    if catalog and catalog.get("collection_emoji_id"): result["collection_emoji_id"] = catalog["collection_emoji_id"]
    return result

def premium_emoji(emoji_id, fallback: str) -> str:
    if emoji_id: return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback

def get_collection_emoji_html(deal: dict) -> str:
    eid = deal.get("collection_emoji_id") if deal else None
    return premium_emoji(eid, EMOJI_COLLECTION_FALLBACK)

def format_gift_attributes(data: dict) -> str:
    if not data: return ""
    lines = []
    if data.get("model"):
        emoji = premium_emoji(data.get("model_emoji_id"), EMOJI_MODEL_FALLBACK)
        rarity = f" {data['model_rarity']}" if data.get("model_rarity") else ""
        lines.append(f"{emoji} {data['model']}{rarity}")
    if data.get("backdrop"):
        emoji = premium_emoji(data.get("backdrop_emoji_id"), EMOJI_BACKDROP_FALLBACK)
        rarity = f" {data['backdrop_rarity']}" if data.get("backdrop_rarity") else ""
        lines.append(f"{emoji} {data['backdrop']}{rarity}")
    if data.get("symbol"):
        emoji = premium_emoji(data.get("symbol_emoji_id"), EMOJI_SYMBOL_FALLBACK)
        rarity = f" {data['symbol_rarity']}" if data.get("symbol_rarity") else ""
        lines.append(f"{emoji} {data['symbol']}{rarity}")
    return "\n".join(lines)

def get_main_kb(lang="ru"):
    msgs = MESSAGES[lang]
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=msgs["main_add_deal"])],
            [KeyboardButton(text=msgs["main_pending_buy"]), KeyboardButton(text=msgs["main_complete_deal"])],
            [KeyboardButton(text=msgs["main_history"]), KeyboardButton(text=msgs["main_stats"])],
            [KeyboardButton(text=msgs["main_calculator"]), KeyboardButton(text=msgs["main_settings"])],
            [KeyboardButton(text=msgs["main_timers"]), KeyboardButton(text=msgs["main_donate"])],
            [KeyboardButton(text=msgs["main_referrals"]), KeyboardButton(text=msgs["lang_btn"])],
        ],
        resize_keyboard=True
    )

def get_cancel_kb(lang="ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])

async def download_file(url, path):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120), headers={"User-Agent": "Mozilla/5.0"}) as s:
        async with s.get(url) as r:
            if r.status != 200: raise ValueError(f"HTTP {r.status}")
            d = await r.read()
    path.write_bytes(d)

async def upload_thumb_to_telegram(image_url, fallback_text="🎁"):
    if not image_url:
        try:
            img = Image.new("RGB", (320, 320), color=(30, 30, 40))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            msg = await bot.send_photo(chat_id=ADMIN_IDS[0], photo=BufferedInputFile(buf.getvalue(), filename="thumb_placeholder.jpg"), disable_notification=True)
            file_id = msg.photo[-1].file_id
            try: await bot.delete_message(chat_id=ADMIN_IDS[0], message_id=msg.message_id)
            except: pass
            return file_id
        except Exception as e:
            return None
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as s:
            async with s.get(image_url) as r:
                if r.status != 200: return None
                data = await r.read()
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.thumbnail((320, 320), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            payload = buf.getvalue()
            fname = "thumb.jpg"
        except:
            payload = data
            fname = "thumb.webp"
        msg = await bot.send_photo(chat_id=ADMIN_IDS[0], photo=BufferedInputFile(payload, filename=fname), disable_notification=True)
        file_id = msg.photo[-1].file_id
        try: await bot.delete_message(chat_id=ADMIN_IDS[0], message_id=msg.message_id)
        except: pass
        return file_id
    except: return None

async def render_gif_for_nft(slug, work_dir):
    s = await get_gif_settings()
    R_W = s["width"]; R_H = s["height"]; R_FPS = s["fps"]
    R_SKIP = s["frame_skip"]; R_CRF = s["crf"]; R_PRESET = s["preset"]
    json_path = work_dir / "a.json"; mp4_path = work_dir / "a.mp4"
    lottie_url = f"https://nft.fragment.com/gift/{slug}.lottie.json"
    await download_file(lottie_url, json_path)
    with open(json_path, "r", encoding="utf-8") as f: data = json.load(f)
    comp_w = int(data.get('w', 512)); comp_h = int(data.get('h', 512))
    frame_rate = float(data.get('fr', 60)); ip, op = float(data.get('ip', 0)), float(data.get('op', 1))
    step = max(1, round(frame_rate / R_FPS))
    frame_numbers = list(range(int(ip), int(op), step)) or [int(ip)]
    frame_numbers = frame_numbers[::R_SKIP]
    final_fps = max(1, math.ceil(R_FPS / R_SKIP))
    layers = data.get('layers', [])
    bg_layers = [x for x in layers if x.get('nm') in {'Background', 'Pattern', 'Color Icon'}]
    anim_layers = [x for x in layers if x.get('nm') in {'Gift'}]
    if not bg_layers or not anim_layers: raise RuntimeError("Не найдены слои")
    bg_data = dict(data); bg_data['layers'] = bg_layers
    anim_data = dict(data); anim_data['layers'] = anim_layers
    html_content = f"""
    <!DOCTYPE html><html><head><script src="https://cdnjs.cloudflare.com/ajax/libs/bodymovin/5.12.2/lottie.min.js"></script>
    <style>body {{ margin: 0; padding: 0; background: transparent; overflow: hidden; }}
    #bg {{ position: absolute; top: 0; left: 0; width: {R_W}px; height: {R_H}px; }}
    #gift {{ position: absolute; top: {(R_H - comp_h)//2}px; left: {(R_W - comp_w)//2}px; width: {comp_w}px; height: {comp_h}px; }}
    #bg svg {{ width: 100% !important; height: 100% !important; }} #gift svg {{ width: 100% !important; height: 100% !important; }}</style></head>
    <body><div id="bg"></div><div id="gift"></div><script>
    const bgAnim = lottie.loadAnimation({{container: document.getElementById('bg'), renderer: 'svg', loop: false, autoplay: false, animationData: {json.dumps(bg_data)}, rendererSettings: {{ preserveAspectRatio: 'none' }}}});
    const giftAnim = lottie.loadAnimation({{container: document.getElementById('gift'), renderer: 'svg', loop: false, autoplay: false, animationData: {json.dumps(anim_data)}, rendererSettings: {{ preserveAspectRatio: 'xMidYMid meet' }}}});
    window.setFrame = (f) => {{ bgAnim.goToAndStop(f, true); giftAnim.goToAndStop(f, true); }}; window.ready = true;
    </script></body></html>"""
    html_path = work_dir / "render.html"
    with open(html_path, "w", encoding="utf-8") as f: f.write(html_content)
    page = await browser_instance.newPage()
    await page.setViewport({'width': R_W, 'height': R_H})
    await page.goto(f"file://{html_path}")
    await page.waitForFunction('window.ready === true')
    fdir = work_dir / "frames"; fdir.mkdir(parents=True, exist_ok=True)
    for idx, i in enumerate(frame_numbers):
        await page.evaluate(f'setFrame({i})')
        await page.screenshot({'path': str(fdir / f"f_{idx:06d}.png"), 'omitBackground': True})
    await page.close()
    cmd = ["ffmpeg", "-y", "-framerate", str(final_fps), "-i", str(fdir / "f_%06d.png"), "-an", "-c:v", "libx264", "-profile:v", "main", "-level", "4.0", "-preset", R_PRESET, "-crf", str(R_CRF), "-pix_fmt", "yuv420p", "-threads", "0", "-movflags", "+faststart", str(mp4_path)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if res.returncode != 0: raise RuntimeError(f"ffmpeg err: {res.stderr[-500:]}")
    return mp4_path

async def background_gif_render(nft_link):
    if not nft_link or "t.me/nft/" not in nft_link: return
    slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0]
    conn = await get_db()
    cur = await conn.execute("SELECT file_id FROM gif_cache WHERE slug=?", (slug,))
    row = await cur.fetchone()
    if row and row[0]: return
    async with gif_render_lock:
        try:
            if not browser_instance: return
            with tempfile.TemporaryDirectory() as tmp:
                mp4_path = await render_gif_for_nft(slug, Path(tmp))
                msg = await bot.send_animation(chat_id=ADMIN_IDS[0], animation=FSInputFile(str(mp4_path), filename=f"{slug}.mp4"), disable_notification=True)
                file_id = msg.animation.file_id
                try: await bot.delete_message(chat_id=ADMIN_IDS[0], message_id=msg.message_id)
                except: pass
                await conn.execute("INSERT OR REPLACE INTO gif_cache (slug, file_id) VALUES (?, ?)", (slug, file_id))
                await conn.commit()

        # ---------- /start ----------
@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    args = message.text.split()

    if len(args) > 1 and args[1] == "inline_help":
        await message.answer("🔍 Введи номер сделки (#123) или название коллекции.")
        return

    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            if referrer_id != user_id:
                conn = await get_db()
                cur = await conn.execute("SELECT user_id FROM referrals WHERE user_id=?", (user_id,))
                if not await cur.fetchone():
                    await conn.execute("INSERT INTO referrals (user_id, referrer_id) VALUES (?,?)", (user_id, referrer_id))
                    await conn.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referrer_id, user_id))
                    await conn.commit()
        except: pass

    await update_user(message.from_user)
    lang = await get_user_lang(user_id)
    await message.answer(MESSAGES[lang]["start"].format(name=message.from_user.first_name), reply_markup=get_main_kb(lang))

async def update_user(user):
    conn = await get_db()
    await conn.execute(
        "INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, joined_date, last_activity, referred_by) "
        "VALUES (?,?,?,?, COALESCE((SELECT joined_date FROM users WHERE user_id=?), datetime('now')), datetime('now'), (SELECT referred_by FROM users WHERE user_id=?))",
        (user.id, user.username, user.first_name, user.last_name, user.id, user.id)
    )
    await conn.execute("INSERT OR IGNORE INTO user_settings (user_id, lang) VALUES (?, 'ru')", (user.id,))
    await conn.execute("INSERT OR IGNORE INTO user_earnings_reports (user_id) VALUES (?)", (user.id,))
    await conn.commit()

@dp.message(F.text.in_(["🌐 🇷🇺 Русский", "🌐 🇬🇧 English"]))
async def switch_language(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    current_lang = await get_user_lang(user_id)
    new_lang = "en" if current_lang == "ru" else "ru"
    await set_user_lang(user_id, new_lang)
    await message.answer(MESSAGES[new_lang]["lang_changed"], reply_markup=get_main_kb(new_lang))

# ---------- ДОБАВЛЕНИЕ СДЕЛКИ ----------
@dp.message(F.text.in_(["📊 Добавить сделку", "📊 Add Deal"]))
async def add_deal_start(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    await state.set_state(AddProfit.waiting_for_nft_link)
    await message.answer(MESSAGES[lang]["enter_nft_link"], reply_markup=get_cancel_kb(lang))

@dp.message(AddProfit.waiting_for_nft_link)
async def process_nft_link(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    link = message.text.strip()
    if not link or link == "-":
        await message.answer(MESSAGES[lang]["link_required"], reply_markup=get_cancel_kb(lang))
        return
    await state.update_data(nft_link=link)

    nft_data = await parse_nft_link(link)
    if nft_data:
        await state.update_data(**nft_data)
        thumb_id = await upload_thumb_to_telegram(nft_data.get("nft_image"))
        if thumb_id: await state.update_data(thumb_file_id=thumb_id)
        
        attrs = format_gift_attributes(nft_data)
        collection_emoji = premium_emoji(nft_data.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
        gift_name = nft_data.get('gift_name', 'NFT')
        msg_text = f"{collection_emoji} <b>{gift_name}</b>\n{attrs}" if attrs else f"{collection_emoji} <b>{gift_name}</b>\n<i>Характеристики не найдены</i>"
        await message.answer(msg_text, reply_markup=get_cancel_kb(lang))
        asyncio.create_task(background_gif_render(link))

    await state.set_state(AddProfit.waiting_for_buy_amount)
    await message.answer(MESSAGES[lang]["enter_buy_amount"], reply_markup=get_cancel_kb(lang))

@dp.message(AddProfit.waiting_for_buy_amount)
async def process_buy_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
        gram_price_buy = await get_gram_price()
        await state.update_data(buy_amount=amount, gram_price_buy=gram_price_buy)
        await state.set_state(AddProfit.waiting_for_category)
        await message.answer(f"📥 {amount} GRAM\n{EMOJI_DOLLAR} Курс: <b>${gram_price_buy:.4f}</b>\n\n{MESSAGES[lang]['enter_collection']}", reply_markup=get_cancel_kb(lang))
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.message(AddProfit.waiting_for_category)
async def process_category(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    await state.update_data(category=message.text.strip())
    await state.set_state(AddProfit.waiting_for_sell_amount)
    await message.answer(MESSAGES[lang]["enter_sell_amount"], reply_markup=get_cancel_kb(lang))

@dp.message(AddProfit.waiting_for_sell_amount)
async def process_sell_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
        gram_price_sell = await get_gram_price()
        await state.update_data(sell_amount=amount, gram_price_sell=gram_price_sell)
        data = await state.get_data()
        gp_buy = data.get("gram_price_buy", 0)
        royalty = await get_user_royalty(message.from_user.id)
        await state.set_state(AddProfit.waiting_for_royalty)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🔸 {royalty:.2f} GRAM", callback_data=f"royalty_{royalty}")],
            [InlineKeyboardButton(text=MESSAGES[lang]["commission_custom"], callback_data="royalty_custom")],
            [InlineKeyboardButton(text=MESSAGES[lang]["commission_zero"], callback_data="royalty_0")],
            [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
        ])
        await message.answer(f"{EMOJI_DOLLAR} Курс покупки: <b>${gp_buy:.4f}</b>\n{EMOJI_DOLLAR} Курс продажи: <b>${gram_price_sell:.4f}</b>\n\n{MESSAGES[lang]['select_commission'].format(royalty=f'{royalty:.2f}')}", reply_markup=kb)
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.callback_query(F.data.startswith("royalty_"))
async def process_royalty_choice(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    val = callback.data.replace("royalty_", "")
    if val == "custom":
        await callback.message.answer("Введите комиссию в GRAM:", reply_markup=get_cancel_kb(lang))
        return
    royalty = float(val)
    await finalize_profit(callback.message, state, royalty, user_id=callback.from_user.id, lang=lang)

@dp.message(AddProfit.waiting_for_royalty)
async def process_custom_royalty(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        royalty = float(message.text.replace(",", "."))
        if royalty < 0: raise ValueError
        await finalize_profit(message, state, royalty, lang=lang)
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

async def finalize_profit(message: Message, state: FSMContext, royalty: float, user_id: int = None, lang: str = "ru"):
    if user_id is None: user_id = message.from_user.id if hasattr(message, 'from_user') else message.chat.id
    data = await state.get_data()
    buy_amount = data["buy_amount"]; sell_amount = data["sell_amount"]
    gram_price_buy = data.get("gram_price_buy") or 0; gram_price_sell = data.get("gram_price_sell") or 0

    if gram_price_buy <= 0: gram_price_buy = await get_gram_price()
    if gram_price_sell <= 0: gram_price_sell = await get_gram_price()

    profit_gram = sell_amount - buy_amount - royalty
    profit_usd = compute_profit_usd(buy_amount, sell_amount, royalty, gram_price_buy, gram_price_sell, fallback_gram_price=gram_price_sell)
    date = datetime.now().strftime("%d.%m.%Y")

    conn = await get_db()
    await conn.execute(
        """INSERT INTO sales (user_id, category, nft_link, nft_image, thumb_file_id, date, buy_amount, sell_amount, gram_price,
           gram_price_buy, gram_price_sell, profit_gram, profit_usd, royalty_gram, gift_name, model, model_rarity, model_emoji_id,
           backdrop, backdrop_rarity, backdrop_emoji_id, symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, data["category"], data["nft_link"], data.get("nft_image"), data.get("thumb_file_id"), date, buy_amount, sell_amount, gram_price_sell,
         gram_price_buy, gram_price_sell, round(profit_gram, 4), profit_usd, royalty,
         data.get("gift_name"), data.get("model"), data.get("model_rarity"), data.get("model_emoji_id"),
         data.get("backdrop"), data.get("backdrop_rarity"), data.get("backdrop_emoji_id"),
         data.get("symbol"), data.get("symbol_rarity"), data.get("symbol_emoji_id"), data.get("collection_emoji_id"))
    )
    await conn.commit()
    
    # Авто-добавление в трекер GiftSat
    cur = await conn.execute("SELECT last_insert_rowid()")
    sale_id = (await cur.fetchone())[0]
    if data.get("nft_link") and "t.me/nft/" in data["nft_link"]:
        slug = data["nft_link"].split("/nft/")[1].split("/")[0].split("?")[0]
        cur = await conn.execute("SELECT id FROM tracking WHERE user_id=? AND slug=?", (user_id, slug))
        if not await cur.fetchone():
            await conn.execute("INSERT INTO tracking (user_id, slug, sale_id, state) VALUES (?, ?, ?, 'bought')", (user_id, slug, sale_id))
    await conn.commit()

    await add_user_collection(user_id, data["category"])
    await state.clear()
    await activate_referral(user_id)
    await check_goal_achievement(user_id)

    msgs = MESSAGES[lang]
    attrs = format_gift_attributes(data)
    collection_emoji = premium_emoji(data.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
    gift_name = data.get('gift_name') or data.get('category') or 'NFT'
    text = msgs["sale_saved"].format(category=data['category'], buy=buy_amount, sell=sell_amount, royalty=f"{royalty:.2f}", profit=f"{profit_gram:+.4f}", usd=f"{profit_usd:+.2f}")
    header = f"{collection_emoji} <b>{gift_name}</b>\n{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n{EMOJI_DOLLAR} Курс продажи: <b>${gram_price_sell:.4f}</b>"
    if attrs: header = f"{header}\n{attrs}"
    await message.answer(f"{header}\n\n{text}", reply_markup=get_main_kb(lang))

# ---------- ОТЛОЖЕННАЯ ПОКУПКА ----------
@dp.message(F.text.in_(["📥 Отложенная покупка", "📥 Pending Buy"]))
async def pending_start(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    await state.set_state(PendingBuy.waiting_for_nft_link)
    await message.answer(MESSAGES[lang]["enter_nft_link"], reply_markup=get_cancel_kb(lang))

@dp.message(PendingBuy.waiting_for_nft_link)
async def process_pending_nft_link(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    link = message.text.strip()
    if not link or link == "-":
        await message.answer(MESSAGES[lang]["link_required"], reply_markup=get_cancel_kb(lang))
        return
    await state.update_data(nft_link=link)

    nft_data = await parse_nft_link(link)
    if nft_data:
        await state.update_data(**nft_data)
        thumb_id = await upload_thumb_to_telegram(nft_data.get("nft_image"))
        if thumb_id: await state.update_data(thumb_file_id=thumb_id)
        attrs = format_gift_attributes(nft_data)
        collection_emoji = premium_emoji(nft_data.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
        gift_name = nft_data.get('gift_name', 'NFT')
        msg_text = f"{collection_emoji} <b>{gift_name}</b>\n{attrs}" if attrs else f"{collection_emoji} <b>{gift_name}</b>\n<i>Характеристики не найдены</i>"
        await message.answer(msg_text, reply_markup=get_cancel_kb(lang))
        asyncio.create_task(background_gif_render(link))

    await state.set_state(PendingBuy.waiting_for_buy_amount)
    await message.answer(MESSAGES[lang]["enter_buy_amount"], reply_markup=get_cancel_kb(lang))

@dp.message(PendingBuy.waiting_for_buy_amount)
async def process_pending_buy_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
        gram_price_buy = await get_gram_price()
        await state.update_data(buy_amount=amount, gram_price_buy=gram_price_buy)
        await state.set_state(PendingBuy.waiting_for_category)
        await message.answer(f"📥 {amount} GRAM\n{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n\n{MESSAGES[lang]['enter_collection']}", reply_markup=get_cancel_kb(lang))
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.message(PendingBuy.waiting_for_category)
async def process_pending_category(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    await state.update_data(category=message.text.strip())
    royalty = await get_user_royalty(message.from_user.id)
    await state.set_state(PendingBuy.waiting_for_royalty)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔸 {royalty:.2f} GRAM", callback_data=f"pending_royalty_{royalty}")],
        [InlineKeyboardButton(text=MESSAGES[lang]["commission_custom"], callback_data="pending_royalty_custom")],
        [InlineKeyboardButton(text=MESSAGES[lang]["commission_zero"], callback_data="pending_royalty_0")],
        [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])
    await message.answer(MESSAGES[lang]["select_commission"].format(royalty=f"{royalty:.2f}"), reply_markup=kb)

@dp.callback_query(F.data.startswith("pending_royalty_"))
async def process_pending_royalty(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    val = callback.data.replace("pending_royalty_", "")
    if val == "custom":
        await callback.message.answer("Введите комиссию в GRAM:", reply_markup=get_cancel_kb(lang))
        return
    royalty = float(val)
    await save_pending(callback.message, state, royalty, callback.from_user.id, lang)

@dp.message(PendingBuy.waiting_for_royalty)
async def process_pending_custom_royalty(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        royalty = float(message.text.replace(",", "."))
        if royalty < 0: raise ValueError
        await save_pending(message, state, royalty, message.from_user.id, lang)
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

async def save_pending(message: Message, state: FSMContext, royalty: float, user_id: int, lang: str = "ru"):
    data = await state.get_data()
    gram_price_buy = data.get("gram_price_buy") or await get_gram_price()
    conn = await get_db()
    await conn.execute(
        """INSERT INTO pending_sales (user_id, category, nft_link, thumb_file_id, date, buy_amount, gram_price, gram_price_buy, royalty_gram,
           gift_name, model, model_rarity, model_emoji_id, backdrop, backdrop_rarity, backdrop_emoji_id, symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, data["category"], data["nft_link"], data.get("thumb_file_id"), datetime.now().strftime("%d.%m.%Y"),
         data["buy_amount"], gram_price_buy, gram_price_buy, royalty,
         data.get("gift_name"), data.get("model"), data.get("model_rarity"), data.get("model_emoji_id"),
         data.get("backdrop"), data.get("backdrop_rarity"), data.get("backdrop_emoji_id"),
         data.get("symbol"), data.get("symbol_rarity"), data.get("symbol_emoji_id"), data.get("collection_emoji_id"))
    )
    await conn.commit()
    await state.clear()
    msgs = MESSAGES[lang]
    await message.answer(f"{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n\n{msgs['pending_saved'].format(category=data['category'], amount=data['buy_amount'])}", reply_markup=get_main_kb(lang))

# ---------- ЗАВЕРШЕНИЕ СДЕЛКИ ----------
@dp.message(F.text.in_(["📤 Завершить сделку", "📤 Complete Deal"]))
async def complete_start(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    user_id = message.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM pending_sales WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,))
    pending = await cur.fetchall()
    if not pending:
        await message.answer(MESSAGES[lang]["no_pending"], reply_markup=get_main_kb(lang))
        return
    await state.set_state(CompletePending.waiting_for_select)
    text = MESSAGES[lang]["select_pending"]
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for p in pending:
        text += f"🆔 <b>#{p['id']}</b> | 📁 {p['category']}\n💎 {p['buy_amount']} GRAM\n📅 {p['date']}\n\n"
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"✅ #{p['id']}", callback_data=f"complete_{p['id']}"),
            InlineKeyboardButton(text=f"🗑 #{p['id']}", callback_data=f"delete_pending_{p['id']}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.regexp(r"^complete_\d+$"))
async def process_complete(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    pending_id = int(callback.data.split("_")[1])
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM pending_sales WHERE id=? AND user_id=?", (pending_id, callback.from_user.id))
    row = await cur.fetchone()
    if not row:
        await callback.message.answer(MESSAGES[lang]["error_not_found"])
        return
    await state.update_data(pending_id=pending_id)
    await state.set_state(CompletePending.waiting_for_confirm)
    link = f"<a href='{row['nft_link']}'>NFT</a>" if row['nft_link'] else "—"
    await callback.message.answer(
        MESSAGES[lang]["confirm_complete"].format(id=row['id'], category=row['category'], buy=row['buy_amount'], link=link, royalty=row['royalty_gram'] or "—", date=row['date']),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=MESSAGES[lang]["complete_yes"], callback_data="confirm_complete")],
            [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
        ])
    )

@dp.callback_query(F.data == "confirm_complete")
async def confirm_complete(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(CompletePending.waiting_for_sell_amount)
    await callback.message.answer(MESSAGES[lang]["enter_sell_amount"], reply_markup=get_cancel_kb(lang))

@dp.message(CompletePending.waiting_for_sell_amount)
async def process_complete_sell_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
        gram_price_sell = await get_gram_price()
        await state.update_data(sell_amount=amount, gram_price_sell=gram_price_sell)
        royalty = await get_user_royalty(message.from_user.id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🔸 {royalty:.2f} GRAM", callback_data=f"complete_royalty_{royalty}")],
            [InlineKeyboardButton(text=MESSAGES[lang]["commission_custom"], callback_data="complete_royalty_custom")],
            [InlineKeyboardButton(text=MESSAGES[lang]["commission_zero"], callback_data="complete_royalty_0")],
            [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
        ])
        await message.answer(f"{EMOJI_DOLLAR} Курс продажи: <b>${gram_price_sell:.4f}</b>\n\n{MESSAGES[lang]['select_commission'].format(royalty=f'{royalty:.2f}')}", reply_markup=kb)
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.callback_query(F.data.startswith("complete_royalty_"))
async def process_complete_royalty_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    val = callback.data.replace("complete_royalty_", "")
    if val == "custom":
        await callback.message.answer("Введите комиссию в GRAM:", reply_markup=get_cancel_kb(lang))
        return
    royalty = float(val)
    await finalize_pending(callback.message, state, royalty, callback.from_user.id, lang)

@dp.message(CompletePending.waiting_for_royalty)
async def process_complete_custom_royalty(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        royalty = float(message.text.replace(",", "."))
        if royalty < 0: raise ValueError
        await finalize_pending(message, state, royalty, message.from_user.id, lang)
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

async def finalize_pending(message: Message, state: FSMContext, royalty: float, user_id: int, lang: str = "ru"):
    data = await state.get_data()
    pending_id = data["pending_id"]; sell_amount = data["sell_amount"]
    gram_price_sell = data.get("gram_price_sell") or await get_gram_price()
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM pending_sales WHERE id=? AND user_id=?", (pending_id, user_id))
    row = await cur.fetchone()
    if not row:
        await message.answer(MESSAGES[lang]["error_not_found"], reply_markup=get_main_kb(lang))
        await state.clear()
        return
    buy_amt = row["buy_amount"]
    gram_price_buy = row['gram_price_buy'] if 'gram_price_buy' in row.keys() and row['gram_price_buy'] else gram_price_sell
    profit_gram = sell_amount - buy_amt - royalty
    profit_usd = compute_profit_usd(buy_amt, sell_amount, royalty, gram_price_buy, gram_price_sell, fallback_gram_price=gram_price_sell)
    nft_data = {k: row[k] if k in row.keys() else None for k in ("gift_name", "model", "model_rarity", "model_emoji_id", "backdrop", "backdrop_rarity", "backdrop_emoji_id", "symbol", "symbol_rarity", "symbol_emoji_id", "collection_emoji_id")}
    if not nft_data["model"] and row["nft_link"]:
        fresh = await parse_nft_link(row["nft_link"])
        if fresh: nft_data = fresh
    thumb_id = row["thumb_file_id"] if "thumb_file_id" in row.keys() else None
    if not thumb_id:
        nft_img = nft_data.get("nft_image")
        if nft_img: thumb_id = await upload_thumb_to_telegram(nft_img)
    await conn.execute(
        """INSERT INTO sales (user_id, category, nft_link, nft_image, thumb_file_id, date, buy_amount, sell_amount, gram_price,
           gram_price_buy, gram_price_sell, profit_gram, profit_usd, royalty_gram, gift_name, model, model_rarity, model_emoji_id,
           backdrop, backdrop_rarity, backdrop_emoji_id, symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, row["category"], row["nft_link"], nft_data.get("nft_image") if "nft_image" in nft_data else None, thumb_id, row["date"], buy_amt, sell_amount, gram_price_sell,
         gram_price_buy, gram_price_sell, round(profit_gram, 4), profit_usd, royalty,
         nft_data.get("gift_name"), nft_data.get("model"), nft_data.get("model_rarity"), nft_data.get("model_emoji_id"),
         nft_data.get("backdrop"), nft_data.get("backdrop_rarity"), nft_data.get("backdrop_emoji_id"),
         nft_data.get("symbol"), nft_data.get("symbol_rarity"), nft_data.get("symbol_emoji_id"), nft_data.get("collection_emoji_id"))
    )
    await conn.execute("DELETE FROM pending_sales WHERE id=?", (pending_id,))
    if row["nft_link"]: await conn.execute("DELETE FROM timers WHERE user_id=? AND nft_link=? AND notified=0", (user_id, row["nft_link"]))
    await conn.commit()
    cur = await conn.execute("SELECT last_insert_rowid()")
    sale_id = (await cur.fetchone())[0]
    if row["nft_link"] and "t.me/nft/" in row["nft_link"]:
        slug = row["nft_link"].split("/nft/")[1].split("/")[0].split("?")[0]
        cur = await conn.execute("SELECT id FROM tracking WHERE user_id=? AND slug=?", (user_id, slug))
        if not await cur.fetchone():
            await conn.execute("INSERT INTO tracking (user_id, slug, sale_id, state) VALUES (?, ?, ?, 'bought')", (user_id, slug, sale_id))
    await conn.commit()
    await add_user_collection(user_id, row["category"])
    await state.clear()
    await activate_referral(user_id)
    await check_goal_achievement(user_id)
    link = f"<a href='{row['nft_link']}'>NFT</a>" if row['nft_link'] else "—"
    msgs = MESSAGES[lang]
    attrs = format_gift_attributes(nft_data) if nft_data else ""
    collection_emoji = premium_emoji(nft_data.get("collection_emoji_id") if nft_data else None, EMOJI_COLLECTION_FALLBACK)
    gift_name = (nft_data.get("gift_name") if nft_data else None) or row['category'] or 'NFT'
    text = msgs["deal_completed"].format(category=row['category'], buy=buy_amt, sell=sell_amount, profit=f"{profit_gram:+.4f}", link=link)
    header = f"{collection_emoji} <b>{gift_name}</b>\n{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n{EMOJI_DOLLAR} Курс продажи: <b>${gram_price_sell:.4f}</b>\n{EMOJI_DOLLAR} Прибыль в USD: <b>{profit_usd:+.2f}$</b>"
    if attrs: header = f"{header}\n{attrs}"
    await message.answer(f"{header}\n\n{text}", reply_markup=get_main_kb(lang))

@dp.callback_query(F.data.startswith("delete_pending_"))
async def delete_pending_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    pending_id = int(callback.data.split("_")[-1])
    await state.update_data(delete_pending_id=pending_id)
    await state.set_state(DeletePendingConfirm.waiting)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=MESSAGES[lang]["delete_yes"], callback_data="confirm_delete_pending")],
        [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])
    await callback.message.answer(MESSAGES[lang]["delete_pending_confirm"], reply_markup=kb)

@dp.callback_query(F.data == "confirm_delete_pending")
async def confirm_delete_pending(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    pending_id = data.get("delete_pending_id")
    lang = await get_user_lang(callback.from_user.id)
    if pending_id:
        conn = await get_db()
        await conn.execute("DELETE FROM pending_sales WHERE id=? AND user_id=?", (pending_id, callback.from_user.id))
        await conn.commit()
    await state.clear()
    try: await callback.message.edit_text(MESSAGES[lang]["deleted"])
    except: await callback.message.answer(MESSAGES[lang]["deleted"])
        except Exception as e:
            logger.warning(f"Фоновая гифка для {slug}: {e}")

# ---------- РЕДАКТИРОВАНИЕ СДЕЛКИ ----------
@dp.callback_query(F.data.regexp(r"^edit_\d+$"))
async def edit_deal_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    deal_id = int(callback.data.split("_")[1])
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM sales WHERE id=? AND user_id=?", (deal_id, callback.from_user.id))
    row = await cur.fetchone()
    if not row:
        await callback.answer(MESSAGES[lang]["error_not_found"])
        return
    await state.update_data(edit_deal_id=deal_id, old_data=dict(row))
    await state.set_state(EditProfit.waiting_for_buy_amount)
    await callback.message.answer(MESSAGES[lang]["edit_buy_amount"].format(old=row['buy_amount']), reply_markup=get_cancel_kb(lang))

@dp.message(EditProfit.waiting_for_buy_amount)
async def process_edit_buy_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
        gram_price_buy = await get_gram_price()
        await state.update_data(new_buy=amount, new_gram_price_buy=gram_price_buy)
        await state.set_state(EditProfit.waiting_for_category)
        await message.answer(f"{EMOJI_DOLLAR} Новый курс: <b>${gram_price_buy:.4f}</b>\n\n{MESSAGES[lang]['edit_category']}", reply_markup=get_cancel_kb(lang))
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.message(EditProfit.waiting_for_category)
async def process_edit_category(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    await state.update_data(new_category=message.text.strip())
    await state.set_state(EditProfit.waiting_for_nft_link)
    await message.answer(MESSAGES[lang]["edit_nft_link"], reply_markup=get_cancel_kb(lang))

@dp.message(EditProfit.waiting_for_nft_link)
async def process_edit_nft_link(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    new_link = message.text.strip()
    await state.update_data(new_link=new_link)
    if new_link and new_link != "-":
        fresh = await parse_nft_link(new_link)
        if fresh:
            await state.update_data(**fresh)
            thumb_id = await upload_thumb_to_telegram(fresh.get("nft_image"))
            if thumb_id: await state.update_data(thumb_file_id=thumb_id)
    await state.set_state(EditProfit.waiting_for_sell_amount)
    await message.answer(MESSAGES[lang]["edit_sell_amount"], reply_markup=get_cancel_kb(lang))

@dp.message(EditProfit.waiting_for_sell_amount)
async def process_edit_sell_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
        gram_price_sell = await get_gram_price()
        await state.update_data(new_sell=amount, new_gram_price_sell=gram_price_sell)
        royalty = await get_user_royalty(message.from_user.id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🔸 {royalty:.2f} GRAM", callback_data=f"edit_royalty_{royalty}")],
            [InlineKeyboardButton(text=MESSAGES[lang]["commission_custom"], callback_data="edit_royalty_custom")],
            [InlineKeyboardButton(text=MESSAGES[lang]["commission_zero"], callback_data="edit_royalty_0")],
            [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
        ])
        await message.answer(f"{EMOJI_DOLLAR} Новый курс продажи: <b>${gram_price_sell:.4f}</b>\n\n{MESSAGES[lang]['edit_commission']}", reply_markup=kb)
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.callback_query(F.data.startswith("edit_royalty_"))
async def process_edit_royalty_choice(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    val = callback.data.replace("edit_royalty_", "")
    if val == "custom":
        await callback.message.answer("Введите комиссию в GRAM:", reply_markup=get_cancel_kb(lang))
        return
    royalty = float(val)
    await finalize_edit(callback.message, state, royalty, callback.from_user.id, lang)

@dp.message(EditProfit.waiting_for_royalty)
async def process_edit_custom_royalty(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        royalty = float(message.text.replace(",", "."))
        if royalty < 0: raise ValueError
        await finalize_edit(message, state, royalty, message.from_user.id, lang)
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"])

async def finalize_edit(message: Message, state: FSMContext, royalty: float, user_id: int, lang: str = "ru"):
    data = await state.get_data()
    deal_id = data["edit_deal_id"]
    new_buy = data.get("new_buy"); new_sell = data.get("new_sell")
    new_category = data.get("new_category"); new_link = data.get("new_link")
    new_gp_buy = data.get("new_gram_price_buy") or await get_gram_price()
    new_gp_sell = data.get("new_gram_price_sell") or new_gp_buy
    profit_gram = new_sell - new_buy - royalty
    profit_usd = compute_profit_usd(new_buy, new_sell, royalty, new_gp_buy, new_gp_sell, fallback_gram_price=new_gp_sell)
    conn = await get_db()
    has_nft = any(k in data for k in ("model", "backdrop", "symbol", "gift_name"))
    if has_nft:
        await conn.execute(
            """UPDATE sales SET buy_amount=?, sell_amount=?, category=?, nft_link=?, profit_gram=?, profit_usd=?, royalty_gram=?, gram_price=?,
               gram_price_buy=?, gram_price_sell=?, gift_name=?, model=?, model_rarity=?, model_emoji_id=?, backdrop=?, backdrop_rarity=?, backdrop_emoji_id=?,
               symbol=?, symbol_rarity=?, symbol_emoji_id=?, collection_emoji_id=?, thumb_file_id=COALESCE(?, thumb_file_id), nft_image=COALESCE(?, nft_image)
               WHERE id=? AND user_id=?""",
            (new_buy, new_sell, new_category, new_link, round(profit_gram, 4), profit_usd, royalty, new_gp_sell,
             new_gp_buy, new_gp_sell, data.get("gift_name"), data.get("model"), data.get("model_rarity"), data.get("model_emoji_id"),
             data.get("backdrop"), data.get("backdrop_rarity"), data.get("backdrop_emoji_id"), data.get("symbol"), data.get("symbol_rarity"), data.get("symbol_emoji_id"),
             data.get("collection_emoji_id"), data.get("thumb_file_id"), data.get("nft_image"), deal_id, user_id)
        )
    else:
        await conn.execute(
            """UPDATE sales SET buy_amount=?, sell_amount=?, category=?, nft_link=?, profit_gram=?, profit_usd=?, royalty_gram=?, gram_price=?, gram_price_buy=?, gram_price_sell=?
               WHERE id=? AND user_id=?""",
            (new_buy, new_sell, new_category, new_link, round(profit_gram, 4), profit_usd, royalty, new_gp_sell, new_gp_buy, new_gp_sell, deal_id, user_id)
        )
    await conn.commit()
    await state.clear()
    await message.answer(f"{EMOJI_DOLLAR} Курс покупки: <b>${new_gp_buy:.4f}</b>\n{EMOJI_DOLLAR} Курс продажи: <b>${new_gp_sell:.4f}</b>\n{EMOJI_DOLLAR} Прибыль в USD: <b>{profit_usd:+.2f}$</b>\n\n{MESSAGES[lang]['updated']}", reply_markup=get_main_kb(lang))

# ---------- УДАЛЕНИЕ И ИСТОРИЯ ----------
@dp.callback_query(F.data.regexp(r"^delete_\d+$"))
async def delete_deal_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    deal_id = int(callback.data.split("_")[1])
    await state.update_data(delete_deal_id=deal_id)
    await state.set_state(DeleteConfirm.waiting)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["delete_yes"], callback_data="confirm_delete"), InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]])
    await callback.message.answer(MESSAGES[lang]["delete_confirm"], reply_markup=kb)

@dp.callback_query(F.data == "confirm_delete")
async def confirm_delete(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    deal_id = data.get("delete_deal_id")
    lang = await get_user_lang(callback.from_user.id)
    if deal_id:
        conn = await get_db()
        await conn.execute("DELETE FROM sales WHERE id=? AND user_id=?", (deal_id, callback.from_user.id))
        await conn.commit()
    await state.clear()
    try: await callback.message.edit_text(MESSAGES[lang]["deleted"])
    except: await callback.message.answer(MESSAGES[lang]["deleted"])

PAGE_SIZE = 5

@dp.message(F.text.in_(["📋 История", "📋 History"]))
@dp.message(Command("history"))
async def history(message: Message):
    await show_history_page(message, message.from_user.id, 0)

async def show_history_page(message: Message, user_id: int, page: int):
    lang = await get_user_lang(user_id)
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM sales WHERE user_id=?", (user_id,))
    total = (await cur.fetchone())[0]
    if total == 0:
        await message.answer(MESSAGES[lang]["history_empty"])
        return
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages-1))
    offset = page * PAGE_SIZE
    cur = await conn.execute("SELECT * FROM sales WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?", (user_id, PAGE_SIZE, offset))
    rows = await cur.fetchall()
    deals = [dict(row) for row in rows]
    text = MESSAGES[lang]["history_title"].format(page=page+1, total=total_pages)
    for d in deals:
        emoji = get_profit_emoji(d['profit_gram'])
        link = f"<a href='{d['nft_link']}'>NFT</a>" if d.get('nft_link') else "—"
        collection_emoji = premium_emoji(d.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
        gift_line = f"{collection_emoji} {d['gift_name']}\n" if d.get('gift_name') else ""
        attrs = format_gift_attributes({k: d.get(k) for k in ("model", "model_rarity", "model_emoji_id", "backdrop", "backdrop_rarity", "backdrop_emoji_id", "symbol", "symbol_rarity", "symbol_emoji_id")})
        attrs_line = f"{attrs}\n" if attrs else ""
        gp_buy = d.get("gram_price_buy") or 0
        gp_sell = d.get("gram_price_sell") or d.get("gram_price") or 0
        courses_line = f"{EMOJI_DOLLAR} ${gp_buy:.4f} → ${gp_sell:.4f}\n" if (gp_buy and gp_sell and gp_buy != gp_sell) else (f"{EMOJI_DOLLAR} ${gp_sell or gp_buy:.4f}\n" if (gp_buy or gp_sell) else "")
        profit_usd = d.get("profit_usd") or 0
        text += f"{emoji} <b>#{d['id']}</b> | {d['category']}\n{gift_line}{attrs_line}{EMOJI_DIAMOND} {d['buy_amount']} → {d['sell_amount']} GRAM\n{courses_line}{EMOJI_DOLLAR} {profit_usd:+.2f}$ | 💰 {d['profit_gram']:+.4f} GRAM | {link} | {d['date']}\n\n"
    
    kb_rows = []
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text=MESSAGES[lang]["history_prev"], callback_data=f"hist_prev_{page}"))
    if page < total_pages - 1: nav.append(InlineKeyboardButton(text=MESSAGES[lang]["history_next"], callback_data=f"hist_next_{page}"))
    if nav: kb_rows.append(nav)
    actions = []
    for d in deals:
        actions.append(InlineKeyboardButton(text=MESSAGES[lang]["edit_btn"].format(id=d['id']), callback_data=f"edit_{d['id']}"))
        actions.append(InlineKeyboardButton(text=MESSAGES[lang]["delete_btn"].format(id=d['id']), callback_data=f"delete_{d['id']}"))
    for i in range(0, len(actions), 4): kb_rows.append(actions[i:i+4])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

@dp.callback_query(F.data.startswith("hist_"))
async def history_pagination(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split("_")
    new_page = int(parts[2]) - 1 if parts[1] == "prev" else int(parts[2]) + 1
    await show_history_page(callback.message, callback.from_user.id, new_page)

# ---------- СТАТИСТИКА ----------
def quickchart_url(config):
    return f"https://quickchart.io/chart?c={quote(json.dumps(config))}&width=500&height=300"

@dp.message(F.text.in_(["📊 Статистика", "📊 Statistics"]))
@dp.message(Command("stats"))
async def stats_main(message: Message):
    await show_stats_dashboard(message, message.from_user.id)

async def show_stats_dashboard(message: Message, user_id: int):
    lang = await get_user_lang(user_id)
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*), SUM(profit_gram), SUM(profit_usd), MAX(profit_gram), MIN(profit_gram), AVG(profit_gram) FROM sales WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    if not row or row[0] is None or not row[0]:
        return await message.answer(MESSAGES[lang]["stats_no_deals"])
    deals, total_g, total_u, max_g, min_g, avg_g = row
    cur = await conn.execute("SELECT SUM(buy_amount), SUM(sell_amount) FROM sales WHERE user_id=?", (user_id,))
    buy_total, sell_total = await cur.fetchone()
    cur = await conn.execute("SELECT goal_gram FROM profit_goals WHERE user_id=?", (user_id,))
    goal_row = await cur.fetchone()
    goal = goal_row[0] if goal_row else None
    star_rate = await get_user_star_rate(user_id)
    royalty = await get_user_royalty(user_id)
    msgs = MESSAGES[lang]
    text = msgs["stats_title"] + msgs["stats_total"].format(total=f"{total_g:+.4f}", usd=f"{total_u:+.2f}") + "\n" + msgs["stats_deals"].format(deals=deals) + "\n" + msgs["stats_avg"].format(avg=f"{avg_g:+.4f}") + "\n" + msgs["stats_max"].format(max=f"{max_g:+.4f}") + "\n" + msgs["stats_min"].format(min=f"{min_g:+.4f}") + "\n" + msgs["stats_volume"].format(buy=f"{buy_total or 0:.2f}", sell=f"{sell_total or 0:.2f}") + "\n" + msgs["stats_star_rate"].format(rate=f"{star_rate:.6f}") + "\n" + msgs["stats_royalty"].format(royalty=f"{royalty:.2f}") + "\n"
    if goal: text += "\n" + msgs["stats_goal"].format(goal=f"{goal:.2f}", bar=make_progress_bar(total_g, goal)) + "\n"
    text += "\n" + msgs["stats_gram_price"].format(price=f"{await get_gram_price():.4f}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msgs["stats_collections_btn"], callback_data="stats_collections"), InlineKeyboardButton(text=msgs["stats_months_btn"], callback_data="stats_months")],
        [InlineKeyboardButton(text=msgs["stats_top_btn"], callback_data="stats_top"), InlineKeyboardButton(text=msgs["stats_cumulative_btn"], callback_data="stats_cumulative")],
        [InlineKeyboardButton(text=msgs["stats_chart_btn"], callback_data="stats_chart")],
        [InlineKeyboardButton(text=msgs["stats_close_btn"], callback_data="close_stats")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "stats_collections")
async def stats_collections(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    conn = await get_db()
    cur = await conn.execute("SELECT category, COUNT(*), SUM(profit_gram), SUM(profit_usd) FROM sales WHERE user_id=? GROUP BY category ORDER BY SUM(profit_gram) DESC", (callback.from_user.id,))
    rows = await cur.fetchall()
    text = MESSAGES[lang]["collections_title"]
    if not rows: text += "—"
    else:
        for i, (cat, cnt, profit_g, profit_u) in enumerate(rows, 1):
            text += f"{i}. {get_profit_emoji(profit_g)} {cat}: {profit_g:+.4f} GRAM (${profit_u or 0:+.2f}) — {cnt} сделок\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["stats_back_btn"], callback_data="stats_back")]])
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data == "stats_months")
async def stats_months(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    conn = await get_db()
    cur = await conn.execute("SELECT substr(date, 4, 7) as month, COUNT(*), SUM(profit_gram) FROM sales WHERE user_id=? GROUP BY month ORDER BY date DESC LIMIT 6", (callback.from_user.id,))
    rows = await cur.fetchall()
    if not rows:
        text = "Нет данных по месяцам."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["stats_back_btn"], callback_data="stats_back")]])
        await callback.message.edit_text(text, reply_markup=kb)
        return
    months = [r[0] for r in reversed(rows)]
    profits = [float(r[2]) for r in reversed(rows)]
    config = {"type": "bar", "data": {"labels": months, "datasets": [{"label": "GRAM", "data": profits, "backgroundColor": ["#2ecc71" if p>0 else "#e74c3c" for p in profits]}]}, "options": {"title": {"display": True, "text": "Прибыль по месяцам", "fontSize": 14}}}
    chart_url = quickchart_url(config)
    await callback.message.answer_photo(chart_url, caption=MESSAGES[lang]["months_title"])
    text = "\n".join([f"{r[0]}: {float(r[2]):+.4f} GRAM ({r[1]} сделок)" for r in rows])
    await callback.message.answer(text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["stats_back_btn"], callback_data="stats_back")]])
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(F.data == "stats_top")
async def stats_top(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    conn = await get_db()
    cur = await conn.execute("SELECT id, category, buy_amount, sell_amount, profit_gram, profit_usd, date, nft_link FROM sales WHERE user_id=? ORDER BY profit_gram DESC LIMIT 10", (callback.from_user.id,))
    rows = await cur.fetchall()
    text = MESSAGES[lang]["top_title"]
    if not rows: text += "—"
    else:
        for did, cat, buy, sell, pg, pu, dt, link in rows:
            text += f"{get_profit_emoji(pg)} <b>#{did}</b> {cat} — {buy}→{sell} GRAM\n💰 {pg:+.4f} GRAM ({pu or 0:+.2f}$) | 📅 {dt}\n"
            if link: text += f"{EMOJI_LINK} <a href='{link}'>NFT</a>\n"
            text += "\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["stats_back_btn"], callback_data="stats_back")]])
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data == "stats_cumulative")
async def stats_cumulative(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    conn = await get_db()
    cur = await conn.execute("SELECT date, profit_gram FROM sales WHERE user_id=? ORDER BY id ASC", (callback.from_user.id,))
    rows = await cur.fetchall()
    if not rows:
        await callback.answer("Нет сделок")
        return
    dates, cum = [], []
    total = 0.0
    for r in rows:
        dates.append(r[0]); total += float(r[1]); cum.append(round(total, 4))
    config = {"type": "line", "data": {"labels": dates, "datasets": [{"label": "GRAM", "data": cum, "borderColor": "#2ecc71", "fill": False}]}, "options": {"title": {"display": True, "text": "Рост общей прибыли", "fontSize": 14}}}
    chart_url = quickchart_url(config)
    await callback.message.answer_photo(chart_url, caption=MESSAGES[lang]["cumulative_title"])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["stats_back_btn"], callback_data="stats_back")]])
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(F.data == "stats_chart")
async def stats_chart(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    conn = await get_db()
    cur = await conn.execute("SELECT profit_gram FROM sales WHERE user_id=? ORDER BY id DESC LIMIT 20", (callback.from_user.id,))
    rows = await cur.fetchall()
    if not rows:
        await callback.answer("Нет сделок")
        return
    profits = [float(r[0]) for r in rows]
    labels = [f"#{i+1}" for i in range(len(profits))]
    config = {"type": "bar", "data": {"labels": labels, "datasets": [{"label": "GRAM", "data": profits, "backgroundColor": ["#2ecc71" if p>0 else "#e74c3c" for p in profits]}]}, "options": {"title": {"display": True, "text": "Последние 20 сделок", "fontSize": 14}}}
    chart_url = quickchart_url(config)
    await callback.message.answer_photo(chart_url, caption=MESSAGES[lang]["chart_title"])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["stats_back_btn"], callback_data="stats_back")]])
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(F.data == "stats_back")
async def stats_back(callback: CallbackQuery):
    await callback.answer()
    try: await callback.message.delete()
    except: pass
    await show_stats_dashboard(callback.message, callback.from_user.id)

@dp.callback_query(F.data == "close_stats")
async def close_stats(callback: CallbackQuery):
    await callback.answer()
    try: await callback.message.delete()
    except: pass

    # ---------- КАЛЬКУЛЯТОР ----------
@dp.message(F.text.in_(["🔄 Калькулятор", "🔄 Calculator"]))
@dp.message(Command("calc"))
async def calc_start(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    await state.set_state(CalcStates.waiting_for_amount)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=MESSAGES[lang]["calc_stars_to_gram"], callback_data="calc_stars_to_gram")],
        [InlineKeyboardButton(text=MESSAGES[lang]["calc_gram_to_stars"], callback_data="calc_gram_to_stars")],
        [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])
    await message.answer(MESSAGES[lang]["calc_title"], reply_markup=kb)

@dp.callback_query(F.data.in_(["calc_stars_to_gram", "calc_gram_to_stars"]))
async def calc_direction(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await state.update_data(calc_dir=callback.data.replace("calc_", ""))
    await state.set_state(CalcStates.waiting_for_amount)
    await callback.message.answer("Введите сумму:", reply_markup=get_cancel_kb(lang))

@dp.message(CalcStates.waiting_for_amount)
async def calc_result(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
        data = await state.get_data()
        direction = data.get("calc_dir")
        star_rate = await get_user_star_rate(message.from_user.id)
        gram_price = await get_gram_price()
        if direction == "stars_to_gram":
            gram = (amount * 0.8 * star_rate) / gram_price
            text = MESSAGES[lang]["calc_result_stars"].format(amount=amount, gram=f"{gram:.4f}", usd=f"{gram*gram_price:.2f}")
        else:
            stars = (amount * gram_price) / (star_rate * 0.8)
            text = MESSAGES[lang]["calc_result_gram"].format(amount=amount, stars=f"{stars:.0f}")
        await message.answer(text, reply_markup=get_main_kb(lang))
        await state.clear()
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

# ---------- НАСТРОЙКИ ----------
@dp.message(F.text.in_(["⚙️ Настройки", "⚙️ Settings"]))
async def settings(message: Message):
    lang = await get_user_lang(message.from_user.id)
    user_id = message.from_user.id
    royalty = await get_user_royalty(user_id)
    star_rate = await get_user_star_rate(user_id)
    change_enabled, change_percent, _ = await get_user_change_alert(user_id)
    conn = await get_db()
    cur = await conn.execute("SELECT goal_gram FROM profit_goals WHERE user_id=?", (user_id,))
    goal_row = await cur.fetchone()
    goal = goal_row[0] if goal_row else None
    msgs = MESSAGES[lang]
    text = msgs["settings_title"] + msgs["settings_commission"].format(royalty=f"{royalty:.2f}") + "\n" + msgs["settings_goal"].format(goal=f"{goal:.2f}" if goal else "—") + "\n" + msgs["settings_star_rate"].format(rate=f"{star_rate:.6f}") + "\n" + msgs["settings_change_alert"].format(status="вкл" if change_enabled else "выкл", percent=change_percent)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msgs["settings_change_commission"], callback_data="set_royalty")],
        [InlineKeyboardButton(text=msgs["settings_set_goal"], callback_data="set_goal")],
        [InlineKeyboardButton(text=msgs["settings_star_rate_btn"], callback_data="set_star_rate")],
        [InlineKeyboardButton(text=msgs["settings_change_alert_btn"], callback_data="toggle_change_alert")],
        [InlineKeyboardButton(text=msgs["settings_alert_btn"], callback_data="alert_start")],
        [InlineKeyboardButton(text=msgs["settings_reports_btn"], callback_data="open_reports")],
        [InlineKeyboardButton(text=msgs["settings_close"], callback_data="close_settings")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "close_settings")
async def close_settings(callback: CallbackQuery):
    await callback.answer()
    try: await callback.message.delete()
    except: pass

@dp.callback_query(F.data == "open_reports")
async def open_reports(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await reports_menu(callback.message, state)

@dp.callback_query(F.data == "set_royalty")
async def set_royalty_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(SetRoyalty.waiting_for_royalty)
    await callback.message.answer(MESSAGES[lang]["enter_royalty"], reply_markup=get_cancel_kb(lang))

@dp.message(SetRoyalty.waiting_for_royalty)
async def process_set_royalty(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        val = float(message.text.replace(",", "."))
        if val < 0: raise ValueError
        conn = await get_db()
        await conn.execute("INSERT OR REPLACE INTO user_royalty VALUES (?,?,datetime('now'))", (message.from_user.id, val))
        await conn.commit()
        await state.clear()
        await message.answer(f"✅ Комиссия изменена на {val:.2f} GRAM", reply_markup=get_main_kb(lang))
    except:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.callback_query(F.data == "set_goal")
async def set_goal_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(SetGoal.waiting_for_goal)
    await callback.message.answer(MESSAGES[lang]["enter_goal"], reply_markup=get_cancel_kb(lang))

@dp.message(SetGoal.waiting_for_goal)
async def process_set_goal(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        val = float(message.text.replace(",", "."))
        if val <= 0: raise ValueError
        conn = await get_db()
        await conn.execute("INSERT OR REPLACE INTO profit_goals VALUES (?,?,datetime('now'),0)", (message.from_user.id, val))
        await conn.commit()
        await state.clear()
        await message.answer(f"🎯 Цель установлена: {val} GRAM", reply_markup=get_main_kb(lang))
        await check_goal_achievement(message.from_user.id)
    except:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.callback_query(F.data == "set_star_rate")
async def set_star_rate_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(SetStarRate.waiting_for_rate)
    await callback.message.answer(MESSAGES[lang]["enter_star_rate"], reply_markup=get_cancel_kb(lang))

@dp.message(SetStarRate.waiting_for_rate)
async def process_set_star_rate(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        rate = float(message.text.replace(",", "."))
        if rate <= 0 or rate >= 1: raise ValueError
        await save_user_star_rate(message.from_user.id, rate)
        await state.clear()
        await message.answer(f"⭐ Курс Stars установлен: ${rate:.6f}", reply_markup=get_main_kb(lang))
    except:
        await message.answer("❌ Введите число от 0 до 1", reply_markup=get_cancel_kb(lang))

@dp.callback_query(F.data == "toggle_change_alert")
async def toggle_change_alert(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    enabled, percent, _ = await get_user_change_alert(callback.from_user.id)
    if enabled:
        await set_user_change_alert(callback.from_user.id, False, percent)
        await callback.message.answer(MESSAGES[lang]["change_alert_off"])
    else:
        await state.set_state(SetChangeAlert.waiting_for_percent)
        await callback.message.answer(MESSAGES[lang]["enter_change_percent"], reply_markup=get_cancel_kb(lang))

@dp.message(SetChangeAlert.waiting_for_percent)
async def process_change_percent(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        percent = float(message.text.replace(",", "."))
        if percent <= 0 or percent > 100: raise ValueError
        await set_user_change_alert(message.from_user.id, True, percent)
        await state.clear()
        await message.answer(MESSAGES[lang]["change_alert_on"].format(percent=percent), reply_markup=get_main_kb(lang))
    except:
        await message.answer("❌ Введите число от 0 до 100", reply_markup=get_cancel_kb(lang))

@dp.callback_query(F.data == "alert_start")
async def alert_start_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(AlertStates.waiting_for_price)
    await callback.message.answer(MESSAGES[lang]["enter_alert_price"], reply_markup=get_cancel_kb(lang))

@dp.message(Command("alert"))
async def alert_start(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    await state.set_state(AlertStates.waiting_for_price)
    await message.answer(MESSAGES[lang]["enter_alert_price"], reply_markup=get_cancel_kb(lang))

@dp.message(AlertStates.waiting_for_price)
async def set_alert(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        target = float(message.text.replace(",", "."))
        if target <= 0: raise ValueError
        conn = await get_db()
        await conn.execute("INSERT OR REPLACE INTO gram_alerts (user_id, target_price, enabled, notified) VALUES (?,?,1,0)", (message.from_user.id, target))
        await conn.commit()
        await state.clear()
        await message.answer(MESSAGES[lang]["alert_set"].format(price=f"{target:.2f}"), reply_markup=get_main_kb(lang))
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

# ---------- ОТЧЁТЫ, ДОНАТЫ, ТАЙМЕРЫ, РЕФЕРАЛЫ ----------
@dp.message(Command("reports"))
async def reports_menu(message: Message, state: FSMContext = None):
    if state: await state.clear()
    lang = await get_user_lang(message.from_user.id)
    conn = await get_db()
    cur = await conn.execute("SELECT weekly, monthly, yearly FROM user_earnings_reports WHERE user_id=?", (message.from_user.id,))
    row = await cur.fetchone() or (1, 1, 1)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{MESSAGES[lang]['reports_weekly']}: {'✅' if row[0] else '❌'}", callback_data="toggle_weekly")],
        [InlineKeyboardButton(text=f"{MESSAGES[lang]['reports_monthly']}: {'✅' if row[1] else '❌'}", callback_data="toggle_monthly")],
        [InlineKeyboardButton(text=f"{MESSAGES[lang]['reports_yearly']}: {'✅' if row[2] else '❌'}", callback_data="toggle_yearly")],
        [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])
    await message.answer(MESSAGES[lang]["reports_title"], reply_markup=kb)

@dp.callback_query(F.data.in_(["toggle_weekly", "toggle_monthly", "toggle_yearly"]))
async def toggle_report(callback: CallbackQuery):
    await callback.answer()
    report_type = callback.data.replace("toggle_", "")
    conn = await get_db()
    cur = await conn.execute(f"SELECT {report_type} FROM user_earnings_reports WHERE user_id=?", (callback.from_user.id,))
    row = await cur.fetchone()
    new_val = 0 if row and row[0] else 1
    await conn.execute(f"UPDATE user_earnings_reports SET {report_type}=? WHERE user_id=?", (new_val, callback.from_user.id))
    await conn.commit()
    await reports_menu(callback.message, None)

@dp.message(F.text.in_(["💎 Поддержать", "💎 Donate"]))
async def donate_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=MESSAGES[lang]["donate_stars"], callback_data="donate_stars")],
        [InlineKeyboardButton(text=MESSAGES[lang]["donate_top"], callback_data="donate_top")],
        [InlineKeyboardButton(text=MESSAGES[lang]["donate_wallet"], callback_data="donate_wallet")],
        [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])
    await message.answer(MESSAGES[lang]["donate_menu"], reply_markup=kb)

@dp.callback_query(F.data == "donate_wallet")
async def donate_wallet(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await callback.message.answer(MESSAGES[lang]["donate_text"])

@dp.callback_query(F.data == "donate_stars")
async def donate_stars_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(DonateStars.waiting_for_amount)
    await callback.message.answer(MESSAGES[lang]["donate_enter_amount"], reply_markup=get_cancel_kb(lang))

@dp.message(DonateStars.waiting_for_amount)
async def donate_stars_process(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        amount = int(message.text.strip())
        if amount <= 0: raise ValueError
        await state.clear()
        await bot.send_invoice(chat_id=message.chat.id, title="Поддержка бота", description=f"Донат {amount} звёзд", payload=f"donate_{message.from_user.id}_{amount}", currency="XTR", prices=[LabeledPrice(label="Донат", amount=amount)], provider_token="")
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    amount = message.successful_payment.total_amount
    user_id = message.from_user.id
    conn = await get_db()
    await conn.execute("INSERT INTO donations (user_id, amount, date, telegram_payment_charge_id) VALUES (?,?,?,?)", (user_id, amount, datetime.now().strftime("%d.%m.%Y"), message.successful_payment.telegram_payment_charge_id))
    await conn.commit()
    lang = await get_user_lang(user_id)
    await message.answer(MESSAGES[lang]["donate_thanks"].format(amount=amount))
    if user_id != ADMIN_IDS[0]:
        try: await bot.send_message(ADMIN_IDS[0], MESSAGES["ru"]["donate_admin_notify"].format(user=f"ID {user_id}", amount=amount, date=datetime.now().strftime('%d.%m.%Y %H:%M')))
        except: pass

@dp.callback_query(F.data == "donate_top")
async def donate_top(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    conn = await get_db()
    cur = await conn.execute("SELECT d.user_id, SUM(d.amount) as total, u.username, u.first_name FROM donations d LEFT JOIN users u ON u.user_id = d.user_id GROUP BY d.user_id ORDER BY total DESC LIMIT 10")
    rows = await cur.fetchall()
    if not rows: return await callback.message.answer(MESSAGES[lang]["donate_top_empty"])
    text = MESSAGES[lang]["donate_top_title"] + "\n\n"
    for i, (uid, total, username, first_name) in enumerate(rows, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        name = f"@{username}" if username else (first_name or f"ID {uid}")
        text += f"{emoji} {name} — {total} ⭐\n"
    await callback.message.answer(text)

@dp.message(F.text.in_(["⏰ Таймеры", "⏰ Timers"]))
async def timers_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM timers WHERE user_id=? AND notified=0 ORDER BY event_time", (message.from_user.id,))
    timers = await cur.fetchall()
    text = MESSAGES[lang]["timers_title"] + "\n\n"
    if not timers: text += MESSAGES[lang]["timers_empty"]
    else:
        for t in timers:
            days_left = max(0, int((t['event_time'] - time.time()) / 86400))
            link = t['nft_link'] or ""
            if t['event_type'] == 'mint': text += MESSAGES[lang]["timer_mint_item"].format(link=link, days=days_left) + "\n"
            elif t['event_type'] == 'relist': text += MESSAGES[lang]["timer_relist_item"].format(link=link, days=days_left) + "\n"
            else: text += MESSAGES[lang]["timer_unlock_item"].format(days=days_left) + "\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=MESSAGES[lang]["timer_add_mint"], callback_data="timer_mint")],
        [InlineKeyboardButton(text=MESSAGES[lang]["timer_add_unlock"], callback_data="timer_unlock")],
        [InlineKeyboardButton(text=MESSAGES[lang]["timer_add_relist"], callback_data="timer_relist")],
        [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.in_(["timer_mint", "timer_unlock", "timer_relist"]))
async def timer_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    event_type = callback.data.replace("timer_", "")
    await state.update_data(event_type=event_type)
    if event_type == "unlock":
        await state.set_state(TimerAdd.waiting_for_days)
        await callback.message.answer(MESSAGES[lang]["timer_enter_days"], reply_markup=get_cancel_kb(lang))
    else:
        await state.set_state(TimerAdd.waiting_for_nft_link)
        await callback.message.answer(MESSAGES[lang]["timer_enter_nft"], reply_markup=get_cancel_kb(lang))

@dp.message(TimerAdd.waiting_for_nft_link)
async def timer_nft_link_process(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    link = message.text.strip()
    if not link or "t.me/nft" not in link:
        return await message.answer(MESSAGES[lang]["timer_invalid_link"], reply_markup=get_cancel_kb(lang))
    await state.update_data(nft_link=link)
    await state.set_state(TimerAdd.waiting_for_days)
    await message.answer(MESSAGES[lang]["timer_enter_days"], reply_markup=get_cancel_kb(lang))

@dp.message(TimerAdd.waiting_for_days)
async def timer_days_process(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        days = int(message.text.strip())
        if days <= 0: raise ValueError
        data = await state.get_data()
        conn = await get_db()
        await conn.execute("INSERT INTO timers (user_id, event_type, nft_link, stars_amount, event_time, description) VALUES (?,?,?,?,?,?)", (message.from_user.id, data.get("event_type"), data.get("nft_link"), 0, time.time() + days * 86400, ""))
        await conn.commit()
        await state.clear()
        await message.answer(MESSAGES[lang]["timer_saved"].format(days=days), reply_markup=get_main_kb(lang))
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.message(F.text.in_(["👥 Рефералы", "👥 Referrals"]))
async def referrals_menu(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
    invited = (await cur.fetchone())[0] or 0
    cur = await conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND is_active=1", (user_id,))
    active = (await cur.fetchone())[0] or 0
    points = active * 10
    level = get_referral_level(points, lang)
    next_pts = get_next_level_points(points)
    ref_link = f"https://t.me/Stars2ProfitBot?start=ref_{user_id}"
    text = MESSAGES[lang]["referrals_title"] + MESSAGES[lang]["referrals_link"].format(link=ref_link) + MESSAGES[lang]["referrals_stats"].format(invited=invited, active=active, points=points) + MESSAGES[lang]["referrals_level"].format(level=level, next_level=MESSAGES[lang]["referrals_next_level"].format(points=next_pts) if next_pts > 0 else "—")
    cur = await conn.execute("SELECT referrer_id, COUNT(*) as cnt FROM referrals WHERE is_active=1 AND referrer_id IS NOT NULL GROUP BY referrer_id ORDER BY cnt DESC LIMIT 10")
    top_rows = await cur.fetchall()
    if top_rows:
        text += MESSAGES[lang]["referrals_top_title"] + "\n"
        for i, (rid, cnt) in enumerate(top_rows, 1):
            cur2 = await conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (rid,))
            urow = await cur2.fetchone()
            name = (f"@{urow[0]}" if urow and urow[0] else (urow[1] if urow else f"ID {rid}"))
            text += f"{i}. {name} — {cnt * 10} очков\n"
    else: text += "\n" + MESSAGES[lang]["referrals_empty"]
    text += "\n\n" + MESSAGES[lang]["referrals_points_per"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=MESSAGES[lang]["referrals_share"], url=f"https://t.me/share/url?url={quote(ref_link)}")],
        [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "cancel_deal")
async def cancel_deal(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    lang = await get_user_lang(callback.from_user.id)
    try: await callback.message.edit_text(MESSAGES[lang]["cancelled"])
    except: await callback.message.answer(MESSAGES[lang]["cancelled"])

@dp.callback_query(F.data == "goal_later")
async def goal_later(callback: CallbackQuery):
    await callback.answer()
    try: await callback.message.delete()
    except: pass

    # ---------- ИНЛАЙН-РЕЖИМ ----------
def inline_bot_keyboard(user_id: int = None):
    url = f"{BOT_URL}?start=ref_{user_id}" if user_id else BOT_URL
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Открыть бота", url=url)]])

def build_inline_plain(deal: dict, lang: str = "ru") -> str:
    return f"🎁 <b>{_esc(deal.get('gift_name') or deal.get('category') or 'NFT')}</b> · Сделка #{deal['id']}\n\n💎 {deal['buy_amount']} → {deal['sell_amount']} GRAM\n💰 <b>{deal.get('profit_gram', 0):+.4f} GRAM</b>\n🪙 <b>{deal.get('profit_usd', 0):+.2f}$</b>"

def build_inline_html(deal: dict) -> str:
    lines = [f"{get_collection_emoji_html(deal)} <b>{_esc(deal.get('gift_name') or deal.get('category') or 'NFT')}</b> · Сделка #{deal['id']}"]
    attrs = format_gift_attributes({k: deal.get(k) for k in ("model", "model_rarity", "model_emoji_id", "backdrop", "backdrop_rarity", "backdrop_emoji_id", "symbol", "symbol_rarity", "symbol_emoji_id")})
    if attrs: lines.extend(["", attrs])
    lines.extend(["", f"{EMOJI_DIAMOND} {deal['buy_amount']} → {deal['sell_amount']} GRAM"])
    gp_buy, gp_sell = deal.get('gram_price_buy') or 0, deal.get('gram_price_sell') or deal.get('gram_price') or 0
    if gp_buy and gp_sell and gp_buy != gp_sell: lines.append(f"{EMOJI_DOLLAR} Курс: ${gp_buy:.4f} → ${gp_sell:.4f}")
    elif gp_buy or gp_sell: lines.append(f"{EMOJI_DOLLAR} Курс: ${gp_sell or gp_buy:.4f}")
    lines.extend([f"{EMOJI_MONEY} <b>{deal.get('profit_gram', 0):+.4f} GRAM</b>", f"{EMOJI_DOLLAR} <b>{deal.get('profit_usd', 0):+.2f}$</b>"])
    if deal.get('nft_link'): lines.extend(["", f'{EMOJI_LINK} <a href="{_esc(deal["nft_link"])}">Открыть NFT</a>'])
    return "\n".join(lines)

@dp.inline_query()
async def inline_query(inline_query):
    uid = inline_query.from_user.id
    query = (inline_query.query or "").strip()
    conn = await get_db()
    if query.isdigit(): cur = await conn.execute("SELECT * FROM sales WHERE id=? AND user_id=? ORDER BY id DESC", (int(query), uid))
    else: cur = await conn.execute("SELECT * FROM sales WHERE user_id=? AND (category LIKE ? OR gift_name LIKE ?) ORDER BY id DESC LIMIT 10", (uid, f"%{query}%", f"%{query}%"))
    deals = [dict(row) for row in await cur.fetchall()]
    results = []
    for d in deals:
        gift_name = d.get('gift_name') or d.get('category') or 'NFT'
        profit, profit_usd = d.get('profit_gram') or 0, d.get('profit_usd') or 0
        desc = f"💎 {d['buy_amount']} → {d['sell_amount']} GRAM | 💰 {profit:+.4f} GRAM ({profit_usd:+.2f}$)"
        thumb_id = d.get("thumb_file_id")
        if thumb_id:
            results.append(InlineQueryResultCachedPhoto(id=f"sale_{d['id']}", photo_file_id=thumb_id, title=f"#{d['id']} {gift_name}", description=desc, caption=build_inline_html(d), parse_mode="HTML", reply_markup=inline_bot_keyboard(user_id=uid)))
        else:
            results.append(InlineQueryResultArticle(id=f"sale_{d['id']}", title=f"#{d['id']} {gift_name}", description=desc, thumbnail_url=d.get("nft_image"), input_message_content=InputTextMessageContent(message_text=build_inline_plain(d), parse_mode="HTML"), reply_markup=inline_bot_keyboard(user_id=uid)))
    if not results:
        results.append(InlineQueryResultArticle(id="no_deals", title="Ничего не найдено", description="У вас пока нет сделок", input_message_content=InputTextMessageContent(message_text="🔍 Нет сделок"), reply_markup=inline_bot_keyboard(user_id=uid)))
    try: await bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=True, switch_pm_text="Введи номер сделки (#123) или коллекцию", switch_pm_parameter="inline_help")
    except: pass

@dp.chosen_inline_result()
async def chosen_inline_result_handler(chosen: ChosenInlineResult):
    if not chosen.inline_message_id or not chosen.result_id.startswith("sale_"): return
    try: deal_id = int(chosen.result_id.replace("sale_", ""))
    except ValueError: return
    uid = chosen.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM sales WHERE id=? AND user_id=?", (deal_id, uid))
    row = await cur.fetchone()
    if not row: return
    deal_dict = dict(row)
    try:
        await conn.execute("INSERT INTO inline_stats (user_id, username, first_name, deal_id) VALUES (?,?,?,?)", (uid, chosen.from_user.username or "", chosen.from_user.first_name or "", deal_id))
        await conn.execute("DELETE FROM inline_stats WHERE id NOT IN (SELECT id FROM inline_stats ORDER BY id DESC LIMIT 500)")
        await conn.commit()
    except: pass
    gif_id = deal_dict.get("gif_file_id")
    nft_link = deal_dict.get("nft_link")
    slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0] if nft_link and "t.me/nft/" in nft_link else None
    if not gif_id and slug:
        cur2 = await conn.execute("SELECT file_id FROM gif_cache WHERE slug=?", (slug,))
        cache_row = await cur2.fetchone()
        if cache_row and cache_row[0]:
            gif_id = cache_row[0]
            await conn.execute("UPDATE sales SET gif_file_id=? WHERE id=?", (gif_id, deal_id))
            await conn.commit()
    if gif_id:
        try:
            await chosen.bot.edit_message_media(inline_message_id=chosen.inline_message_id, media=InputMediaAnimation(media=gif_id, caption=build_inline_html(deal_dict), parse_mode="HTML"), reply_markup=inline_bot_keyboard(user_id=uid))
        except: pass

# ---------- АДМИН-ПАНЕЛЬ ----------
@dp.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext = None):
    if state: await state.clear()
    if not await is_admin(message.from_user.id): return await message.answer("⛔ Доступ запрещён")
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM users"); total_users = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*), SUM(profit_gram), SUM(profit_usd) FROM sales"); total_deals, total_g, total_u = await cur.fetchone()
    text = f"⚙️ <b>Админ-панель</b>\n\n👥 Пользователей: {total_users}\n📊 Всего сделок: {total_deals or 0}\n💰 Прибыль: {total_g or 0:+.4f} GRAM\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_ext_stats"), InlineKeyboardButton(text="📋 Логи", callback_data="admin_logs")],
        [InlineKeyboardButton(text="🚨 Ошибки", callback_data="admin_errors"), InlineKeyboardButton(text="🎨 Настройки гифки", callback_data="admin_gif_settings")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="⬅️ Закрыть", callback_data="close_admin")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "close_admin")
async def close_admin(callback: CallbackQuery):
    await callback.answer()
    try: await callback.message.delete()
    except: pass

@dp.callback_query(F.data == "admin_gif_settings")
async def admin_gif_settings(callback: CallbackQuery):
    await callback.answer()
    s = await get_gif_settings()
    text = f"🎨 <b>Настройки гифки</b>\n\n📐 Ширина: {s['width']} px\n📐 Высота: {s['height']} px\n🎞 FPS: {s['fps']}\n⏭ Пропуск: {s['frame_skip']}\n💾 CRF: {s['crf']}\n⚡ Пресет: {s['preset']}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📐 Ширина", callback_data="gif_set_width"), InlineKeyboardButton(text="📐 Высота", callback_data="gif_set_height")],
        [InlineKeyboardButton(text="🎞 FPS", callback_data="gif_set_fps"), InlineKeyboardButton(text="⏭ Пропуск", callback_data="gif_set_skip")],
        [InlineKeyboardButton(text="💾 CRF", callback_data="gif_set_crf"), InlineKeyboardButton(text="⚡ Пресет", callback_data="gif_set_preset")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_back(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id): return
    try: await callback.message.delete()
    except: pass
    await admin_cmd(callback.message)

@dp.callback_query(F.data.startswith("gif_set_"))
async def gif_set_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    key = callback.data.replace("gif_set_", "")
    prompts = {"width": "Ширина (256-2048):", "height": "Высота (256-2048):", "fps": "FPS (15-60):", "skip": "Пропуск (1-5):", "crf": "CRF (18-28):", "preset": "Пресет (ultrafast/veryfast/fast/medium/slow):"}
    if key in prompts:
        await state.update_data(gif_set_key=key)
        await state.set_state(GifSettingsStates.waiting_for_value)
        await callback.message.answer(prompts[key], reply_markup=get_cancel_kb(await get_user_lang(callback.from_user.id)))

@dp.message(GifSettingsStates.waiting_for_value)
async def gif_set_value(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    data = await state.get_data()
    key = data.get("gif_set_key")
    if not key: return await state.clear()
    val = message.text.strip()
    conn = await get_db()
    try:
        if key == "preset":
            if val not in ("ultrafast", "veryfast", "fast", "medium", "slow"): raise ValueError
            await conn.execute("UPDATE gif_settings SET preset=? WHERE id=1", (val,))
        else:
            n = int(val)
            limits = {"width": (256, 2048), "height": (256, 2048), "fps": (15, 60), "skip": (1, 5), "crf": (18, 28)}
            lo, hi = limits[key]
            if not (lo <= n <= hi): raise ValueError
            await conn.execute(f"UPDATE gif_settings SET {key if key != 'skip' else 'frame_skip'}=? WHERE id=1", (n,))
        await conn.commit()
        await message.answer("✅ Сохранено.")
    except:
        await message.answer("❌ Некорректное значение.")
    finally:
        await state.clear()

@dp.callback_query(F.data == "admin_ext_stats")
async def admin_ext_stats(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM users"); users = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*), SUM(profit_gram) FROM sales"); deals, total_g = await cur.fetchone()
    text = f"📊 <b>Расширенная статистика</b>\n\n👥 Пользователи: {users}\n📈 Сделки: {deals or 0}\n💰 Прибыль: {total_g or 0:+.4f} GRAM"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass

@dp.callback_query(F.data == "admin_logs")
async def admin_logs(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT user_id, username, action, details, timestamp FROM action_logs ORDER BY id DESC LIMIT 20")
    rows = await cur.fetchall()
    text = "📋 <b>Последние действия:</b>\n\n" + "\n".join([f"🕐 {str(r[4])[11:16]} — ID{r[0]} — {r[2]}" for r in rows]) if rows else "Логов пока нет."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass

@dp.callback_query(F.data == "admin_errors")
async def admin_errors(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT error_type, details, timestamp FROM error_logs ORDER BY id DESC LIMIT 5")
    rows = await cur.fetchall()
    text = "🚨 <b>Последние ошибки:</b>\n\n" + "\n".join([f"⚠️ {r[0]} — {str(r[2])[:16]}\n{r[1][:100]}" for r in rows]) if rows else "✅ Ошибок нет."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.message.answer("📢 Введите текст для рассылки:", reply_markup=get_cancel_kb(await get_user_lang(callback.from_user.id)))

@dp.message(BroadcastState.waiting_for_message)
async def do_broadcast(message: Message, state: FSMContext):
    conn = await get_db()
    cur = await conn.execute("SELECT user_id FROM users"); users = [row[0] async for row in cur]
    success = 0
    for uid in users:
        try: await bot.send_message(uid, message.text); success += 1; await asyncio.sleep(0.05)
        except: pass
    await state.clear()
    await message.answer(f"✅ Рассылка завершена: {success}/{len(users)}")

# ---------- ФОНОВЫЕ ЗАДАЧИ ----------
async def backfill_thumbs():
    while True:
        try:
            conn = await get_db()
            cur = await conn.execute("SELECT id, nft_image FROM sales WHERE thumb_file_id IS NULL AND nft_image IS NOT NULL AND nft_image != '' LIMIT 10")
            for row in await cur.fetchall():
                thumb_id = await upload_thumb_to_telegram(row["nft_image"])
                if thumb_id:
                    await conn.execute("UPDATE sales SET thumb_file_id=? WHERE id=?", (thumb_id, row["id"]))
                    await conn.commit()
                await asyncio.sleep(1.5)
        except: pass
        await asyncio.sleep(60)

async def send_startup_errors():
    try:
        conn = await get_db()
        cur = await conn.execute("SELECT COUNT(*) FROM error_logs WHERE timestamp >= datetime(?, 'unixepoch')", (time.time() - 86400,))
        count = (await cur.fetchone())[0]
        if count > 0:
            await bot.send_message(ADMIN_IDS[0], f"🚨 <b>Ошибки при запуске</b>\nНайдено: {count} ошибок за 24ч.\nОткрой админку.")
    except: pass

# ============================================================
# ВНЕДРЕНИЕ GIFT_SAT
# ============================================================
def init_gift_sat(dp: Dispatcher, bot, get_db, get_user_lang, ADMIN_IDS, AddProfit=None):
    try:
        from gift_sat_module import GiftSatModule
        module = GiftSatModule(bot, get_db, get_user_lang, ADMIN_IDS, AddProfit)
        module.register(dp)
        return module
    except Exception as e:
        logger.error(f"❌ Ошибка модуля GiftSat: {e}")
        return None

# ---------- ЗАПУСК ----------
async def main():
    global browser_instance
    logger.info("🚀 Бот запускается...")
    await init_db()

    try:
        browser_instance = await pyppeteer.launch(headless=True, executablePath='/usr/bin/chromium', args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])
        logger.info("Chromium запущен.")
    except Exception as e:
        logger.error(f"Chromium error: {e}")
        browser_instance = None

    gift_sat_module = init_gift_sat(dp, bot, get_db, get_user_lang, ADMIN_IDS, AddProfit)
    if gift_sat_module:
        asyncio.create_task(gift_sat_module.poll_sales())
        logger.info("✅ GiftSat модуль подключён")

    asyncio.create_task(backfill_thumbs())
    await send_startup_errors()

    try: await bot.delete_webhook(drop_pending_updates=True)
    except: pass

    logger.info("🤖 Бот запущен!")
    try:
        await dp.start_polling(bot)
    finally:
        if browser_instance:
            try: await browser_instance.close()
            except: pass
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
