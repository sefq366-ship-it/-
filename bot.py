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
import zipfile
import csv
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont

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

# ---------- ЭМОДЗИ ----------
EMOJI_COLLECTION_FALLBACK = "🎁"
EMOJI_DIAMOND  = '<tg-emoji emoji-id="5296742257146241213">💎</tg-emoji>'
EMOJI_MONEY    = '<tg-emoji emoji-id="5902206159095339799">🤑</tg-emoji>'
EMOJI_DOLLAR   = '<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji>'
EMOJI_LINK     = '<tg-emoji emoji-id="6028171274939797252">🔗</tg-emoji>'
EMOJI_BUY      = '<tg-emoji emoji-id="6039420807900303010">📥</tg-emoji>'
EMOJI_SELL     = '<tg-emoji emoji-id="6043874504302661409">📤</tg-emoji>'

EMOJI_MODEL_FALLBACK    = "🎨"
EMOJI_BACKDROP_FALLBACK = "⚫"
EMOJI_SYMBOL_FALLBACK   = "🌸"

# ---------- КОНФИГ ----------
BOT_TOKEN = "8"
ADMIN_IDS = [1012040843]
DB_PATH = "sales.db"
BOT_URL = "https://t.me/Stars2ProfitBot"

GIF_CHAT_ID = -5009413752

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

db = None
browser_instance = None
gif_render_lock = asyncio.Lock()

gif_render_tasks: dict = {}

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
    waiting_for_search = State()
    waiting_for_confirm = State()
    waiting_for_nft_link = State()
    waiting_for_sell_amount = State()
    waiting_for_royalty = State()

class CalcStates(StatesGroup):
    waiting_for_amount = State()

class HistorySearch(StatesGroup):
    waiting_for_query = State()

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
        for ext in ["-wal", "-shm"]:
            p = Path(DB_PATH + ext)
            if p.exists():
                try:
                    p.unlink()
                except:
                    pass
        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA foreign_keys=ON")
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
            nft_image TEXT,
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
            unavailable INTEGER DEFAULT 0,
            retry_after REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_inline_points (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0,
            last_shared_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_achievements (
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, code)
        );
        CREATE TABLE IF NOT EXISTS daily_profit (
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            profit_gram REAL DEFAULT 0,
            profit_usd REAL DEFAULT 0,
            deals INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date)
        );
        CREATE TABLE IF NOT EXISTS thumb_cache (
            slug TEXT PRIMARY KEY,
            file_id TEXT,
            unavailable INTEGER DEFAULT 0,
            retry_after REAL DEFAULT 0,
            attempts INTEGER DEFAULT 0,
            is_placeholder INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    REQUIRED_COLUMNS = {
        "sales": [
            ("nft_link", "TEXT"), ("nft_image", "TEXT"), ("nft_name", "TEXT"),
            ("thumb_file_id", "TEXT"), ("gram_price", "REAL DEFAULT 0"),
            ("gram_price_buy", "REAL DEFAULT 0"), ("gram_price_sell", "REAL DEFAULT 0"),
            ("royalty_gram", "REAL DEFAULT 0"), ("gift_name", "TEXT"),
            ("model", "TEXT"), ("model_rarity", "TEXT"), ("model_emoji_id", "TEXT"),
            ("backdrop", "TEXT"), ("backdrop_rarity", "TEXT"), ("backdrop_emoji_id", "TEXT"),
            ("symbol", "TEXT"), ("symbol_rarity", "TEXT"), ("symbol_emoji_id", "TEXT"),
            ("collection_emoji_id", "TEXT"), ("gif_file_id", "TEXT"),
        ],
        "pending_sales": [
            ("nft_link", "TEXT"), ("nft_image", "TEXT"), ("thumb_file_id", "TEXT"),
            ("gram_price", "REAL DEFAULT 0"), ("gram_price_buy", "REAL DEFAULT 0"),
            ("royalty_gram", "REAL DEFAULT 0"), ("gift_name", "TEXT"),
            ("model", "TEXT"), ("model_rarity", "TEXT"), ("model_emoji_id", "TEXT"),
            ("backdrop", "TEXT"), ("backdrop_rarity", "TEXT"), ("backdrop_emoji_id", "TEXT"),
            ("symbol", "TEXT"), ("symbol_rarity", "TEXT"), ("symbol_emoji_id", "TEXT"),
            ("collection_emoji_id", "TEXT"),
        ],
        "users": [("referred_by", "INTEGER")],
        "user_change_alerts": [("disabled_until", "REAL DEFAULT 0")],
        "gif_cache": [("unavailable", "INTEGER DEFAULT 0"), ("retry_after", "REAL DEFAULT 0")],
        "thumb_cache": [("is_placeholder", "INTEGER DEFAULT 0")],
    }

    for table_name, columns in REQUIRED_COLUMNS.items():
        try:
            cur = await conn.execute(f"PRAGMA table_info({table_name})")
            existing_rows = await cur.fetchall()
            existing_cols = {row[1] for row in existing_rows}
        except Exception as e:
            logger.warning(f"[MIGRATE] Не удалось прочитать {table_name}: {e}")
            continue
        if not existing_cols:
            continue
        for col_name, col_type in columns:
            if col_name not in existing_cols:
                try:
                    await conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                    logger.info(f"[MIGRATE] ✅ {table_name}: добавлена колонка {col_name} ({col_type})")
                except Exception as e:
                    if "duplicate column" not in str(e).lower():
                        logger.warning(f"[MIGRATE] ❌ {table_name}.{col_name}: {e}")

    for admin_id in ADMIN_IDS:
        try:
            await conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (admin_id,))
        except Exception as e:
            logger.warning(f"[MIGRATE] Не удалось добавить админа {admin_id}: {e}")

    try:
        await conn.execute(
            "UPDATE sales SET gram_price_buy = gram_price "
            "WHERE (gram_price_buy IS NULL OR gram_price_buy = 0) AND gram_price > 0"
        )
        await conn.execute(
            "UPDATE sales SET gram_price_sell = gram_price "
            "WHERE (gram_price_sell IS NULL OR gram_price_sell = 0) AND gram_price > 0"
        )
        logger.info("[MIGRATE] ✅ Бэкфилл gram_price_buy/sell из gram_price")
    except Exception as e:
        logger.warning(f"[MIGRATE] Бэкфилл gram_price: {e}")

    try:
        cur = await conn.execute("SELECT COUNT(*) FROM daily_profit")
        dp_count = (await cur.fetchone())[0]
        if dp_count == 0:
            cur = await conn.execute(
                "SELECT user_id, date, SUM(profit_gram), SUM(profit_usd), COUNT(*) "
                "FROM sales GROUP BY user_id, date"
            )
            rows = await cur.fetchall()
            for row in rows:
                uid, d, pg, pu, cnt = row
                if d:
                    await conn.execute(
                        "INSERT OR IGNORE INTO daily_profit (user_id, date, profit_gram, profit_usd, deals) "
                        "VALUES (?,?,?,?,?)",
                        (uid, d, pg or 0, pu or 0, cnt or 0)
                    )
            if rows:
                logger.info(f"[MIGRATE] ✅ daily_profit: заполнено {len(rows)} записей из sales")
    except Exception as e:
        logger.warning(f"[MIGRATE] daily_profit backfill: {e}")

    await conn.commit()
    logger.info("[MIGRATE] ✅ Инициализация БД завершена")

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

# ---------- РАСШИФРОВКА ДЕЙСТВИЙ ----------
ACTION_LABELS = {
    "add_deal": "📊 Добавил сделку", "add_pending": "📥 Создал отложенную покупку",
    "complete_pending": "📤 Завершил отложенную сделку", "edit_deal": "✏️ Редактировал сделку",
    "delete_deal": "🗑 Удалил сделку", "delete_pending": "🗑 Удалил отложенную покупку",
    "set_royalty": "⚙️ Изменил комиссию", "set_goal": "🎯 Установил цель",
    "set_star_rate": "⭐ Изменил курс Stars", "set_change_alert": "🔔 Настроил уведомления",
    "set_gram_alert": "💰 Установил алерт", "donate": "💎 Задонатил",
    "referral_active": "👥 Активировал реферала", "goal_achieved": "🏆 Достиг цели",
    "broadcast": "📢 Сделал рассылку", "gif_settings": "🎨 Изменил настройки гифки",
    "thumb_refresh": "🔄 Обновил картинки", "backup": "💾 Скачал бэкап",
    "timer_add": "⏰ Добавил таймер", "lang_change": "🌐 Сменил язык",
    "inline_share": "📤 Поделился сделкой", "gif_404": "⚠️ Гифка недоступна",
    "thumb_404": "⚠️ Превью недоступно", "achievement": "🏆 Открыл достижение",
}

async def get_user_display(conn, user_id: int) -> str:
    try:
        cur = await conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return f"ID {user_id}"
        if row[0]:
            return f"@{row[0]}"
        if row[1]:
            return _esc(row[1])
        return f"ID {user_id}"
    except Exception:
        return f"ID {user_id}"

# ---------- КУРС ----------
gram_cache = {"price": 0.0, "timestamp": 0}
gram_cache_lock = asyncio.Lock()

async def get_gram_price():
    if gram_cache["price"] > 0 and (time.time() - gram_cache["timestamp"]) < 300:
        return gram_cache["price"]
    async with gram_cache_lock:
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
        gp_buy = float(gram_price_buy or 0)
        gp_sell = float(gram_price_sell or 0)
        if gp_buy > 0 and gp_sell > 0:
            cost_usd = float(buy_amount) * gp_buy
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

async def save_user_royalty(user_id, royalty_gram):
    conn = await get_db()
    await conn.execute(
        "INSERT OR REPLACE INTO user_royalty (user_id, royalty_gram, updated_at) VALUES (?,?,datetime('now'))",
        (user_id, float(royalty_gram))
    )
    await conn.commit()

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
    await log_action(user_id, "", "referral_active", f"реферер: {referrer_id}")
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
    if not catalog or not catalog.get("collection_emoji_id"):
        catalog_by_slug = await get_gift_catalog_from_changes(slug)
        if catalog_by_slug:
            catalog = catalog_by_slug
    source_data = await get_gift_from_fragment(slug, number)
    if not source_data:
        source_data = await get_gift_from_tme(nft_link)
    if not source_data:
        if catalog and catalog.get("collection_emoji_id"):
            result["collection_emoji_id"] = catalog["collection_emoji_id"]
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
    if catalog and catalog.get("collection_emoji_id"):
        result["collection_emoji_id"] = catalog["collection_emoji_id"]
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

# ---------- КРАСИВАЯ ЗАГЛУШКА ----------
def create_placeholder_image(gift_name: str, profit: float) -> bytes:
    img = Image.new("RGB", (320, 320), color=(30, 30, 40))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except:
        font = ImageFont.load_default()
        font_small = ImageFont.load_default()
    text = gift_name[:18]
    profit_text = f"{profit:+.2f} GRAM"
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((320 - w) // 2, 130), text, fill=(255, 255, 255), font=font)
        bbox = draw.textbbox((0, 0), profit_text, font=font_small)
        w = bbox[2] - bbox[0]
        color = (46, 204, 113) if profit > 0 else (231, 76, 60)
        draw.text(((320 - w) // 2, 170), profit_text, fill=color, font=font_small)
    except:
        draw.text((50, 130), text, fill=(255, 255, 255))
        draw.text((50, 170), profit_text, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()

async def upload_thumb_to_telegram(image_url, fallback_text="🎁", gift_name="NFT", profit=0.0, slug=None, caption=None):
    """
    Загружает превью в группу GIF_CHAT_ID.
    - Если slug известен и в thumb_cache есть рабочий file_id (НЕ заглушка) — возвращает его.
    - Если slug помечен unavailable и retry_after не наступил — возвращает None.
    - Иначе скачивает, загружает, сохраняет в thumb_cache.
    - При ошибке ставит unavailable=1, retry_after=+24ч и возвращает заглушку (is_placeholder=1).
    """
    conn = await get_db()

    if slug:
        cur = await conn.execute(
            "SELECT file_id, unavailable, retry_after, is_placeholder FROM thumb_cache WHERE slug=?",
            (slug,)
        )
        row = await cur.fetchone()
        if row and row["file_id"] and not row["is_placeholder"]:
            logger.info(f"[THUMB] {slug}: из кэша (реальная)")
            return row["file_id"]
        if row and row["unavailable"] and row["retry_after"] and time.time() < row["retry_after"]:
            logger.info(f"[THUMB] {slug}: пропуск до {datetime.fromtimestamp(row['retry_after']).strftime('%d.%m %H:%M')}")
            return None

    if not image_url and slug:
        image_url = f"https://nft.fragment.com/gift/{slug}.webp"

    if not image_url:
        try:
            payload = create_placeholder_image(gift_name, profit)
            msg = await bot.send_photo(
                chat_id=GIF_CHAT_ID,
                photo=BufferedInputFile(payload, filename="thumb_placeholder.jpg"),
                caption=caption,
                disable_notification=True
            )
            file_id = msg.photo[-1].file_id
            if slug:
                await conn.execute(
                    "INSERT OR REPLACE INTO thumb_cache (slug, file_id, unavailable, retry_after, attempts, is_placeholder) "
                    "VALUES (?, ?, 0, 0, COALESCE((SELECT attempts FROM thumb_cache WHERE slug=?), 0) + 1, 1)",
                    (slug, file_id, slug)
                )
                await conn.commit()
            return file_id
        except Exception as e:
            logger.warning(f"[THUMB] Не удалось отправить заглушку в группу {GIF_CHAT_ID}: {e}")
            return None

    is_placeholder = False
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as s:
            async with s.get(image_url) as r:
                if r.status != 200:
                    if slug:
                        alt_url = f"https://nft.fragment.com/gift/{slug}.webp"
                        async with s.get(alt_url) as r2:
                            if r2.status == 200:
                                data = await r2.read()
                            else:
                                raise ValueError(f"HTTP {r2.status}")
                    else:
                        raise ValueError(f"HTTP {r.status}")
                else:
                    data = await r.read()

        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.thumbnail((320, 320), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            payload = buf.getvalue()
            fname = "thumb.jpg"
        except Exception as e:
            logger.warning(f"[THUMB] PIL не смог открыть: {e}. Ставлю заглушку.")
            payload = create_placeholder_image(gift_name, profit)
            fname = "thumb_placeholder.jpg"
            is_placeholder = True

        msg = await bot.send_photo(
            chat_id=GIF_CHAT_ID,
            photo=BufferedInputFile(payload, filename=fname),
            caption=caption,
            disable_notification=True
        )
        file_id = msg.photo[-1].file_id

        if slug:
            await conn.execute(
                "INSERT OR REPLACE INTO thumb_cache (slug, file_id, unavailable, retry_after, attempts, is_placeholder) "
                "VALUES (?, ?, 0, 0, COALESCE((SELECT attempts FROM thumb_cache WHERE slug=?), 0) + 1, ?)",
                (slug, file_id, slug, 1 if is_placeholder else 0)
            )
            await conn.commit()
            if is_placeholder:
                logger.info(f"[THUMB] {slug}: заглушка (is_placeholder=1)")
            else:
                logger.info(f"[THUMB] {slug}: загружено в группу")

        return file_id

    except Exception as e:
        logger.warning(f"[THUMB] Ошибка загрузки {image_url} в группу {GIF_CHAT_ID}: {e}")

        if slug:
            retry = time.time() + 86400
            await conn.execute(
                "INSERT OR REPLACE INTO thumb_cache (slug, file_id, unavailable, retry_after, attempts, is_placeholder) "
                "VALUES (?, NULL, 1, ?, COALESCE((SELECT attempts FROM thumb_cache WHERE slug=?), 0) + 1, 0)",
                (slug, retry, slug)
            )
            await conn.commit()
            logger.info(f"[THUMB] {slug}: помечено как недоступное, повтор через 24ч")
            await log_action(0, "system", "thumb_404", f"Slug: {slug}, повтор через 24ч")

        try:
            payload = create_placeholder_image(gift_name, profit)
            msg = await bot.send_photo(
                chat_id=GIF_CHAT_ID,
                photo=BufferedInputFile(payload, filename="thumb_placeholder.jpg"),
                caption=caption,
                disable_notification=True
            )
            file_id = msg.photo[-1].file_id
            if slug:
                await conn.execute(
                    "INSERT OR REPLACE INTO thumb_cache (slug, file_id, unavailable, retry_after, attempts, is_placeholder) "
                    "VALUES (?, ?, 1, ?, COALESCE((SELECT attempts FROM thumb_cache WHERE slug=?), 0) + 1, 1)",
                    (slug, file_id, retry, slug)
                )
                await conn.commit()
            return file_id
        except:
            return None

async def render_gif_for_nft(slug, work_dir):
    s = await get_gif_settings()
    R_W = s["width"]; R_H = s["height"]; R_FPS = s["fps"]
    R_SKIP = s["frame_skip"]; R_CRF = s["crf"]; R_PRESET = s["preset"]
    json_path = work_dir / "a.json"; mp4_path = work_dir / "a.mp4"

    # 1. Пытаемся скачать Lottie с Fragment
    lottie_url = f"https://nft.fragment.com/gift/{slug}.lottie.json"
    lottie_downloaded = False
    try:
        await download_file(lottie_url, json_path)
        lottie_downloaded = True
        logger.info(f"[GIF] {slug}: Lottie скачан с Fragment")
    except Exception as e:
        logger.warning(f"[GIF] {slug}: Fragment не отдал Lottie ({e}), пробую api.changes.tg")

    # 2. Если Fragment не дал — пробуем api.changes.tg
    if not lottie_downloaded:
        try:
            gift_meta_url = f"https://nft.fragment.com/gift/{slug}.json"
            gift_meta_path = work_dir / "meta.json"
            await download_file(gift_meta_url, gift_meta_path)
            with open(gift_meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            gift_id = meta.get("gift_id") or meta.get("id") or meta.get("giftId")
            if not gift_id and "-" in slug:
                gift_id = slug.rsplit("-", 1)[1]
            if not gift_id:
                raise ValueError("Не удалось определить giftId")
            changes_url = f"https://api.changes.tg/original/{gift_id}.json"
            logger.info(f"[GIF] {slug}: пробую {changes_url}")
            await download_file(changes_url, json_path)
            lottie_downloaded = True
            logger.info(f"[GIF] {slug}: Lottie скачан с api.changes.tg (giftId={gift_id})")
        except Exception as e:
            logger.warning(f"[GIF] {slug}: api.changes.tg тоже не дал Lottie ({e})")

    if not lottie_downloaded:
        raise RuntimeError(f"Lottie not found for {slug} (neither Fragment nor api.changes.tg)")

    # 3. Стандартный рендер
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    comp_w = int(data.get('w', 512)); comp_h = int(data.get('h', 512))
    frame_rate = float(data.get('fr', 60)); ip, op = float(data.get('ip', 0)), float(data.get('op', 1))
    step = max(1, round(frame_rate / R_FPS))
    frame_numbers = list(range(int(ip), int(op), step)) or [int(ip)]
    frame_numbers = frame_numbers[::R_SKIP]
    final_fps = max(1, math.ceil(R_FPS / R_SKIP))
    layers = data.get('layers', [])
    bg_layers = [x for x in layers if x.get('nm') in {'Background', 'Pattern', 'Color Icon'}]
    anim_layers = [x for x in layers if x.get('nm') in {'Gift'}]
    if not bg_layers or not anim_layers:
        raise RuntimeError("Не найдены слои")
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
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
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
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg err: {res.stderr[-500:]}")
    return mp4_path

async def ensure_gif_rendered(slug: str, nft_link: str, notify_user_id: int = None):
    conn = await get_db()
    cur = await conn.execute("SELECT file_id, unavailable, retry_after FROM gif_cache WHERE slug=?", (slug,))
    row = await cur.fetchone()
    if row and row["file_id"]:
        if notify_user_id:
            asyncio.create_task(notify_gif_ready(notify_user_id, nft_link, row["file_id"]))
        return row["file_id"]
    if row and row["unavailable"] and row["retry_after"] and time.time() < row["retry_after"]:
        return None

    task = gif_render_tasks.get(slug)
    if task and not task.done():
        try:
            return await task
        except Exception:
            return None

    async def _do():
        async with gif_render_lock:
            cur2 = await conn.execute("SELECT file_id FROM gif_cache WHERE slug=?", (slug,))
            r2 = await cur2.fetchone()
            if r2 and r2["file_id"]:
                return r2["file_id"]
            if not browser_instance:
                return None
            with tempfile.TemporaryDirectory() as tmp:
                mp4_path = await render_gif_for_nft(slug, Path(tmp))

                caption_for_gif = None
                try:
                    cur_info = await conn.execute(
                        "SELECT user_id, category, gift_name, buy_amount, sell_amount, profit_gram, profit_usd, date, nft_link "
                        "FROM sales WHERE nft_link=? ORDER BY id DESC LIMIT 1",
                        (nft_link,)
                    )
                    info_row = await cur_info.fetchone()
                    if info_row:
                        user_id_info = info_row["user_id"]
                        cur_u = await conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (user_id_info,))
                        u_row = await cur_u.fetchone()
                        user_display = "—"
                        if u_row:
                            if u_row["username"]:
                                user_display = f"@{u_row['username']}"
                            elif u_row["first_name"]:
                                user_display = _esc(u_row["first_name"])
                        g_name = info_row["gift_name"] or info_row["category"] or "NFT"
                        caption_for_gif = (
                            f"🎬 <b>Гифка к сделке</b>\n\n"
                            f"👤 {user_display}\n"
                            f"🎁 <b>{_esc(g_name)}</b>\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"💎 {info_row['buy_amount']} → {info_row['sell_amount']} GRAM\n"
                            f"{EMOJI_MONEY} <b>{info_row['profit_gram']:+.4f} GRAM</b> · {EMOJI_DOLLAR} <b>{info_row['profit_usd']:+.2f}$</b>\n"
                            f"📅 {info_row['date']}\n"
                        )
                        if info_row["nft_link"]:
                            caption_for_gif += f"{EMOJI_LINK} <a href='{info_row['nft_link']}'>Открыть NFT</a>"
                except Exception as e:
                    logger.debug(f"ensure_gif_rendered caption build: {e}")

                msg = await bot.send_animation(
                    chat_id=GIF_CHAT_ID,
                    animation=FSInputFile(str(mp4_path), filename=f"{slug}.mp4"),
                    caption=caption_for_gif,
                    disable_notification=True
                )
                file_id = msg.animation.file_id
                await conn.execute("INSERT OR REPLACE INTO gif_cache (slug, file_id, unavailable, retry_after) VALUES (?, ?, 0, 0)", (slug, file_id))
                await conn.commit()
                logger.info(f"[GIF] {slug} отрендерена и сохранена в группу {GIF_CHAT_ID}")
                return file_id

    task = asyncio.create_task(_do())
    gif_render_tasks[slug] = task
    try:
        result = await task
    except Exception as e:
        err = str(e)
        if "404" in err:
            retry = time.time() + 86400
            await conn.execute("INSERT OR REPLACE INTO gif_cache (slug, file_id, unavailable, retry_after) VALUES (?, NULL, 1, ?)", (slug, retry))
            await conn.commit()
            logger.info(f"[GIF] {slug} недоступна (404) — повтор через 24ч")
            await log_action(0, "system", "gif_404", f"Slug: {slug}, повтор через 24ч")
        else:
            logger.warning(f"[GIF] {slug}: {e}")
            if "chat not found" in err.lower() or "chat_id is empty" in err.lower():
                logger.error(f"[GIF] ❌ НЕВЕРНЫЙ GIF_CHAT_ID={GIF_CHAT_ID}. Проверьте ID группы через @userinfobot (должен начинаться с -100)")
        result = None
    finally:
        gif_render_tasks.pop(slug, None)

    if result and notify_user_id:
        asyncio.create_task(notify_gif_ready(notify_user_id, nft_link, result))
    return result

async def background_gif_render(nft_link, notify_user_id=None):
    if not nft_link or "t.me/nft/" not in nft_link:
        return
    slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0]
    await ensure_gif_rendered(slug, nft_link, notify_user_id=notify_user_id)

async def notify_gif_ready(user_id: int, nft_link: str, gif_file_id: str = None):
    try:
        conn = await get_db()
        cur = await conn.execute(
            "SELECT id, category, gift_name, buy_amount, sell_amount, profit_gram, profit_usd "
            "FROM sales WHERE user_id=? AND nft_link=? ORDER BY id DESC LIMIT 1",
            (user_id, nft_link)
        )
        row = await cur.fetchone()
        if row:
            deal_id, category, gift_name, buy_amt, sell_amt, profit_gram, profit_usd = row
            gift_name = gift_name or category or "NFT"
            profit_gram = profit_gram or 0
            profit_usd = profit_usd or 0
            text = (
                f"🎬 <b>Гифка к сделке готова!</b>\n\n"
                f"🎁 <b>{_esc(gift_name)}</b> · сделка <b>#{deal_id}</b>\n"
                f"{EMOJI_DIAMOND} {buy_amt} → {sell_amt} GRAM\n"
                f"{EMOJI_MONEY} <b>{profit_gram:+.4f} GRAM</b> · {EMOJI_DOLLAR} <b>{profit_usd:+.2f}$</b>\n\n"
                f"📤 Поделись ею в чате — пусть другие увидят твой профит "
                f"(и получат <b>+2 очка</b> к репутации за отправку)."
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📤 Поделиться сделкой", switch_inline_query=str(deal_id))],
                [InlineKeyboardButton(text="👀 Как это работает", callback_data="show_inline_hint")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
            ])
            if gif_file_id:
                try:
                    await bot.send_animation(chat_id=user_id, animation=gif_file_id, caption=text, reply_markup=kb)
                    return
                except Exception as e:
                    logger.debug(f"notify_gif_ready send_animation failed: {e}")
            await bot.send_message(user_id, text, reply_markup=kb)
            return

        cur = await conn.execute(
            "SELECT id, category, gift_name, buy_amount FROM pending_sales "
            "WHERE user_id=? AND nft_link=? ORDER BY id DESC LIMIT 1",
            (user_id, nft_link)
        )
        pend = await cur.fetchone()
        if pend:
            gift_name = pend["gift_name"] or pend["category"] or "NFT"
            text = (
                f"🎬 <b>Гифка для отложенной покупки готова!</b>\n\n"
                f"🎁 <b>{_esc(gift_name)}</b> · pending <b>#{pend['id']}</b>\n"
                f"{EMOJI_BUY} {pend['buy_amount']} GRAM\n\n"
                f"Она появится сразу, как только ты закроешь сделку — ждать не придётся."
            )
            try:
                await bot.send_message(user_id, text)
            except: pass
    except Exception as e:
        logger.debug(f"notify_gif_ready error: {e}")

@dp.callback_query(F.data == "show_inline_hint")
async def show_inline_hint(callback: CallbackQuery):
    await callback.answer()
    text = (
        "💡 <b>Как поделиться сделкой:</b>\n\n"
        "1️⃣ Нажми кнопку «📤 Поделиться сделкой»\n"
        "2️⃣ Выбери чат, куда отправить\n"
        "3️⃣ Бот автоматически подставит красивую карточку с гифкой\n\n"
        "🎁 За каждую отправку ты получаешь <b>+2 очка репутации</b>.\n"
        "Смотри свой прогресс в разделе «👥 Рефералы»."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except:
        await callback.message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    lang = await get_user_lang(callback.from_user.id)
    try:
        await callback.message.delete()
    except:
        pass
    await callback.message.answer(
        MESSAGES[lang]["start"].format(name=callback.from_user.first_name),
        reply_markup=get_main_kb(lang)
    )

# ---------- /start ----------
@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) > 1 and args[1] == "inline_help":
        await message.answer("🔍 Введи номер сделки (#123), название коллекции или «stats» для статистики.")
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
    await log_action(user_id, "", "lang_change", new_lang)
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
    if not message.text:
        await message.answer("❌ Пожалуйста, отправь ссылку текстом.", reply_markup=get_cancel_kb(lang))
        return
    link = message.text.strip()
    if not link or link == "-":
        await message.answer(MESSAGES[lang]["link_required"], reply_markup=get_cancel_kb(lang))
        return
    await state.update_data(nft_link=link)
    nft_data = await parse_nft_link(link)
    if nft_data:
        await state.update_data(**nft_data)
        gift_name = nft_data.get('gift_name', 'NFT')
        slug = link.split("/nft/")[1].split("/")[0].split("?")[0] if "t.me/nft/" in link else None
        thumb_id = await upload_thumb_to_telegram(nft_data.get("nft_image"), gift_name=gift_name, profit=0.0, slug=slug)
        if thumb_id:
            await state.update_data(thumb_file_id=thumb_id)
        attrs = format_gift_attributes(nft_data)
        collection_emoji = premium_emoji(nft_data.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
        msg_text = f"{collection_emoji} <b>{gift_name}</b>\n{attrs}" if attrs else f"{collection_emoji} <b>{gift_name}</b>\n<i>Характеристики не найдены</i>"
        await message.answer(msg_text, reply_markup=get_cancel_kb(lang))
    await state.set_state(AddProfit.waiting_for_buy_amount)
    await message.answer(MESSAGES[lang]["enter_buy_amount"], reply_markup=get_cancel_kb(lang))

@dp.message(AddProfit.waiting_for_buy_amount)
async def process_buy_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
        gram_price_buy = await get_gram_price()
        await state.update_data(buy_amount=amount, gram_price_buy=gram_price_buy)
        await state.set_state(AddProfit.waiting_for_category)
        await message.answer(f"📥 {amount} GRAM\n{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n\n{MESSAGES[lang]['enter_collection']}", reply_markup=get_cancel_kb(lang))
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
        if amount <= 0:
            raise ValueError
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
        if royalty < 0:
            raise ValueError
        await finalize_profit(message, state, royalty, lang=lang)
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

async def finalize_profit(message: Message, state: FSMContext, royalty: float, user_id: int = None, lang: str = "ru"):
    if user_id is None:
        user_id = message.from_user.id if hasattr(message, 'from_user') else message.chat.id
    data = await state.get_data()
    buy_amount = data["buy_amount"]
    sell_amount = data["sell_amount"]
    gram_price_buy = data.get("gram_price_buy") or 0
    gram_price_sell = data.get("gram_price_sell") or 0
    if gram_price_buy <= 0:
        gram_price_buy = await get_gram_price()
    if gram_price_sell <= 0:
        gram_price_sell = await get_gram_price()

    profit_gram = sell_amount - buy_amount - royalty
    profit_usd = compute_profit_usd(buy_amount, sell_amount, royalty, gram_price_buy, gram_price_sell, fallback_gram_price=gram_price_sell)
    date = datetime.now().strftime("%d.%m.%Y")
    gift_name = data.get('gift_name') or data.get('category') or 'NFT'
    nft_link = data.get("nft_link") or ""
    slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0] if "t.me/nft/" in nft_link else None

    try:
        user_display = f"@{message.from_user.username}" if message.from_user.username else f"ID {user_id}"
    except:
        user_display = f"ID {user_id}"
    attrs_for_caption = format_gift_attributes(data)
    caption_for_group = (
        f"📊 <b>Новая сделка</b>\n\n"
        f"👤 {_esc(user_display)}\n"
        f"🎁 <b>{_esc(gift_name)}</b>\n"
    )
    if attrs_for_caption:
        caption_for_group += f"{attrs_for_caption}\n"
    caption_for_group += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💎 {buy_amount} → {sell_amount} GRAM\n"
        f"🔸 Комиссия: {royalty:.2f} GRAM\n"
        f"{EMOJI_MONEY} <b>{profit_gram:+.4f} GRAM</b> · {EMOJI_DOLLAR} <b>{profit_usd:+.2f}$</b>\n"
        f"📅 {date}\n"
    )
    if nft_link:
        caption_for_group += f"{EMOJI_LINK} <a href='{nft_link}'>Открыть NFT</a>"

    thumb_id = data.get("thumb_file_id")
    if not thumb_id or not str(thumb_id).startswith("AgAC"):
        thumb_id = await upload_thumb_to_telegram(data.get("nft_image"), gift_name=gift_name, profit=profit_gram, slug=slug, caption=caption_for_group)

    conn = await get_db()
    await conn.execute(
        """INSERT INTO sales (user_id, category, nft_link, nft_image, thumb_file_id, date, buy_amount, sell_amount, gram_price,
           gram_price_buy, gram_price_sell, profit_gram, profit_usd, royalty_gram, gift_name, model, model_rarity, model_emoji_id,
           backdrop, backdrop_rarity, backdrop_emoji_id, symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, data["category"], data["nft_link"], data.get("nft_image"), thumb_id, date, buy_amount, sell_amount, gram_price_sell,
         gram_price_buy, gram_price_sell, round(profit_gram, 4), profit_usd, royalty,
         data.get("gift_name"), data.get("model"), data.get("model_rarity"), data.get("model_emoji_id"),
         data.get("backdrop"), data.get("backdrop_rarity"), data.get("backdrop_emoji_id"),
         data.get("symbol"), data.get("symbol_rarity"), data.get("symbol_emoji_id"), data.get("collection_emoji_id"))
    )
    await conn.commit()

    await log_action(
        user_id, "",
        "add_deal",
        f"{data['category']}: {buy_amount} → {sell_amount} GRAM (прибыль {profit_gram:+.4f} GRAM / {profit_usd:+.2f}$)"
    )

    await _update_daily_profit(user_id, date, profit_gram, profit_usd, 1)
    await add_user_collection(user_id, data["category"])
    await state.clear()
    await activate_referral(user_id)
    await check_goal_achievement(user_id)
    await check_achievements(user_id)

    msgs = MESSAGES[lang]
    attrs = format_gift_attributes(data)
    collection_emoji = premium_emoji(data.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
    text = msgs["sale_saved"].format(category=data['category'], buy=buy_amount, sell=sell_amount, royalty=f"{royalty:.2f}", profit=f"{profit_gram:+.4f}", usd=f"{profit_usd:+.2f}")
    header = f"{collection_emoji} <b>{gift_name}</b>\n{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n{EMOJI_DOLLAR} Курс продажи: <b>${gram_price_sell:.4f}</b>"
    if attrs:
        header = f"{header}\n{attrs}"
    await message.answer(f"{header}\n\n{text}", reply_markup=get_main_kb(lang))

    if nft_link and "t.me/nft/" in nft_link:
        asyncio.create_task(ensure_gif_rendered(slug, nft_link, notify_user_id=user_id))

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
    if not message.text:
        await message.answer("❌ Пожалуйста, отправь ссылку текстом.", reply_markup=get_cancel_kb(lang))
        return
    link = message.text.strip()
    if not link or link == "-":
        await message.answer(MESSAGES[lang]["link_required"], reply_markup=get_cancel_kb(lang))
        return
    await state.update_data(nft_link=link)
    nft_data = await parse_nft_link(link)
    if nft_data:
        await state.update_data(**nft_data)
        gift_name = nft_data.get('gift_name', 'NFT')
        slug = link.split("/nft/")[1].split("/")[0].split("?")[0] if "t.me/nft/" in link else None
        thumb_id = await upload_thumb_to_telegram(nft_data.get("nft_image"), gift_name=gift_name, profit=0.0, slug=slug)
        if thumb_id:
            await state.update_data(thumb_file_id=thumb_id)
        attrs = format_gift_attributes(nft_data)
        collection_emoji = premium_emoji(nft_data.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
        msg_text = f"{collection_emoji} <b>{gift_name}</b>\n{attrs}" if attrs else f"{collection_emoji} <b>{gift_name}</b>\n<i>Характеристики не найдены</i>"
        await message.answer(msg_text, reply_markup=get_cancel_kb(lang))
        if slug and browser_instance:
            asyncio.create_task(ensure_gif_rendered(slug, link, notify_user_id=message.from_user.id))
    await state.set_state(PendingBuy.waiting_for_buy_amount)
    await message.answer(MESSAGES[lang]["enter_buy_amount"], reply_markup=get_cancel_kb(lang))

@dp.message(PendingBuy.waiting_for_buy_amount)
async def process_pending_buy_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
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
        if royalty < 0:
            raise ValueError
        await save_pending(message, state, royalty, message.from_user.id, lang)
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

async def save_pending(message: Message, state: FSMContext, royalty: float, user_id: int, lang: str = "ru"):
    data = await state.get_data()
    if "category" not in data or "nft_link" not in data:
        await message.answer("❌ Ошибка: данные потеряны. Начни создание отложенной покупки заново.", reply_markup=get_main_kb(lang))
        await state.clear()
        return

    gram_price_buy = data.get("gram_price_buy") or await get_gram_price()
    conn = await get_db()
    await conn.execute(
        """INSERT INTO pending_sales (user_id, category, nft_link, nft_image, thumb_file_id, date, buy_amount, gram_price, gram_price_buy, royalty_gram,
           gift_name, model, model_rarity, model_emoji_id, backdrop, backdrop_rarity, backdrop_emoji_id, symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, data["category"], data["nft_link"], data.get("nft_image"), data.get("thumb_file_id"), datetime.now().strftime("%d.%m.%Y"),
         data["buy_amount"], gram_price_buy, gram_price_buy, royalty,
         data.get("gift_name"), data.get("model"), data.get("model_rarity"), data.get("model_emoji_id"),
         data.get("backdrop"), data.get("backdrop_rarity"), data.get("backdrop_emoji_id"),
         data.get("symbol"), data.get("symbol_rarity"), data.get("symbol_emoji_id"), data.get("collection_emoji_id"))
    )
    await conn.commit()
    await log_action(user_id, "", "add_pending", f"{data['category']}: покупка {data['buy_amount']} GRAM, комиссия {royalty:.2f}")
    await state.clear()

    gift_name = data.get("gift_name") or data["category"] or "NFT"
    ce = premium_emoji(data.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
    attrs = format_gift_attributes({
        "model": data.get("model"), "model_rarity": data.get("model_rarity"), "model_emoji_id": data.get("model_emoji_id"),
        "backdrop": data.get("backdrop"), "backdrop_rarity": data.get("backdrop_rarity"), "backdrop_emoji_id": data.get("backdrop_emoji_id"),
        "symbol": data.get("symbol"), "symbol_rarity": data.get("symbol_rarity"), "symbol_emoji_id": data.get("symbol_emoji_id"),
    })
    nft_link = data.get("nft_link") or ""
    link_line = f"{EMOJI_LINK} <a href='{nft_link}'>Открыть NFT</a>" if nft_link else "—"
    date_str = datetime.now().strftime("%d.%m.%Y")

    header = (f"✅ <b>Отложенная покупка сохранена!</b>\n\n{ce} <b>{_esc(gift_name)}</b>\n")
    if attrs:
        header += f"{attrs}\n"
    header += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{EMOJI_BUY} Покупка: <b>{data['buy_amount']} GRAM</b>\n"
        f"🔸 Комиссия: <b>{royalty:.2f} GRAM</b>\n"
        f"{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n"
        f"📅 {date_str}\n"
        f"{link_line}\n\n"
        f"<i>Завершить сделку можно в разделе «📤 Завершить сделку»</i>"
    )
    thumb_id = data.get("thumb_file_id")
    if thumb_id and isinstance(thumb_id, str) and thumb_id.startswith("AgAC"):
        try:
            await message.answer_photo(photo=thumb_id, caption=header, reply_markup=get_main_kb(lang))
            if nft_link and "t.me/nft/" in nft_link and browser_instance:
                slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0]
                asyncio.create_task(ensure_gif_rendered(slug, nft_link, notify_user_id=user_id))
            return
        except: pass
    await message.answer(header, reply_markup=get_main_kb(lang))
    if nft_link and "t.me/nft/" in nft_link and browser_instance:
        slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0]
        asyncio.create_task(ensure_gif_rendered(slug, nft_link, notify_user_id=user_id))

# ---------- ЗАВЕРШЕНИЕ СДЕЛКИ ----------
PENDING_PAGE_SIZE = 5

async def show_pending_page(message: Message, user_id: int, page: int, edit: bool = False):
    lang = await get_user_lang(user_id)
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM pending_sales WHERE user_id=?", (user_id,))
    total = (await cur.fetchone())[0]
    if total == 0:
        await message.answer(MESSAGES[lang]["no_pending"], reply_markup=get_main_kb(lang))
        return
    total_pages = (total + PENDING_PAGE_SIZE - 1) // PENDING_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    offset = page * PENDING_PAGE_SIZE
    cur = await conn.execute(
        "SELECT * FROM pending_sales WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (user_id, PENDING_PAGE_SIZE, offset)
    )
    rows = await cur.fetchall()
    text = f"📤 <b>Отложенные сделки</b> · стр. {page+1}/{total_pages} (всего {total})\n\n"
    kb_rows = []
    for i, p in enumerate(rows, 1):
        ce = premium_emoji(p["collection_emoji_id"], EMOJI_COLLECTION_FALLBACK)
        gift_name = (p["gift_name"] if "gift_name" in p.keys() else None) or p["category"] or "NFT"
        text += f"<b>{i}.</b> {ce} <b>#{p['id']}</b> · {_esc(gift_name)}\n"
        text += f"   {EMOJI_DIAMOND} {p['buy_amount']} GRAM · 🔸 {p['royalty_gram'] or 0:.2f} · 📅 {p['date']}\n"
        if p["nft_link"]:
            text += f"   {EMOJI_LINK} <a href='{p['nft_link']}'>Открыть NFT</a>\n"
        text += "\n"
        kb_rows.append([
            InlineKeyboardButton(text=f"✅ #{p['id']}", callback_data=f"complete_{p['id']}"),
            InlineKeyboardButton(text=f"🗑 #{p['id']}", callback_data=f"delete_pending_{p['id']}"),
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"pending_page_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"pending_page_{page+1}"))
    kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton(text="🔍 Найти сделку", callback_data="pending_search")])
    kb_rows.append([InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except:
            pass
    await message.answer(text, reply_markup=kb)

@dp.message(F.text.in_(["📤 Завершить сделку", "📤 Complete Deal"]))
async def complete_start(message: Message, state: FSMContext):
    await state.clear()
    await state.update_data(pending_page=0)
    await show_pending_page(message, message.from_user.id, 0)

@dp.callback_query(F.data == "noop")
async def noop_cb(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data.startswith("pending_page_"))
async def pending_page_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    page = int(callback.data.replace("pending_page_", ""))
    await state.update_data(pending_page=page)
    await show_pending_page(callback.message, callback.from_user.id, page, edit=True)

@dp.callback_query(F.data == "pending_back")
async def pending_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    page = data.get("pending_page", 0)
    await state.clear()
    await state.update_data(pending_page=page)
    try:
        await callback.message.delete()
    except:
        pass
    await show_pending_page(callback.message, callback.from_user.id, page)

# ---------- ПОИСК В ОТЛОЖЕННЫХ ----------
@dp.callback_query(F.data == "pending_search")
async def pending_search_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(CompletePending.waiting_for_search)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="pending_back")]
    ])
    await callback.message.answer(
        "🔍 <b>Поиск по отложенным</b>\n\n"
        "Введи что угодно:\n"
        "• коллекцию — <code>LuckyLocket</code>, <code>Redo</code>\n"
        "• ссылку — <code>https://t.me/nft/LuckyLocket-42</code>\n"
        "• номер — <code>42</code> или <code>#42</code>\n"
        "• модель — <code>Peach</code>\n"
        "• дату — <code>12.10</code>",
        reply_markup=kb
    )

@dp.message(CompletePending.waiting_for_search)
async def pending_search_process(message: Message, state: FSMContext):
    if not message.text:
        return
    query = message.text.strip()
    if not query:
        await message.answer("❌ Пустой запрос.")
        return
    user_id = message.from_user.id
    conn = await get_db()
    results = []
    exact_match = False
    if "t.me/nft/" in query or "nft.fragment.com" in query:
        try:
            part = query.split("/nft/")[1] if "/nft/" in query else query.split("gift/")[1]
            seg = part.split("/")[0].split("?")[0]
            if "-" in seg:
                slug_raw, num_raw = seg.rsplit("-", 1)
                if num_raw.isdigit():
                    cur = await conn.execute(
                        "SELECT * FROM pending_sales WHERE user_id=? AND nft_link LIKE ? ORDER BY id DESC",
                        (user_id, f"%{slug_raw.lower()}-{num_raw}%")
                    )
                    results = list(await cur.fetchall())
                    if results:
                        exact_match = True
                    else:
                        cur = await conn.execute(
                            "SELECT * FROM pending_sales WHERE user_id=? AND category LIKE ? ORDER BY id DESC",
                            (user_id, f"%{slug_raw}%")
                        )
                        results = list(await cur.fetchall())
                        exact_match = False
        except: pass
    if not results and (query.isdigit() or (query.startswith("#") and query[1:].isdigit())):
        num_q = int(query.lstrip("#"))
        cur = await conn.execute("SELECT * FROM pending_sales WHERE user_id=? AND id=?", (user_id, num_q))
        results = list(await cur.fetchall())
        exact_match = bool(results)
    if not results:
        like = f"%{query}%"
        cur = await conn.execute(
            "SELECT * FROM pending_sales WHERE user_id=? AND (category LIKE ? OR gift_name LIKE ? OR model LIKE ? OR date LIKE ?) ORDER BY id DESC",
            (user_id, like, like, like, like)
        )
        results = list(await cur.fetchall())
        exact_match = False
    if not results:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="pending_search")],
            [InlineKeyboardButton(text="⬅️ К списку", callback_data="pending_back")]
        ])
        await message.answer(f"🔍 По запросу <code>{_esc(query)}</code> ничего не найдено.", reply_markup=kb)
        await state.clear()
        return
    text = f"🔍 <b>Результаты:</b> <code>{_esc(query)}</code>\n"
    text += f"Найдено: <b>{len(results)}</b>\n"
    if not exact_match and ("t.me/nft/" in query or "nft.fragment.com" in query):
        text += "<i>⚠️ Точного совпадения по ссылке нет — показываю все сделки этой коллекции</i>\n"
    text += "\n"
    kb_rows = []
    for i, p in enumerate(results[:5], 1):
        ce = premium_emoji(p["collection_emoji_id"], EMOJI_COLLECTION_FALLBACK)
        gift_name = (p["gift_name"] if "gift_name" in p.keys() else None) or p["category"] or "NFT"
        text += f"<b>{i}.</b> {ce} <b>#{p['id']}</b> · {_esc(gift_name)}\n"
        text += f"   {EMOJI_DIAMOND} {p['buy_amount']} GRAM · 🔸 {p['royalty_gram'] or 0:.2f} · 📅 {p['date']}\n"
        if p["nft_link"]:
            text += f"   {EMOJI_LINK} <a href='{p['nft_link']}'>Открыть NFT</a>\n"
        text += "\n"
        kb_rows.append([
            InlineKeyboardButton(text=f"✅ #{p['id']}", callback_data=f"complete_{p['id']}"),
            InlineKeyboardButton(text=f"🗑 #{p['id']}", callback_data=f"delete_pending_{p['id']}"),
        ])
    if len(results) > 5:
        text += f"<i>… и ещё {len(results) - 5} — уточни запрос</i>\n"
    kb_rows.append([
        InlineKeyboardButton(text="🔍 Новый поиск", callback_data="pending_search"),
        InlineKeyboardButton(text="⬅️ К списку", callback_data="pending_back")
    ])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await state.clear()

# ---------- КАРТОЧКА ВЫБРАННОЙ ----------
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
    data = await state.get_data()
    page = data.get("pending_page", 0)
    await state.clear()
    await state.update_data(pending_id=pending_id, pending_page=page, return_page=page)
    await state.set_state(CompletePending.waiting_for_sell_amount)
    try:
        await callback.message.delete()
    except: pass
    gift_name = (row["gift_name"] if "gift_name" in row.keys() else None) or row["category"] or "NFT"
    ce = premium_emoji(row["collection_emoji_id"], EMOJI_COLLECTION_FALLBACK)
    attrs = format_gift_attributes({
        "model": row["model"], "model_rarity": row["model_rarity"], "model_emoji_id": row["model_emoji_id"],
        "backdrop": row["backdrop"], "backdrop_rarity": row["backdrop_rarity"], "backdrop_emoji_id": row["backdrop_emoji_id"],
        "symbol": row["symbol"], "symbol_rarity": row["symbol_rarity"], "symbol_emoji_id": row["symbol_emoji_id"],
    })
    link = f"<a href='{row['nft_link']}'>Открыть NFT</a>" if row["nft_link"] else "—"
    royalty_saved = float(row["royalty_gram"] or 0)
    text = f"{ce} <b>{_esc(gift_name)}</b> · #{row['id']}\n"
    if attrs:
        text += f"{attrs}\n"
    text += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{EMOJI_DIAMOND} Покупка: <b>{row['buy_amount']} GRAM</b>\n"
        f"🔸 Комиссия в pending: <b>{royalty_saved:.2f} GRAM</b>\n"
        f"📅 {row['date']} · {EMOJI_LINK} {link}\n\n"
        f"💵 Введи сумму продажи в GRAM:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="pending_back")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_deal")]
    ])
    thumb_id = row["thumb_file_id"] if "thumb_file_id" in row.keys() else None
    if thumb_id and isinstance(thumb_id, str) and thumb_id.startswith("AgAC"):
        try:
            await callback.message.answer_photo(photo=thumb_id, caption=text, reply_markup=kb)
            return
        except: pass
    await callback.message.answer(text, reply_markup=kb)

# ---------- ВВОД СУММЫ + ВЫБОР КОМИССИИ ----------
@dp.message(CompletePending.waiting_for_sell_amount)
async def process_complete_sell_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    if not message.text:
        await message.answer("❌ Пожалуйста, отправь число текстом.", reply_markup=get_cancel_kb(lang))
        return
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
        await state.update_data(sell_amount=amount)
        data = await state.get_data()
        pending_id = data.get("pending_id")
        conn = await get_db()
        cur = await conn.execute("SELECT royalty_gram FROM pending_sales WHERE id=? AND user_id=?", (pending_id, message.from_user.id))
        row = await cur.fetchone()
        saved_royalty = float(row[0] or 0) if row else 0.0
        await state.set_state(CompletePending.waiting_for_royalty)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"➕ Добавить {saved_royalty:.2f} GRAM (как в pending)", callback_data=f"complete_royalty_add_{saved_royalty}")],
            [InlineKeyboardButton(text="🔸 Ввести свою комиссию", callback_data="complete_royalty_custom")],
            [InlineKeyboardButton(text="0 (без доп. комиссии)", callback_data="complete_royalty_add_0")],
            [InlineKeyboardButton(text="⬅️ К списку", callback_data="pending_back")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_deal")]
        ])
        await message.answer(
            f"💵 Продажа: <b>{amount} GRAM</b>\n\n"
            f"🔸 Комиссия, которую ты вводил при создании: <b>{saved_royalty:.2f} GRAM</b>\n\n"
            f"Добавить её к сделке или ввести другую?",
            reply_markup=kb
        )
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.callback_query(F.data.startswith("complete_royalty_add_"))
async def complete_royalty_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    val = callback.data.replace("complete_royalty_add_", "")
    try:
        extra = float(val)
    except:
        extra = 0.0
    await _finalize_pending_with_extra(callback.message, state, extra, callback.from_user.id, lang)

@dp.callback_query(F.data == "complete_royalty_custom")
async def complete_royalty_custom_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await callback.message.answer("🔸 Введи комиссию в GRAM (добавится к комиссии из pending):", reply_markup=get_cancel_kb(lang))

@dp.message(CompletePending.waiting_for_royalty)
async def process_complete_custom_royalty(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    if not message.text:
        await message.answer("❌ Пожалуйста, отправь число текстом.", reply_markup=get_cancel_kb(lang))
        return
    try:
        extra = float(message.text.replace(",", "."))
        if extra < 0:
            raise ValueError
        await _finalize_pending_with_extra(message, state, extra, message.from_user.id, lang)
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

# ---------- ЭКРАН ЗАГРУЗКИ ГИФКИ ----------
async def _loading_gif_screen(chat_id: int, deal_id: int) -> int:
    text = (
        f"🎬 <b>Генерирую гифку к сделке #{deal_id}…</b>\n\n"
        f"⏳ Обычно это занимает 10–30 секунд.\n"
        f"Бот не завис — он рендерит анимацию подарка.\n\n"
        f"<i>Если Fragment ещё не подгрузил Lottie — мы попробуем позже автоматически.</i>"
    )
    msg = await bot.send_message(chat_id, text)
    return msg.message_id

async def _loading_ticker(chat_id: int, message_id: int, deal_id: int, stop_event: asyncio.Event):
    secs = 0
    frames = ["⏳", "⌛"]
    idx = 0
    try:
        while not stop_event.is_set():
            await asyncio.sleep(4)
            secs += 4
            idx = (idx + 1) % len(frames)
            text = (
                f"🎬 <b>Генерирую гифку к сделке #{deal_id}…</b> {frames[idx]}\n\n"
                f"⏱ Прошло: {secs} сек.\n"
                f"Бот не завис — он рендерит анимацию подарка.\n\n"
                f"<i>Если Fragment ещё не подгрузил Lottie — мы попробуем позже автоматически.</i>"
            )
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
            except:
                pass
    except asyncio.CancelledError:
        pass

async def _finalize_pending_with_extra(message: Message, state: FSMContext, extra_royalty: float, user_id: int, lang: str = "ru"):
    data = await state.get_data()
    pending_id = data.get("pending_id")
    sell_amount = data.get("sell_amount")
    if not pending_id or sell_amount is None:
        await message.answer("❌ Данные потеряны. Начни заново.", reply_markup=get_main_kb(lang))
        await state.clear()
        return

    conn = await get_db()
    cur = await conn.execute("SELECT * FROM pending_sales WHERE id=? AND user_id=?", (pending_id, user_id))
    row = await cur.fetchone()
    if not row:
        await message.answer(MESSAGES[lang]["error_not_found"], reply_markup=get_main_kb(lang))
        await state.clear()
        return

    saved_royalty = float(row["royalty_gram"] or 0)
    total_royalty = saved_royalty + float(extra_royalty or 0)
    buy_amt = row["buy_amount"]
    gram_price_sell = await get_gram_price()
    gram_price_buy = row["gram_price_buy"] if "gram_price_buy" in row.keys() and row["gram_price_buy"] else gram_price_sell
    profit_gram = sell_amount - buy_amt - total_royalty
    profit_usd = compute_profit_usd(buy_amt, sell_amount, total_royalty, gram_price_buy, gram_price_sell, fallback_gram_price=gram_price_sell)

    nft_data = {
        "gift_name": row["gift_name"] if "gift_name" in row.keys() else None,
        "model": row["model"] if "model" in row.keys() else None,
        "model_rarity": row["model_rarity"] if "model_rarity" in row.keys() else None,
        "model_emoji_id": row["model_emoji_id"] if "model_emoji_id" in row.keys() else None,
        "backdrop": row["backdrop"] if "backdrop" in row.keys() else None,
        "backdrop_rarity": row["backdrop_rarity"] if "backdrop_rarity" in row.keys() else None,
        "backdrop_emoji_id": row["backdrop_emoji_id"] if "backdrop_emoji_id" in row.keys() else None,
        "symbol": row["symbol"] if "symbol" in row.keys() else None,
        "symbol_rarity": row["symbol_rarity"] if "symbol_rarity" in row.keys() else None,
        "symbol_emoji_id": row["symbol_emoji_id"] if "symbol_emoji_id" in row.keys() else None,
        "collection_emoji_id": row["collection_emoji_id"] if "collection_emoji_id" in row.keys() else None,
        "nft_image": row["nft_image"] if "nft_image" in row.keys() else None,
    }

    nft_link = row["nft_link"] or data.get("nft_link")
    if not nft_data["model"] and nft_link:
        fresh = await parse_nft_link(nft_link)
        if fresh:
            for k, v in fresh.items():
                if v is not None and not nft_data.get(k):
                    nft_data[k] = v

    try:
        user_display = f"@{message.from_user.username}" if message.from_user.username else f"ID {user_id}"
    except:
        user_display = f"ID {user_id}"
    attrs_for_caption = format_gift_attributes(nft_data) if nft_data else ""
    caption_for_group = (
        f"📊 <b>Закрыта отложенная сделка</b>\n\n"
        f"👤 {_esc(user_display)}\n"
        f"🎁 <b>{_esc(nft_data.get('gift_name') or row['category'] or 'NFT')}</b>\n"
    )
    if attrs_for_caption:
        caption_for_group += f"{attrs_for_caption}\n"
    caption_for_group += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💎 {buy_amt} → {sell_amount} GRAM\n"
        f"🔸 Комиссия: {total_royalty:.2f} GRAM\n"
        f"{EMOJI_MONEY} <b>{profit_gram:+.4f} GRAM</b> · {EMOJI_DOLLAR} <b>{profit_usd:+.2f}$</b>\n"
        f"📅 {row['date']}\n"
    )
    if nft_link:
        caption_for_group += f"{EMOJI_LINK} <a href='{nft_link}'>Открыть NFT</a>"

    thumb_id = row["thumb_file_id"] if "thumb_file_id" in row.keys() else None
    if not thumb_id or not str(thumb_id).startswith("AgAC"):
        gift_name_tmp = nft_data.get("gift_name") or row["category"] or "NFT"
        slug_tmp = nft_link.split("/nft/")[1].split("/")[0].split("?")[0] if nft_link and "t.me/nft/" in nft_link else None
        thumb_id = await upload_thumb_to_telegram(nft_data.get("nft_image"), gift_name=gift_name_tmp, profit=profit_gram, slug=slug_tmp, caption=caption_for_group)

    cur = await conn.execute(
        """INSERT INTO sales (user_id, category, nft_link, nft_image, thumb_file_id, date, buy_amount, sell_amount, gram_price,
           gram_price_buy, gram_price_sell, profit_gram, profit_usd, royalty_gram, gift_name, model, model_rarity, model_emoji_id,
           backdrop, backdrop_rarity, backdrop_emoji_id, symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, row["category"], nft_link, nft_data.get("nft_image"), thumb_id, row["date"], buy_amt, sell_amount, gram_price_sell,
         gram_price_buy, gram_price_sell, round(profit_gram, 4), profit_usd, total_royalty,
         nft_data.get("gift_name"), nft_data.get("model"), nft_data.get("model_rarity"), nft_data.get("model_emoji_id"),
         nft_data.get("backdrop"), nft_data.get("backdrop_rarity"), nft_data.get("backdrop_emoji_id"),
         nft_data.get("symbol"), nft_data.get("symbol_rarity"), nft_data.get("symbol_emoji_id"), nft_data.get("collection_emoji_id"))
    )
    new_deal_id = cur.lastrowid
    await conn.execute("DELETE FROM pending_sales WHERE id=?", (pending_id,))
    if nft_link:
        await conn.execute("DELETE FROM timers WHERE user_id=? AND nft_link=? AND notified=0", (user_id, nft_link))
    await conn.commit()

    await log_action(user_id, "", "complete_pending", f"#{pending_id} {row['category']}: {buy_amt} → {sell_amount} GRAM (прибыль {profit_gram:+.4f} GRAM / {profit_usd:+.2f}$)")

    await _update_daily_profit(user_id, row["date"], profit_gram, profit_usd, 1)

    await add_user_collection(user_id, row["category"])
    await state.clear()
    await activate_referral(user_id)
    await check_goal_achievement(user_id)
    await check_achievements(user_id)

    link = f"<a href='{nft_link}'>Открыть NFT</a>" if nft_link else "—"
    msgs = MESSAGES[lang]
    attrs = format_gift_attributes(nft_data) if nft_data else ""
    ce = premium_emoji(nft_data.get("collection_emoji_id") if nft_data else None, EMOJI_COLLECTION_FALLBACK)
    gift_name = (nft_data.get("gift_name") if nft_data else None) or row["category"] or "NFT"
    text = msgs["deal_completed"].format(category=row["category"], buy=buy_amt, sell=sell_amount, profit=f"{profit_gram:+.4f}", link=link)
    header = f"🎉 <b>Сделка закрыта!</b>\n\n{ce} <b>{_esc(gift_name)}</b>\n"
    if attrs:
        header += f"{attrs}\n"
    header += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{EMOJI_DIAMOND} {buy_amt} → {sell_amount} GRAM\n"
        f"🔸 Комиссия: {total_royalty:.2f} GRAM\n"
        f"{EMOJI_MONEY} <b>{profit_gram:+.4f} GRAM</b> · {EMOJI_DOLLAR} <b>{profit_usd:+.2f}$</b>\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=str(new_deal_id))],
        [InlineKeyboardButton(text="📋 История", callback_data="open_history")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="back_to_main")]
    ])

    gif_id = None
    slug = None
    if nft_link and "t.me/nft/" in nft_link:
        slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0]
        gif_id = await ensure_gif_rendered(slug, nft_link)

    if gif_id:
        try:
            await bot.send_animation(chat_id=user_id, animation=gif_id, caption=header + "\n" + text, reply_markup=kb)
            return
        except Exception as e:
            logger.warning(f"send_animation final: {e}")

    note = "\n\n🎬 <b>Гифка появится, как только Fragment подгрузит Lottie.</b>\nМы автоматически попробуем снова через 24 часа."
    if thumb_id and isinstance(thumb_id, str) and thumb_id.startswith("AgAC"):
        try:
            await bot.send_photo(chat_id=user_id, photo=thumb_id, caption=header + "\n" + text + note, reply_markup=kb)
            return
        except: pass
    await message.answer(header + "\n" + text + note, reply_markup=kb)

@dp.callback_query(F.data == "open_history")
async def open_history_cb(callback: CallbackQuery):
    await callback.answer()
    await show_history_page(callback.message, callback.from_user.id, 0)

# ---------- УДАЛЕНИЕ PENDING ----------
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
        await log_action(callback.from_user.id, "", "delete_pending", f"#{pending_id}")
    await state.clear()
    try:
        await callback.message.edit_text(MESSAGES[lang]["deleted"])
    except:
        await callback.message.answer(MESSAGES[lang]["deleted"])

# ---------- ИСТОРИЯ + ПОИСК ----------
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
    if page > 0:
        nav.append(InlineKeyboardButton(text=MESSAGES[lang]["history_prev"], callback_data=f"hist_prev_{page}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text=MESSAGES[lang]["history_next"], callback_data=f"hist_next_{page}"))
    if nav:
        kb_rows.append(nav)
    actions = []
    for d in deals:
        actions.append(InlineKeyboardButton(text=MESSAGES[lang]["edit_btn"].format(id=d['id']), callback_data=f"edit_{d['id']}"))
        actions.append(InlineKeyboardButton(text=MESSAGES[lang]["delete_btn"].format(id=d['id']), callback_data=f"delete_{d['id']}"))
    for i in range(0, len(actions), 4):
        kb_rows.append(actions[i:i+4])
    kb_rows.append([InlineKeyboardButton(text="🔍 Найти сделку", callback_data="history_search")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

# ---------- НОВАЯ СТАТИСТИКА: daily_profit + достижения + streak + график ----------

ACHIEVEMENTS = {
    "first_deal":    {"emoji": "🥇", "title": "Первая сделка",       "desc": "Закрыл первую сделку"},
    "ten_deals":     {"emoji": "🔟", "title": "Десятка",             "desc": "10 сделок закрыто"},
    "hundred_deals": {"emoji": "💯", "title": "Сотка сделок",        "desc": "100 сделок закрыто"},
    "profit_10":     {"emoji": "💎", "title": "Первая десятка",      "desc": "Профит > 10 GRAM"},
    "profit_100":    {"emoji": "👑", "title": "Сотка профита",       "desc": "Профит > 100 GRAM"},
    "profit_1000":   {"emoji": "🏆", "title": "Тысячник",            "desc": "Профит > 1000 GRAM"},
    "streak_3":      {"emoji": "🔥", "title": "Серия 3",             "desc": "3 дня подряд со сделками"},
    "streak_7":      {"emoji": "⚡", "title": "Серия 7",             "desc": "7 дней подряд со сделками"},
    "streak_30":     {"emoji": "🌟", "title": "Серия 30",            "desc": "30 дней подряд со сделками"},
    "winrate_70":    {"emoji": "🎯", "title": "Снайпер",             "desc": "Winrate ≥ 70% (мин. 10 сделок)"},
    "goal_achieved": {"emoji": "🏁", "title": "Цель достигнута",     "desc": "Достиг цели по профиту"},
    "inline_10":     {"emoji": "📤", "title": "Промоутер",           "desc": "10 инлайн-отправок"},
}

async def _update_daily_profit(user_id: int, date_str: str, profit_gram: float, profit_usd: float, deals: int = 1):
    try:
        conn = await get_db()
        await conn.execute(
            "INSERT INTO daily_profit (user_id, date, profit_gram, profit_usd, deals) VALUES (?,?,?,?,?) "
            "ON CONFLICT(user_id, date) DO UPDATE SET "
            "profit_gram = profit_gram + excluded.profit_gram, "
            "profit_usd = profit_usd + excluded.profit_usd, "
            "deals = deals + excluded.deals",
            (user_id, date_str, profit_gram, profit_usd, deals)
        )
        await conn.commit()
    except Exception as e:
        logger.warning(f"_update_daily_profit: {e}")

async def get_streak(user_id: int):
    conn = await get_db()
    cur = await conn.execute("SELECT date FROM daily_profit WHERE user_id=? AND deals > 0 ORDER BY date DESC", (user_id,))
    rows = await cur.fetchall()
    if not rows:
        return 0, 0
    def parse(d):
        try:
            return datetime.strptime(d, "%d.%m.%Y").date()
        except:
            return None
    dates = []
    for r in rows:
        d = parse(r[0])
        if d:
            dates.append(d)
    if not dates:
        return 0, 0
    today = datetime.now().date()
    cur_streak = 0
    check = today
    dates_set = set(dates)
    if check not in dates_set:
        check = today - timedelta(days=1)
        if check not in dates_set:
            cur_streak = 0
    while check in dates_set:
        cur_streak += 1
        check -= timedelta(days=1)
    best = 0
    run = 1
    sorted_dates = sorted(dates)
    for i in range(1, len(sorted_dates)):
        if (sorted_dates[i] - sorted_dates[i-1]).days == 1:
            run += 1
        else:
            best = max(best, run)
            run = 1
    best = max(best, run)
    return cur_streak, best

async def check_achievements(user_id: int):
    try:
        conn = await get_db()
        cur = await conn.execute("SELECT code FROM user_achievements WHERE user_id=?", (user_id,))
        existing = {r[0] for r in await cur.fetchall()}
        new_codes = []

        cur = await conn.execute("SELECT COUNT(*), SUM(profit_gram), SUM(CASE WHEN profit_gram>0 THEN 1 ELSE 0 END) FROM sales WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        total_deals = row[0] or 0
        total_profit = row[1] or 0
        wins = row[2] or 0

        if total_deals >= 1 and "first_deal" not in existing:
            new_codes.append("first_deal")
        if total_deals >= 10 and "ten_deals" not in existing:
            new_codes.append("ten_deals")
        if total_deals >= 100 and "hundred_deals" not in existing:
            new_codes.append("hundred_deals")
        if total_profit >= 10 and "profit_10" not in existing:
            new_codes.append("profit_10")
        if total_profit >= 100 and "profit_100" not in existing:
            new_codes.append("profit_100")
        if total_profit >= 1000 and "profit_1000" not in existing:
            new_codes.append("profit_1000")

        cur_streak, _ = await get_streak(user_id)
        if cur_streak >= 3 and "streak_3" not in existing:
            new_codes.append("streak_3")
        if cur_streak >= 7 and "streak_7" not in existing:
            new_codes.append("streak_7")
        if cur_streak >= 30 and "streak_30" not in existing:
            new_codes.append("streak_30")

        if total_deals >= 10 and (wins / total_deals) >= 0.7 and "winrate_70" not in existing:
            new_codes.append("winrate_70")

        cur = await conn.execute("SELECT notified FROM profit_goals WHERE user_id=?", (user_id,))
        g = await cur.fetchone()
        if g and g[0] and "goal_achieved" not in existing:
            new_codes.append("goal_achieved")

        cur = await conn.execute("SELECT points FROM user_inline_points WHERE user_id=?", (user_id,))
        p = await cur.fetchone()
        if p and p[0] >= 20 and "inline_10" not in existing:
            new_codes.append("inline_10")

        for code in new_codes:
            await conn.execute("INSERT OR IGNORE INTO user_achievements (user_id, code) VALUES (?,?)", (user_id, code))
        await conn.commit()

        for code in new_codes:
            info = ACHIEVEMENTS.get(code, {})
            try:
                await bot.send_message(
                    user_id,
                    f"🏆 <b>Новое достижение!</b>\n\n"
                    f"{info.get('emoji','🏆')} <b>{info.get('title', code)}</b>\n"
                    f"<i>{info.get('desc','')}</i>"
                )
                await log_action(user_id, "", "achievement", code)
            except: pass
    except Exception as e:
        logger.warning(f"check_achievements: {e}")

def render_profit_chart(daily: list, title: str = "Прибыль за 7 дней (GRAM)"):
    if not daily:
        return None
    try:
        W, H = 800, 400
        PAD_L, PAD_R, PAD_T, PAD_B = 60, 30, 50, 60
        img = Image.new("RGB", (W, H), (24, 26, 36))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        except:
            font = font_small = font_title = ImageFont.load_default()

        profits = [p for _, p in daily]
        max_v = max(max(profits), 0.001)
        min_v = min(min(profits), 0)
        span = max_v - min_v
        if span <= 0:
            span = 1

        draw.text((PAD_L, 10), title, fill=(230, 230, 240), font=font_title)

        plot_w = W - PAD_L - PAD_R
        plot_h = H - PAD_T - PAD_B
        zero_y = PAD_T + plot_h * (max_v / span)

        n = len(daily)
        bar_w = plot_w / n * 0.7
        gap = plot_w / n
        for i, (d, p) in enumerate(daily):
            x_center = PAD_L + gap * i + gap / 2
            bar_h = plot_h * (abs(p) / span) if span else 0
            if bar_h < 2:
                bar_h = 2
            x0 = x_center - bar_w / 2
            x1 = x_center + bar_w / 2
            if p >= 0:
                y0 = zero_y - bar_h
                y1 = zero_y
                color = (46, 204, 113)
            else:
                y0 = zero_y
                y1 = zero_y + bar_h
                color = (231, 76, 60)
            draw.rectangle([x0, y0, x1, y1], fill=color)
            if n <= 40:
                val_text = f"{p:+.1f}"
                try:
                    bbox = draw.textbbox((0, 0), val_text, font=font_small)
                    tw = bbox[2] - bbox[0]
                except:
                    tw = len(val_text) * 7
                draw.text((x_center - tw / 2, y0 - 20 if p >= 0 else y1 + 4), val_text, fill=(200, 200, 210), font=font_small)
            try:
                short_date = d[:5]
            except:
                short_date = d
            if n <= 15 or i % max(1, n // 12) == 0:
                try:
                    bbox = draw.textbbox((0, 0), short_date, font=font_small)
                    tw = bbox[2] - bbox[0]
                except:
                    tw = len(short_date) * 7
                draw.text((x_center - tw / 2, H - PAD_B + 20), short_date, fill=(160, 160, 170), font=font_small)

        draw.line([(PAD_L, zero_y), (W - PAD_R, zero_y)], fill=(80, 80, 100), width=1)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"render_profit_chart: {e}")
        return None

async def user_stats(message: Message):
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    conn = await get_db()

    cur = await conn.execute(
        "SELECT COUNT(*), SUM(profit_gram), SUM(profit_usd), "
        "SUM(CASE WHEN profit_gram > 0 THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN profit_gram < 0 THEN 1 ELSE 0 END), "
        "AVG(profit_gram), MAX(profit_gram), MIN(profit_gram) "
        "FROM sales WHERE user_id=?",
        (user_id,)
    )
    total, sum_g, sum_u, wins, losses, avg_g, best, worst = await cur.fetchone()
    total = total or 0
    if total == 0:
        await message.answer(MESSAGES[lang]["history_empty"], reply_markup=get_main_kb(lang))
        return
    sum_g = sum_g or 0
    sum_u = sum_u or 0
    avg_g = avg_g or 0
    wins = wins or 0
    losses = losses or 0
    winrate = (wins / total * 100) if total else 0

    today = datetime.now().strftime("%d.%m.%Y")
    cur = await conn.execute("SELECT COUNT(*), SUM(profit_gram) FROM sales WHERE user_id=? AND date=?", (user_id, today))
    today_cnt, today_g = await cur.fetchone()
    today_cnt = today_cnt or 0
    today_g = today_g or 0

    cur = await conn.execute("SELECT goal_gram FROM profit_goals WHERE user_id=?", (user_id,))
    goal_row = await cur.fetchone()
    goal = goal_row[0] if goal_row else None

    cur = await conn.execute(
        "SELECT category, COUNT(*), SUM(profit_gram) FROM sales WHERE user_id=? "
        "GROUP BY category ORDER BY SUM(profit_gram) DESC LIMIT 3",
        (user_id,)
    )
    by_cat = await cur.fetchall()

    cur_streak, best_streak = await get_streak(user_id)

    cur = await conn.execute("SELECT code FROM user_achievements WHERE user_id=?", (user_id,))
    unlocked = [r[0] for r in await cur.fetchall()]
    total_ach = len(ACHIEVEMENTS)
    ach_line = ""
    for code, info in ACHIEVEMENTS.items():
        if code in unlocked:
            ach_line += info["emoji"] + " "
        else:
            ach_line += "⚪ "

    percentile_text = ""
    if total >= 10:
        try:
            cur = await conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT user_id, 
                           CAST(SUM(CASE WHEN profit_gram>0 THEN 1 ELSE 0 END) AS REAL)*100.0/COUNT(*) as wr
                    FROM sales GROUP BY user_id HAVING COUNT(*) >= 10
                ) WHERE wr < ?
            """, (winrate,))
            better_than = (await cur.fetchone())[0] or 0
            cur = await conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT user_id FROM sales GROUP BY user_id HAVING COUNT(*) >= 10
                )
            """)
            total_users_with_10 = (await cur.fetchone())[0] or 1
            pct = 100.0 * better_than / total_users_with_10
            if pct >= 50:
                percentile_text = f"🏅 Топ-{int(100-pct)+1}% по winrate среди активных!"
            else:
                percentile_text = f"📊 Ты обгоняешь {pct:.0f}% активных по winrate."
        except:
            pass

    text = "📊 <b>СТАТИСТИКА</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"

    if cur_streak > 0:
        text += f"🔥 Серия: <b>{cur_streak}</b> дн. подряд · рекорд <b>{best_streak}</b>\n"
    if ach_line:
        text += f"🏆 Достижения: {ach_line}<b>({len(unlocked)}/{total_ach})</b>\n"
    text += "\n"

    text += (
        "📈 <b>Сделки</b>\n"
        f"  Всего       <b>{total}</b>\n"
        f"  ✅ В плюс    <b>{wins}</b>\n"
        f"  ❌ В минус   <b>{losses}</b>\n\n"
        f"🎯 <b>Winrate</b>\n"
        f"  {make_progress_bar(wins, total, 12)}\n"
    )
    if percentile_text:
        text += f"  {percentile_text}\n"
    text += "\n"

    text += (
        "💰 <b>Прибыль</b>\n"
        f"  💎 GRAM    <b>{sum_g:+.4f}</b>\n"
        f"  🪙 USD     <b>{sum_u:+.2f}$</b>\n"
        f"  📊 Средняя  <b>{avg_g:+.4f}</b>\n"
        f"  🏆 Лучшая   <b>{(best or 0):+.4f}</b>\n"
        f"  💀 Худшая   <b>{(worst or 0):+.4f}</b>\n\n"
    )

    text += f"📅 <b>Сегодня:</b> {today_cnt} сделок · <b>{today_g:+.4f} GRAM</b>\n"

    if goal:
        text += (
            f"\n🎯 <b>Цель</b> {sum_g:.2f} / {goal:.2f} GRAM\n"
            f"  {make_progress_bar(sum_g, goal, 12)}\n"
        )

    if by_cat:
        text += "\n━━━━━━━━━━━━━━━━━━━━\n📁 <b>Топ коллекций</b>\n"
        for i, (cat, cnt, s) in enumerate(by_cat, 1):
            s = s or 0
            share = (s / sum_g * 100) if sum_g > 0 else 0
            bar = make_progress_bar(share, 100, 8)
            text += f"  {i}. {_esc(cat)}\n     {cnt} шт · {s:+.2f} GRAM · {bar}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 График 7 дней", callback_data="stats_chart_7d"),
         InlineKeyboardButton(text="📅 30 дней", callback_data="stats_chart_30d")],
        [InlineKeyboardButton(text="♾ График за всё время", callback_data="stats_chart_all")],
        [InlineKeyboardButton(text="📋 История", callback_data="open_history"),
         InlineKeyboardButton(text="🏠 Меню", callback_data="back_to_main")],
        [InlineKeyboardButton(text="📤 Поделиться статистикой", switch_inline_query="stats")],
    ])
    await message.answer(text, reply_markup=kb)

@dp.message(F.text.in_(["📊 Статистика", "📊 Stats"]))
@dp.message(Command("stats"))
async def user_stats_handler(message: Message):
    await user_stats(message)

async def _build_stats_chart(callback: CallbackQuery, period: str):
    user_id = callback.from_user.id
    conn = await get_db()
    today = datetime.now().date()

    if period == "7d":
        days_count = 7
        title = "Прибыль за 7 дней (GRAM)"
        cap_title = "Прибыль за 7 дней"
    elif period == "30d":
        days_count = 30
        title = "Прибыль за 30 дней (GRAM)"
        cap_title = "Прибыль за 30 дней"
    else:
        cur = await conn.execute(
            "SELECT date, profit_gram FROM daily_profit WHERE user_id=? AND deals > 0 ORDER BY date ASC",
            (user_id,)
        )
        all_rows = await cur.fetchall()
        if not all_rows:
            await callback.message.answer("📊 Сделок пока не было — график пуст.")
            return
        daily = [(r[0], r[1] or 0) for r in all_rows]
        if len(daily) > 90:
            from collections import OrderedDict
            weekly = OrderedDict()
            for date_str, profit in daily:
                try:
                    dt = datetime.strptime(date_str, "%d.%m.%Y").date()
                    iso = dt.isocalendar()
                    key = f"{iso[0]}-W{iso[1]:02d}"
                    if key not in weekly:
                        weekly[key] = 0.0
                    weekly[key] += profit
                except:
                    continue
            daily = list(weekly.items())
            title = "Прибыль по неделям (GRAM)"
            cap_title = "Прибыль за всё время (по неделям)"
        else:
            title = "Прибыль за всё время (GRAM)"
            cap_title = "Прибыль за всё время"

        total = sum(p for _, p in daily)
        avg = total / max(len(daily), 1)
        if all(p == 0 for _, p in daily):
            await callback.message.answer("📊 Сделок пока не было — график пуст.")
            return
        img_bytes = render_profit_chart(daily, title=title)
        if not img_bytes:
            await callback.message.answer("❌ Не удалось нарисовать график.")
            return
        caption = (
            f"📊 <b>{cap_title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Итого: <b>{total:+.4f} GRAM</b>\n"
            f"📈 Средняя: <b>{avg:+.4f} GRAM</b>\n"
            f"📅 Точек: {len(daily)}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 7 дней", callback_data="stats_chart_7d"),
             InlineKeyboardButton(text="📅 30 дней", callback_data="stats_chart_30d")],
            [InlineKeyboardButton(text="♾ Всё время", callback_data="stats_chart_all")],
            [InlineKeyboardButton(text="⬅️ К статистике", callback_data="back_to_stats")],
        ])
        await callback.message.answer_photo(photo=BufferedInputFile(img_bytes, filename="chart_all.png"), caption=caption, reply_markup=kb)
        return

    days = []
    for i in range(days_count - 1, -1, -1):
        d = today - timedelta(days=i)
        days.append(d.strftime("%d.%m.%Y"))
    cur = await conn.execute(
        f"SELECT date, profit_gram FROM daily_profit WHERE user_id=? AND date IN ({','.join('?' * len(days))})",
        (user_id, *days)
    )
    by_date = {r[0]: r[1] or 0 for r in await cur.fetchall()}
    daily = [(d, by_date.get(d, 0.0)) for d in days]
    total = sum(p for _, p in daily)
    if all(p == 0 for _, p in daily):
        await callback.message.answer(f"📊 За последние {days_count} дней сделок не было — график пуст.")
        return
    img_bytes = render_profit_chart(daily, title=title)
    if not img_bytes:
        await callback.message.answer("❌ Не удалось нарисовать график.")
        return
    caption = (
        f"📊 <b>{cap_title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Итого: <b>{total:+.4f} GRAM</b>\n"
        f"📈 Средняя в день: <b>{total / days_count:+.4f} GRAM</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 7 дней", callback_data="stats_chart_7d"),
         InlineKeyboardButton(text="📅 30 дней", callback_data="stats_chart_30d")],
        [InlineKeyboardButton(text="♾ Всё время", callback_data="stats_chart_all")],
        [InlineKeyboardButton(text="⬅️ К статистике", callback_data="back_to_stats")],
    ])
    await callback.message.answer_photo(photo=BufferedInputFile(img_bytes, filename=f"chart_{days_count}d.png"), caption=caption, reply_markup=kb)


@dp.callback_query(F.data == "stats_chart")
async def stats_chart_cb(callback: CallbackQuery):
    await callback.answer("Рисую график…")
    await _build_stats_chart(callback, "7d")


@dp.callback_query(F.data == "stats_chart_7d")
async def stats_chart_7d_cb(callback: CallbackQuery):
    await callback.answer("Рисую график за 7 дней…")
    try:
        await callback.message.delete()
    except:
        pass
    await _build_stats_chart(callback, "7d")


@dp.callback_query(F.data == "stats_chart_30d")
async def stats_chart_30d_cb(callback: CallbackQuery):
    await callback.answer("Рисую график за 30 дней…")
    try:
        await callback.message.delete()
    except:
        pass
    await _build_stats_chart(callback, "30d")


@dp.callback_query(F.data == "stats_chart_all")
async def stats_chart_all_cb(callback: CallbackQuery):
    await callback.answer("Рисую график за всё время…")
    try:
        await callback.message.delete()
    except:
        pass
    await _build_stats_chart(callback, "all")


@dp.callback_query(F.data == "back_to_stats")
async def back_to_stats_cb(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except:
        pass
    await user_stats(callback.message)

# ---------- ПАГИНАЦИЯ ИСТОРИИ ----------
@dp.callback_query(F.data.startswith("hist_"))
async def history_pagination(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split("_")
    new_page = int(parts[2]) - 1 if parts[1] == "prev" else int(parts[2]) + 1
    await show_history_page(callback.message, callback.from_user.id, new_page)

# ---------- ПОИСК В ИСТОРИИ ----------
@dp.callback_query(F.data == "history_search")
async def history_search_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(HistorySearch.waiting_for_query)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К истории", callback_data="hist_back")]
    ])
    await callback.message.answer(
        "🔍 <b>Поиск по истории</b>\n\n"
        "Введи:\n"
        "• номер сделки — <code>42</code> или <code>#42</code>\n"
        "• коллекцию — <code>LuckyLocket</code>\n"
        "• ссылку — <code>t.me/nft/LuckyLocket-42</code>\n"
        "• модель — <code>Peach</code>",
        reply_markup=kb
    )

@dp.callback_query(F.data == "hist_back")
async def hist_back_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await show_history_page(callback.message, callback.from_user.id, 0)

@dp.message(HistorySearch.waiting_for_query)
async def history_search_process(message: Message, state: FSMContext):
    if not message.text:
        return
    query = message.text.strip()
    if not query:
        await message.answer("❌ Пустой запрос.")
        return
    user_id = message.from_user.id
    conn = await get_db()
    results = []

    if query.isdigit() or (query.startswith("#") and query[1:].isdigit()):
        num = int(query.lstrip("#"))
        cur = await conn.execute("SELECT * FROM sales WHERE user_id=? AND id=?", (user_id, num))
        results = list(await cur.fetchall())

    if not results and ("t.me/nft/" in query or "nft.fragment.com" in query):
        try:
            part = query.split("/nft/")[1] if "/nft/" in query else query.split("gift/")[1]
            seg = part.split("/")[0].split("?")[0]
            if "-" in seg:
                slug, num = seg.rsplit("-", 1)
                if num.isdigit():
                    cur = await conn.execute("SELECT * FROM sales WHERE user_id=? AND nft_link LIKE ? ORDER BY id DESC", (user_id, f"%{slug.lower()}-{num}%"))
                    results = list(await cur.fetchall())
        except: pass

    if not results:
        like = f"%{query}%"
        cur = await conn.execute("SELECT * FROM sales WHERE user_id=? AND (category LIKE ? OR gift_name LIKE ? OR model LIKE ?) ORDER BY id DESC LIMIT 10", (user_id, like, like, like))
        results = list(await cur.fetchall())

    if not results:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="history_search")],
            [InlineKeyboardButton(text="⬅️ К истории", callback_data="hist_back")]
        ])
        await message.answer(f"🔍 По запросу <code>{_esc(query)}</code> ничего не найдено.", reply_markup=kb)
        await state.clear()
        return

    text = f"🔍 <b>Найдено: {len(results)}</b>\n\n"
    kb_rows = []
    for d in results[:10]:
        emoji = get_profit_emoji(d['profit_gram'])
        collection_emoji = premium_emoji(d.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
        gift_line = f"{collection_emoji} {_esc(d['gift_name'])}" if d['gift_name'] else f"📁 {_esc(d['category'])}"
        link = f"<a href='{d['nft_link']}'>NFT</a>" if d.get('nft_link') else "—"
        text += f"{emoji} <b>#{d['id']}</b> · {gift_line}\n   💎 {d['buy_amount']} → {d['sell_amount']} GRAM · 💰 {d['profit_gram']:+.4f} GRAM\n   📅 {d['date']} · {link}\n\n"
        kb_rows.append([
            InlineKeyboardButton(text=f"✏️ #{d['id']}", callback_data=f"edit_{d['id']}"),
            InlineKeyboardButton(text=f"🗑 #{d['id']}", callback_data=f"delete_{d['id']}")
        ])
    kb_rows.append([
        InlineKeyboardButton(text="🔍 Новый поиск", callback_data="history_search"),
        InlineKeyboardButton(text="⬅️ К истории", callback_data="hist_back")
    ])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await state.clear()

# ---------- УДАЛЕНИЕ СДЕЛКИ ----------
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
        await log_action(callback.from_user.id, "", "delete_deal", f"#{deal_id}")
    await state.clear()
    try:
        await callback.message.edit_text(MESSAGES[lang]["deleted"])
    except:
        await callback.message.answer(MESSAGES[lang]["deleted"])

# ---------- КАЛЬКУЛЯТОР ----------
@dp.message(F.text.in_(["🔄 Калькулятор", "🔄 Calculator"]))
@dp.message(Command("calc"))
async def calc_start(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Stars → 💎 GRAM", callback_data="calc_stars_to_gram")],
        [InlineKeyboardButton(text="💎 GRAM → ⭐ Stars", callback_data="calc_gram_to_stars")],
        [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])
    text = (
        "🔄 <b>Калькулятор</b>\n\n"
        "Выбери направление пересчёта:\n"
        "• <b>Stars → GRAM</b> — сколько получишь GRAM за звёзды\n"
        "• <b>GRAM → Stars</b> — сколько Stars нужно на GRAM\n\n"
        "💡 <i>Учитывается курс Stars и комиссия 20%</i>"
    )
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.in_(["calc_stars_to_gram", "calc_gram_to_stars"]))
async def calc_direction(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    direction = callback.data.replace("calc_", "")
    await state.update_data(calc_dir=direction)
    await state.set_state(CalcStates.waiting_for_amount)

    if direction == "stars_to_gram":
        title = "⭐ Stars → 💎 GRAM"
        hint = "Введи количество Stars (целое число):"
    else:
        title = "💎 GRAM → ⭐ Stars"
        hint = "Введи количество GRAM (можно с точкой):"

    text = f"🔄 <b>Калькулятор</b> · {title}\n━━━━━━━━━━━━━━━━━━\n{hint}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="calc_back")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except:
        await callback.message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "calc_back")
async def calc_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    lang = await get_user_lang(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Stars → 💎 GRAM", callback_data="calc_stars_to_gram")],
        [InlineKeyboardButton(text="💎 GRAM → ⭐ Stars", callback_data="calc_gram_to_stars")],
        [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])
    text = (
        "🔄 <b>Калькулятор</b>\n\n"
        "Выбери направление пересчёта:\n"
        "• <b>Stars → GRAM</b> — сколько получишь GRAM за звёзды\n"
        "• <b>GRAM → Stars</b> — сколько Stars нужно на GRAM\n\n"
        "💡 <i>Учитывается курс Stars и комиссия 20%</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except:
        await callback.message.answer(text, reply_markup=kb)

@dp.message(CalcStates.waiting_for_amount)
async def calc_result(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    if not message.text:
        await message.answer("❌ Введите число.", reply_markup=get_cancel_kb(lang))
        return
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
        data = await state.get_data()
        direction = data.get("calc_dir")
        star_rate = await get_user_star_rate(message.from_user.id)
        gram_price = await get_gram_price()

        if direction == "stars_to_gram":
            gram = (amount * 0.8 * star_rate) / gram_price
            usd = gram * gram_price
            text = (
                f"⭐ <b>Stars → GRAM</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⭐ Stars: <b>{amount:.0f}</b>\n"
                f"💎 GRAM: <b>{gram:.4f}</b>\n"
                f"🪙 USD: <b>${usd:.2f}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 Курс: 1⭐ = ${star_rate:.6f}\n"
                f"💡 Комиссия: 20%\n\n"
                f"<i>Расчёт приблизительный, зависит от курса GRAM</i>"
            )
        else:
            stars = (amount * gram_price) / (star_rate * 0.8)
            text = (
                f"💎 <b>GRAM → Stars</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💎 GRAM: <b>{amount:.2f}</b>\n"
                f"⭐ Stars: <b>{stars:.0f}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 Курс: 1⭐ = ${star_rate:.6f}\n"
                f"💡 Комиссия: 20%\n\n"
                f"<i>Расчёт приблизительный, зависит от курса GRAM</i>"
            )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Новый расчёт", callback_data="calc_back")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="back_to_main")]
        ])
        await message.answer(text, reply_markup=kb)
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
    try:
        await callback.message.delete()
    except: pass

@dp.callback_query(F.data == "open_reports")
async def open_reports_cb(callback: CallbackQuery, state: FSMContext):
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
        if val < 0:
            raise ValueError
        await save_user_royalty(message.from_user.id, val)
        await log_action(message.from_user.id, "", "set_royalty", f"{val:.2f} GRAM")
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
        if val <= 0:
            raise ValueError
        conn = await get_db()
        await conn.execute("INSERT OR REPLACE INTO profit_goals (user_id, goal_gram, created_at, notified) VALUES (?,?,datetime('now'),0)", (message.from_user.id, val))
        await conn.commit()
        await log_action(message.from_user.id, "", "set_goal", f"{val:.2f} GRAM")
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
        if rate <= 0 or rate >= 1:
            raise ValueError
        await save_user_star_rate(message.from_user.id, rate)
        await log_action(message.from_user.id, "", "set_star_rate", f"${rate:.6f}")
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
        await log_action(callback.from_user.id, "", "set_change_alert", "выкл")
        await callback.message.answer(MESSAGES[lang]["change_alert_off"])
    else:
        await state.set_state(SetChangeAlert.waiting_for_percent)
        await callback.message.answer(MESSAGES[lang]["enter_change_percent"], reply_markup=get_cancel_kb(lang))

@dp.message(SetChangeAlert.waiting_for_percent)
async def process_change_percent(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        percent = float(message.text.replace(",", "."))
        if percent <= 0 or percent > 100:
            raise ValueError
        await set_user_change_alert(message.from_user.id, True, percent)
        await log_action(message.from_user.id, "", "set_change_alert", f"вкл, {percent}%")
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
        if target <= 0:
            raise ValueError
        conn = await get_db()
        await conn.execute("INSERT OR REPLACE INTO gram_alerts (user_id, target_price, enabled, notified) VALUES (?,?,1,0)", (message.from_user.id, target))
        await conn.commit()
        await log_action(message.from_user.id, "", "set_gram_alert", f"${target:.2f}")
        await state.clear()
        await message.answer(MESSAGES[lang]["alert_set"].format(price=f"{target:.2f}"), reply_markup=get_main_kb(lang))
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

@dp.message(Command("reports"))
async def reports_menu(message: Message, state: FSMContext = None):
    if state:
        await state.clear()
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

# ---------- ТАЙМЕРЫ ----------
@dp.message(F.text.in_(["⏰ Таймеры", "⏰ Timers"]))
async def timers_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM timers WHERE user_id=? AND notified=0 ORDER BY event_time", (message.from_user.id,))
    timers = await cur.fetchall()

    text = "⏰ <b>Таймеры</b>\n"
    kb_rows = []

    if not timers:
        text += "━━━━━━━━━━━━━━━━━━\n📭 У тебя пока нет активных таймеров.\n\n💡 <i>Создай таймер, чтобы не пропустить минт, анлок или ре-листинг подарка.</i>"
    else:
        text += f"━━━━━━━━━━━━━━━━━━\nВсего: {len(timers)} · Активных: {len(timers)}\n\n"

        now_ts = time.time()
        best = timers[0]
        best_diff = best['event_time'] - now_ts
        for t in timers[1:]:
            diff = t['event_time'] - now_ts
            if diff < best_diff:
                best = t
                best_diff = diff

        best_link = best['nft_link'] or ""
        best_name = "NFT"
        if "t.me/nft/" in best_link:
            try:
                seg = best_link.split("/nft/")[1].split("/")[0]
                if "-" in seg:
                    best_name = seg.rsplit("-", 1)[0]
            except: pass

        if best_diff <= 0:
            near_str = "⚠️ <b>Сработает сегодня!</b>"
        else:
            days = int(best_diff // 86400)
            hours = int((best_diff % 86400) // 3600)
            if days > 0:
                near_str = f"🕐 Ближайшее: {_esc(best_name)} · через <b>{days} дн.</b>"
            else:
                near_str = f"🕐 Ближайшее: {_esc(best_name)} · через <b>{hours} ч.</b>"

        text += f"🟢 {near_str}\n━━━━━━━━━━━━━━━━━━\n\n"

        for t in timers:
            link = t['nft_link'] or ""
            ev_type = t['event_type']

            if ev_type == 'mint':
                emoji, label = "🎁", "Минтинг"
            elif ev_type == 'relist':
                emoji, label = "🔄", "Ре-листинг"
            else:
                emoji, label = "🔓", "Разблокировка"

            gift_name = "NFT"
            if "t.me/nft/" in link:
                try:
                    seg = link.split("/nft/")[1].split("/")[0]
                    if "-" in seg:
                        gift_name = seg.rsplit("-", 1)[0]
                except: pass

            time_left = t['event_time'] - time.time()
            if time_left <= 0:
                time_str = "⚠️ <b>Сработает сегодня!</b>"
            else:
                days = int(time_left // 86400)
                hours = int((time_left % 86400) // 3600)
                if days > 0:
                    time_str = f"🕐 Осталось: <b>{days} дн.</b>"
                else:
                    time_str = f"🕐 Осталось: <b>{hours} ч.</b>"

            ev_date = datetime.fromtimestamp(t['event_time']).strftime("%d.%m")
            text += (
                f"{emoji} <b>{_esc(gift_name)}</b> · {label}\n"
                f"   📅 {ev_date} · {time_str}\n"
                f"   🔗 <a href='{link}'>Открыть NFT</a>\n\n"
            )
            kb_rows.append([
                InlineKeyboardButton(text=f"🔗 {gift_name}", url=link),
                InlineKeyboardButton(text=f"🗑 Удалить", callback_data=f"timer_del_{t['id']}")
            ])

    kb_rows.append([InlineKeyboardButton(text="🔔 Проверить сейчас", callback_data="timer_check_now")])
    kb_rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="timer_add_menu")])
    kb_rows.append([InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

@dp.callback_query(F.data == "timer_add_menu")
async def timer_add_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Минтинг", callback_data="timer_mint")],
        [InlineKeyboardButton(text="🔓 Разблокировка", callback_data="timer_unlock")],
        [InlineKeyboardButton(text="🔄 Ре-листинг", callback_data="timer_relist")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="timer_back")]
    ])
    try:
        await callback.message.edit_text(
            "➕ <b>Новый таймер</b>\n\n"
            "Выбери тип события:\n"
            "• <b>Минтинг</b> — когда подарок станет доступен\n"
            "• <b>Разблокировка</b> — когда можно будет передать\n"
            "• <b>Ре-листинг</b> — когда можно будет продать снова\n\n"
            "💡 <i>Я напишу ровно в момент, когда действие станет доступно</i>",
            reply_markup=kb
        )
    except:
        await callback.message.answer("➕ <b>Новый таймер</b>\n\nВыбери тип:", reply_markup=kb)

@dp.callback_query(F.data == "timer_back")
async def timer_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await timers_menu(callback.message, state)

@dp.callback_query(F.data.startswith("timer_del_"))
async def timer_delete(callback: CallbackQuery):
    await callback.answer()
    timer_id = int(callback.data.replace("timer_del_", ""))
    conn = await get_db()
    await conn.execute("DELETE FROM timers WHERE id=? AND user_id=?", (timer_id, callback.from_user.id))
    await conn.commit()
    try:
        await callback.message.edit_text("✅ Таймер удалён.")
    except:
        await callback.message.answer("✅ Таймер удалён.")

@dp.callback_query(F.data == "timer_check_now")
async def timer_check_now(callback: CallbackQuery):
    await callback.answer("Проверяю таймеры…")
    user_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute(
        "SELECT id, event_type, nft_link, event_time FROM timers "
        "WHERE user_id=? AND notified=0 ORDER BY event_time",
        (user_id,)
    )
    timers = await cur.fetchall()
    if not timers:
        await callback.message.answer("📭 У тебя нет активных таймеров.")
        return

    now_ts = time.time()
    fired = 0
    upcoming = 0
    for t in timers:
        event_time = t["event_time"] or 0
        time_left = event_time - now_ts
        if time_left <= 0 and time_left > -86400:
            ev_type = t["event_type"]
            if ev_type == "mint":
                emoji, label, action = "🎁", "Минтинг", "Минт открылся — забирай!"
            elif ev_type == "relist":
                emoji, label, action = "🔄", "Ре-листинг", "Ре-листинг доступен — выставляй!"
            else:
                emoji, label, action = "🔓", "Разблокировка", "Разблокировка — можно передавать!"
            link = t["nft_link"] or ""
            gift_name = "NFT"
            if "t.me/nft/" in link:
                try:
                    seg = link.split("/nft/")[1].split("/")[0]
                    if "-" in seg:
                        gift_name = seg.rsplit("-", 1)[0]
                except: pass
            ev_date = datetime.fromtimestamp(event_time).strftime("%d.%m.%Y %H:%M")
            mins_passed = int(abs(time_left) // 60)
            text = (
                f"🚨 <b>ПОРА ДЕЙСТВОВАТЬ!</b>\n\n"
                f"{emoji} <b>{_esc(gift_name)}</b> · {label}\n"
                f"📅 {ev_date}\n"
                f"🕐 Наступило <b>{mins_passed} мин. назад</b>\n\n"
                f"👉 <b>{action}</b>\n"
            )
            if link:
                text += f"\n🔗 <a href='{link}'>Открыть NFT в Fragment</a>"
            try:
                await callback.message.answer(text)
                await conn.execute("UPDATE timers SET notified=1 WHERE id=?", (t["id"],))
                fired += 1
            except Exception as e:
                logger.warning(f"timer_check_now send: {e}")
        else:
            upcoming += 1
    await conn.commit()

    if fired == 0:
        await callback.message.answer(
            f"✅ Пока нечего напоминать — {upcoming} таймеров ещё впереди.\n"
            f"Как только событие наступит — пришлю сообщение."
        )

@dp.callback_query(F.data.in_(["timer_mint", "timer_unlock", "timer_relist"]))
async def timer_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    event_type = callback.data.replace("timer_", "")
    await state.update_data(event_type=event_type)
    await state.set_state(TimerAdd.waiting_for_nft_link)
    await callback.message.answer(MESSAGES[lang]["timer_enter_nft"], reply_markup=get_cancel_kb(lang))

@dp.message(TimerAdd.waiting_for_nft_link)
async def timer_nft_link_process(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    if not message.text:
        await message.answer("❌ Отправьте ссылку текстом.", reply_markup=get_cancel_kb(lang))
        return
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
        if days <= 0:
            raise ValueError
        data = await state.get_data()
        conn = await get_db()
        await conn.execute("INSERT INTO timers (user_id, event_type, nft_link, stars_amount, event_time, description) VALUES (?,?,?,?,?,?)", (message.from_user.id, data.get("event_type"), data.get("nft_link"), 0, time.time() + days * 86400, ""))
        await conn.commit()
        await log_action(message.from_user.id, "", "timer_add", f"{data.get('event_type')} через {days} дн.")
        await state.clear()
        await message.answer(MESSAGES[lang]["timer_saved"].format(days=days), reply_markup=get_main_kb(lang))
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

# ---------- ДОНАТЫ ----------
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
        if amount <= 0:
            raise ValueError
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
    await log_action(user_id, "", "donate", f"{amount} ⭐")
    lang = await get_user_lang(user_id)
    await message.answer(MESSAGES[lang]["donate_thanks"].format(amount=amount))
    if user_id != ADMIN_IDS[0]:
        try:
            await bot.send_message(ADMIN_IDS[0], MESSAGES["ru"]["donate_admin_notify"].format(user=f"ID {user_id}", amount=amount, date=datetime.now().strftime('%d.%m.%Y %H:%M')))
        except: pass

@dp.callback_query(F.data == "donate_top")
async def donate_top(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    conn = await get_db()
    cur = await conn.execute("SELECT d.user_id, SUM(d.amount) as total, u.username, u.first_name FROM donations d LEFT JOIN users u ON u.user_id = d.user_id GROUP BY d.user_id ORDER BY total DESC LIMIT 10")
    rows = await cur.fetchall()
    if not rows:
        return await callback.message.answer(MESSAGES[lang]["donate_top_empty"])
    text = MESSAGES[lang]["donate_top_title"] + "\n\n"
    for i, (uid, total, username, first_name) in enumerate(rows, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        name = f"@{username}" if username else (first_name or f"ID {uid}")
        text += f"{emoji} {name} — {total} ⭐\n"
    await callback.message.answer(text)

# ---------- РЕФЕРАЛЫ ----------
def get_inline_level(points: int):
    if points >= 400:
        return "🥇", "Легенда инлайнов", 0
    elif points >= 100:
        return "🥈", "Промоутер", 400 - points
    elif points >= 20:
        return "🥉", "Новичок", 100 - points
    else:
        return "🌱", "Начинающий", 20 - points

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
    else:
        text += "\n" + MESSAGES[lang]["referrals_empty"]
    text += "\n\n" + MESSAGES[lang]["referrals_points_per"]

    cur = await conn.execute("SELECT COUNT(*) FROM inline_stats WHERE user_id=?", (user_id,))
    inline_count = (await cur.fetchone())[0] or 0
    cur = await conn.execute("SELECT points FROM user_inline_points WHERE user_id=?", (user_id,))
    pts_row = await cur.fetchone()
    inline_points = pts_row[0] if pts_row else 0
    lvl_emoji, lvl_name, lvl_next = get_inline_level(inline_points)
    text += "\n\n📤 <b>Инлайн-режим</b>\n"
    text += f"{lvl_emoji} Уровень: <b>{lvl_name}</b>\n"
    text += f"• Отправок в чаты: <b>{inline_count}</b>\n"
    text += f"• Очков за инлайны: <b>{inline_points}</b>\n"
    if lvl_next > 0:
        text += f"• До следующего уровня: {lvl_next} очков\n"
    else:
        text += "• 🏆 Максимальный уровень!\n"
    text += "\n<i>За каждую отправку сделки в чат — +2 очка.</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=MESSAGES[lang]["referrals_share"], url=f"https://t.me/share/url?url={quote(ref_link)}")],
        [InlineKeyboardButton(text="📤 Поделиться моей сделкой", switch_inline_query="")],
        [InlineKeyboardButton(text="🏆 Топ инлайнов", callback_data="inline_top")],
        [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "inline_top")
async def inline_top(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT user_id, points, (SELECT COUNT(*) FROM inline_stats WHERE user_id=user_inline_points.user_id) as cnt FROM user_inline_points ORDER BY points DESC LIMIT 10")
    rows = await cur.fetchall()
    if not rows:
        await callback.message.answer("📤 Пока никто не делился сделками. Будь первым!")
        return
    text = "🏆 <b>Топ по инлайн-отправкам</b>\n\n"
    for i, (uid, pts, cnt) in enumerate(rows, 1):
        name = await get_user_display(conn, uid)
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        lvl_emoji, lvl_name, _ = get_inline_level(pts)
        text += f"{emoji} {name} — {pts} очков ({cnt} отправок) {lvl_emoji} {lvl_name}\n"
    await callback.message.answer(text)

@dp.callback_query(F.data == "goal_later")
async def goal_later(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except: pass

@dp.callback_query(F.data == "cancel_deal")
async def cancel_deal_universal(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    lang = await get_user_lang(callback.from_user.id)
    try:
        await callback.message.edit_text(MESSAGES[lang]["cancelled"])
    except:
        await callback.message.answer(MESSAGES[lang]["cancelled"])

# ---------- ИНЛАЙН-РЕЖИМ ----------
def inline_bot_keyboard(user_id: int = None):
    url = f"{BOT_URL}?start=ref_{user_id}" if user_id else BOT_URL
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Открыть бота", url=url)]])

def build_inline_html(deal: dict) -> str:
    lines = [f"{get_collection_emoji_html(deal)} <b>{_esc(deal.get('gift_name') or deal.get('category') or 'NFT')}</b> · Сделка #{deal['id']}"]
    attrs = format_gift_attributes({k: deal.get(k) for k in ("model", "model_rarity", "model_emoji_id", "backdrop", "backdrop_rarity", "backdrop_emoji_id", "symbol", "symbol_rarity", "symbol_emoji_id")})
    if attrs:
        lines.extend(["", attrs])
    lines.extend(["", f"{EMOJI_DIAMOND} {deal['buy_amount']} → {deal['sell_amount']} GRAM"])
    gp_buy, gp_sell = deal.get('gram_price_buy') or 0, deal.get('gram_price_sell') or deal.get('gram_price') or 0
    if gp_buy and gp_sell and gp_buy != gp_sell:
        lines.append(f"{EMOJI_DOLLAR} Курс: ${gp_buy:.4f} → ${gp_sell:.4f}")
    elif gp_buy or gp_sell:
        lines.append(f"{EMOJI_DOLLAR} Курс: ${gp_sell or gp_buy:.4f}")
    lines.extend([f"{EMOJI_MONEY} <b>{deal.get('profit_gram', 0):+.4f} GRAM</b>", f"{EMOJI_DOLLAR} <b>{deal.get('profit_usd', 0):+.2f}$</b>"])
    if deal.get('nft_link'):
        lines.extend(["", f'{EMOJI_LINK} <a href="{_esc(deal["nft_link"])}">Открыть NFT</a>'])
    return "\n".join(lines)

def build_stats_inline_html(user_id: int, username: str, first_name: str, stats: dict) -> str:
    lines = []
    display_name = f"@{username}" if username else (first_name or f"ID {user_id}")
    lines.append(f"📊 <b>Статистика {_esc(display_name)}</b>")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(f"📈 Сделок: <b>{stats['total']}</b>")
    lines.append(f"✅ В плюс: <b>{stats['wins']}</b> · ❌ В минус: <b>{stats['losses']}</b>")
    lines.append(f"🎯 Winrate: <b>{stats['winrate']:.1f}%</b>")
    lines.append("")
    lines.append(f"💰 <b>Прибыль:</b>")
    lines.append(f"💎 {stats['sum_g']:+.4f} GRAM")
    lines.append(f"🪙 {stats['sum_u']:+.2f}$")
    if stats.get("best") is not None:
        lines.append(f"🏆 Лучшая: {stats['best']:+.4f} GRAM")
    if stats.get("streak", 0) > 0:
        lines.append(f"🔥 Серия: {stats['streak']} дн.")
    if stats.get("goal"):
        lines.append(f"🎯 Цель: {stats['sum_g']:.2f} / {stats['goal']:.2f} GRAM")
    lines.append("")
    lines.append(f"🚀 Попробуй и ты → @Stars2ProfitBot")
    return "\n".join(lines)

async def _get_user_stats_for_inline(user_id: int) -> dict:
    conn = await get_db()
    cur = await conn.execute(
        "SELECT COUNT(*), SUM(profit_gram), SUM(profit_usd), "
        "SUM(CASE WHEN profit_gram > 0 THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN profit_gram < 0 THEN 1 ELSE 0 END), "
        "MAX(profit_gram) "
        "FROM sales WHERE user_id=?",
        (user_id,)
    )
    total, sum_g, sum_u, wins, losses, best = await cur.fetchone()
    total = total or 0
    wins = wins or 0
    losses = losses or 0
    winrate = (wins / total * 100) if total else 0
    cur_streak, _ = await get_streak(user_id)
    cur = await conn.execute("SELECT goal_gram FROM profit_goals WHERE user_id=?", (user_id,))
    g_row = await cur.fetchone()
    goal = g_row[0] if g_row else None
    return {
        "total": total, "sum_g": sum_g or 0, "sum_u": sum_u or 0,
        "wins": wins, "losses": losses, "winrate": winrate,
        "best": best, "streak": cur_streak, "goal": goal,
    }

@dp.inline_query()
async def inline_query(inline_query):
    uid = inline_query.from_user.id
    query = (inline_query.query or "").strip()
    conn = await get_db()

    if query.lower() in ("stats", "стата", "статистика") or query.lower().startswith("stats_"):
        target_id = uid
        if query.lower().startswith("stats_"):
            try:
                requested = int(query.split("_", 1)[1])
                if requested != uid:
                    requested = uid
                target_id = requested
            except:
                target_id = uid

        stats = await _get_user_stats_for_inline(target_id)
        if stats["total"] == 0:
            results = [InlineQueryResultArticle(
                id="no_stats", title="Нет сделок", description="Сначала добавь хотя бы одну сделку",
                input_message_content=InputTextMessageContent(message_text="📊 У меня пока нет сделок — начну прямо сейчас!", parse_mode="HTML"),
                reply_markup=inline_bot_keyboard(user_id=uid)
            )]
            try:
                await bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=True, switch_pm_text="Введи номер сделки (#123), коллекцию или «stats»", switch_pm_parameter="inline_help")
            except Exception as e:
                logger.error(f"Inline stats error: {e}")
            return

        cur = await conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (target_id,))
        u_row = await cur.fetchone()
        username = u_row["username"] if u_row else ""
        first_name = u_row["first_name"] if u_row else ""

        stats_html = build_stats_inline_html(target_id, username or "", first_name or "", stats)
        display_name = f"@{username}" if username else (first_name or f"ID {target_id}")

        results = [InlineQueryResultArticle(
            id=f"stats_{target_id}",
            title=f"📊 Статистика {display_name}",
            description=f"Сделок: {stats['total']} · Winrate: {stats['winrate']:.1f}% · {stats['sum_g']:+.2f} GRAM",
            input_message_content=InputTextMessageContent(message_text=stats_html, parse_mode="HTML"),
            reply_markup=inline_bot_keyboard(user_id=uid)
        )]
        try:
            await bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=True, switch_pm_text="Введи номер сделки (#123), коллекцию или «stats»", switch_pm_parameter="inline_help")
        except Exception as e:
            logger.error(f"Inline stats error: {e}")
        return

    if query.isdigit():
        cur = await conn.execute("SELECT * FROM sales WHERE id=? AND user_id=? ORDER BY id DESC", (int(query), uid))
    else:
        cur = await conn.execute("SELECT * FROM sales WHERE user_id=? AND (category LIKE ? OR gift_name LIKE ?) ORDER BY id DESC LIMIT 10", (uid, f"%{query}%", f"%{query}%"))
    deals = [dict(row) for row in await cur.fetchall()]
    results = []
    for d in deals:
        gift_name = d.get('gift_name') or d.get('category') or 'NFT'
        profit, profit_usd = d.get('profit_gram') or 0, d.get('profit_usd') or 0
        desc = f"💎 {d['buy_amount']} → {d['sell_amount']} GRAM | 💰 {profit:+.4f} GRAM ({profit_usd:+.2f}$)"
        caption_html = build_inline_html(d)
        thumb_id = d.get("thumb_file_id")
        nft_image = d.get("nft_image")
        nft_link = d.get("nft_link") or ""
        slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0] if "t.me/nft/" in nft_link else None

        is_placeholder = False
        if thumb_id and slug:
            cur2 = await conn.execute("SELECT is_placeholder FROM thumb_cache WHERE slug=?", (slug,))
            tc_row = await cur2.fetchone()
            if tc_row and tc_row[0]:
                is_placeholder = True

        if not thumb_id or not isinstance(thumb_id, str) or not thumb_id.startswith("AgAC") or is_placeholder:
            if slug:
                await conn.execute("UPDATE thumb_cache SET unavailable=0, retry_after=0 WHERE slug=?", (slug,))
                await conn.commit()
            thumb_id = await upload_thumb_to_telegram(nft_image, gift_name=gift_name, profit=profit, slug=slug)
            if thumb_id:
                await conn.execute("UPDATE sales SET thumb_file_id=? WHERE id=?", (thumb_id, d['id']))
                await conn.commit()
                if slug:
                    cur2 = await conn.execute("SELECT is_placeholder FROM thumb_cache WHERE slug=?", (slug,))
                    tc_row2 = await cur2.fetchone()
                    if tc_row2 and tc_row2[0]:
                        thumb_id = None
            else:
                thumb_id = None

        if thumb_id:
            results.append(InlineQueryResultCachedPhoto(id=f"sale_{d['id']}", photo_file_id=thumb_id, title=f"#{d['id']} {gift_name}", description=desc, caption=caption_html, parse_mode="HTML", reply_markup=inline_bot_keyboard(user_id=uid)))
        else:
            results.append(InlineQueryResultArticle(id=f"sale_{d['id']}", title=f"#{d['id']} {gift_name}", description=desc, thumbnail_url=nft_image, input_message_content=InputTextMessageContent(message_text=caption_html, parse_mode="HTML"), reply_markup=inline_bot_keyboard(user_id=uid)))

    if not results:
        results.append(InlineQueryResultArticle(
            id="no_deals", title="Ничего не найдено",
            description="Введи номер сделки (#123), коллекцию — или «stats» для статистики",
            input_message_content=InputTextMessageContent(message_text="🔍 Нет сделок. Попробуй ввести «stats» для статистики.", parse_mode="HTML"),
            reply_markup=inline_bot_keyboard(user_id=uid)
        ))

    try:
        await bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=True, switch_pm_text="Введи номер сделки (#123), коллекцию или «stats»", switch_pm_parameter="inline_help")
    except Exception as e:
        logger.error(f"Inline error: {e}")

@dp.chosen_inline_result()
async def chosen_inline_result_handler(chosen: ChosenInlineResult):
    if not chosen.inline_message_id or not chosen.result_id.startswith("sale_"):
        return
    try:
        deal_id = int(chosen.result_id.replace("sale_", ""))
    except ValueError:
        return
    uid = chosen.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM sales WHERE id=? AND user_id=?", (deal_id, uid))
    row = await cur.fetchone()
    if not row:
        return
    deal_dict = dict(row)
    try:
        await conn.execute("INSERT INTO inline_stats (user_id, username, first_name, deal_id) VALUES (?,?,?,?)", (uid, chosen.from_user.username or "", chosen.from_user.first_name or "", deal_id))
        await conn.execute("DELETE FROM inline_stats WHERE id NOT IN (SELECT id FROM inline_stats ORDER BY id DESC LIMIT 500)")
        await conn.execute("INSERT INTO user_inline_points (user_id, points, last_shared_at, updated_at) VALUES (?, 2, datetime('now'), datetime('now')) ON CONFLICT(user_id) DO UPDATE SET points = points + 2, last_shared_at = datetime('now'), updated_at = datetime('now')", (uid,))
        await conn.commit()
    except Exception as e:
        logger.debug(f"inline points error: {e}")
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
            await bot.edit_message_media(inline_message_id=chosen.inline_message_id, media=InputMediaAnimation(media=gif_id, caption=build_inline_html(deal_dict), parse_mode="HTML"), reply_markup=inline_bot_keyboard(user_id=uid))
        except Exception as e:
            logger.debug(f"Gif skip: {e}")

# ---------- АДМИН-ПАНЕЛЬ ----------
@dp.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext = None):
    if state:
        await state.clear()
    if not await is_admin(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён")
    await show_admin_panel(message)

async def show_admin_panel(message: Message):
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM users")
    total_users = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*), SUM(profit_gram), SUM(profit_usd) FROM sales")
    total_deals, total_g, total_u = await cur.fetchone()
    cur = await conn.execute("SELECT COUNT(*) FROM sales WHERE date = ?", (datetime.now().strftime("%d.%m.%Y"),))
    today_deals = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM admins")
    admin_count = (await cur.fetchone())[0]
    text = (
        "⚙️ <b>Админ-панель Stars2Profit</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"📊 Всего сделок: {total_deals or 0}\n"
        f"📅 Сделок сегодня: {today_deals}\n"
        f"💰 Общая прибыль: {total_g or 0:+.4f} GRAM (${total_u or 0:+.2f})\n"
        f"👑 Администраторов: {admin_count}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Расширенная статистика", callback_data="admin_ext_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="📈 Инлайн-статистика", callback_data="admin_inline_stats")],
        [InlineKeyboardButton(text="📋 Логи действий", callback_data="admin_logs")],
        [InlineKeyboardButton(text="🚨 Проверить ошибки", callback_data="admin_errors")],
        [InlineKeyboardButton(text="🎨 Настройки гифки", callback_data="admin_gif_settings")],
        [InlineKeyboardButton(text="🔄 Обновить картинки", callback_data="admin_refresh_thumbs")],
        [InlineKeyboardButton(text="🖼 Перезагрузить заглушки", callback_data="admin_reload_placeholders")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💾 Бэкап БД", callback_data="admin_backup")],
        [InlineKeyboardButton(text="⬅️ Закрыть", callback_data="close_admin")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "close_admin")
async def close_admin(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except: pass

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_back(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    try:
        await callback.message.delete()
    except: pass
    await show_admin_panel(callback.message)

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
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except: pass

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
    if not await is_admin(message.from_user.id):
        return
    data = await state.get_data()
    key = data.get("gif_set_key")
    if not key:
        return await state.clear()
    val = message.text.strip()
    conn = await get_db()
    try:
        if key == "preset":
            if val not in ("ultrafast", "veryfast", "fast", "medium", "slow"):
                raise ValueError
            await conn.execute("UPDATE gif_settings SET preset=? WHERE id=1", (val,))
        else:
            n = int(val)
            limits = {"width": (256, 2048), "height": (256, 2048), "fps": (15, 60), "skip": (1, 5), "crf": (18, 28)}
            lo, hi = limits[key]
            if not (lo <= n <= hi):
                raise ValueError
            await conn.execute(f"UPDATE gif_settings SET {key if key != 'skip' else 'frame_skip'}=? WHERE id=1", (n,))
        await conn.execute("DELETE FROM gif_cache")
        await conn.execute("UPDATE sales SET gif_file_id=NULL")
        await conn.commit()
        await log_action(message.from_user.id, "", "gif_settings", f"{key}={val}")
        await message.answer("✅ Сохранено. Кэш гифок очищен — новые гифки будут сгенерированы с новыми настройками.")
    except:
        await message.answer("❌ Некорректное значение.")
    finally:
        await state.clear()

@dp.callback_query(F.data == "admin_refresh_thumbs")
async def admin_refresh_thumbs(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("⏳ Начинаю обновление картинок для всех сделок. Это может занять время...")
    conn = await get_db()
    await conn.execute("DELETE FROM thumb_cache")
    await conn.execute("UPDATE sales SET thumb_file_id=NULL")
    await conn.execute("UPDATE pending_sales SET thumb_file_id=NULL")
    await conn.commit()
    cur = await conn.execute("SELECT id, nft_image, thumb_file_id, gift_name, profit_gram, nft_link FROM sales WHERE nft_image IS NOT NULL AND nft_image != ''")
    rows = await cur.fetchall()
    if not rows:
        await callback.message.edit_text("✅ Нет сделок с картинками для обновления.")
        return
    updated = 0
    for row in rows:
        gift_name = row["gift_name"] or "NFT"
        profit = row["profit_gram"] or 0
        nft_link = row["nft_link"] or ""
        slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0] if "t.me/nft/" in nft_link else None
        new_thumb = await upload_thumb_to_telegram(row["nft_image"], gift_name=gift_name, profit=profit, slug=slug)
        if new_thumb:
            await conn.execute("UPDATE sales SET thumb_file_id=? WHERE id=?", (new_thumb, row["id"]))
            await conn.commit()
            updated += 1
        await asyncio.sleep(0.5)
    await log_action(callback.from_user.id, "", "thumb_refresh", f"{updated}/{len(rows)}")
    await callback.message.edit_text(f"✅ Обновлено картинок: {updated} из {len(rows)}.")

@dp.callback_query(F.data == "admin_reload_placeholders")
async def admin_reload_placeholders(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("⏳ Ищу заглушки и пробую загрузить реальные картинки...")
    conn = await get_db()

    cur = await conn.execute(
        "SELECT s.id, s.nft_link, s.nft_image, s.gift_name, s.profit_gram, s.user_id, s.category, s.buy_amount, s.sell_amount, s.profit_usd, s.date "
        "FROM sales s "
        "JOIN thumb_cache tc ON tc.slug = SUBSTR(s.nft_link, INSTR(s.nft_link, '/nft/') + 5, "
        "    INSTR(SUBSTR(s.nft_link, INSTR(s.nft_link, '/nft/') + 5), '/') - 1) "
        "WHERE tc.is_placeholder = 1 AND s.nft_link IS NOT NULL AND s.nft_link != ''"
    )
    sales_rows = await cur.fetchall()

    cur = await conn.execute(
        "SELECT p.id, p.nft_link, p.nft_image, p.gift_name, p.user_id, p.category, p.buy_amount, p.date "
        "FROM pending_sales p "
        "JOIN thumb_cache tc ON tc.slug = SUBSTR(p.nft_link, INSTR(p.nft_link, '/nft/') + 5, "
        "    INSTR(SUBSTR(p.nft_link, INSTR(p.nft_link, '/nft/') + 5), '/') - 1) "
        "WHERE tc.is_placeholder = 1 AND p.nft_link IS NOT NULL AND p.nft_link != ''"
    )
    pending_rows = await cur.fetchall()

    if not sales_rows and not pending_rows:
        await callback.message.edit_text("✅ Заглушек не найдено — все картинки реальные.")
        return

    updated = 0
    for row in sales_rows:
        nft_link = row["nft_link"]
        slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0] if "t.me/nft/" in nft_link else None
        if not slug:
            continue
        await conn.execute("UPDATE thumb_cache SET unavailable=0, retry_after=0 WHERE slug=?", (slug,))
        await conn.commit()
        caption = None
        try:
            cur_uu = await conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (row["user_id"],))
            u = await cur_uu.fetchone()
            user_display = "—"
            if u:
                if u["username"]:
                    user_display = f"@{u['username']}"
                elif u["first_name"]:
                    user_display = _esc(u["first_name"])
            g_name = row["gift_name"] or row["category"] or "NFT"
            caption = (
                f"🔄 <b>Обновлена картинка сделки</b>\n\n"
                f"👤 {user_display}\n"
                f"🎁 <b>{_esc(g_name)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💎 {row['buy_amount']} → {row['sell_amount']} GRAM\n"
                f"{EMOJI_MONEY} <b>{row['profit_gram']:+.4f} GRAM</b> · {EMOJI_DOLLAR} <b>{row['profit_usd']:+.2f}$</b>\n"
                f"📅 {row['date']}\n"
                f"{EMOJI_LINK} <a href='{nft_link}'>Открыть NFT</a>"
            )
        except Exception as e:
            logger.debug(f"reload placeholders caption: {e}")
        thumb_id = await upload_thumb_to_telegram(row["nft_image"], gift_name=row["gift_name"] or "NFT", profit=row["profit_gram"] or 0, slug=slug, caption=caption)
        if thumb_id:
            await conn.execute("UPDATE sales SET thumb_file_id=? WHERE id=?", (thumb_id, row["id"]))
            await conn.commit()
            updated += 1
        await asyncio.sleep(1)

    for row in pending_rows:
        nft_link = row["nft_link"]
        slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0] if "t.me/nft/" in nft_link else None
        if not slug:
            continue
        await conn.execute("UPDATE thumb_cache SET unavailable=0, retry_after=0 WHERE slug=?", (slug,))
        await conn.commit()
        caption = None
        try:
            cur_uu = await conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (row["user_id"],))
            u = await cur_uu.fetchone()
            user_display = "—"
            if u:
                if u["username"]:
                    user_display = f"@{u['username']}"
                elif u["first_name"]:
                    user_display = _esc(u["first_name"])
            g_name = row["gift_name"] or row["category"] or "NFT"
            caption = (
                f"🔄 <b>Обновлена картинка pending</b>\n\n"
                f"👤 {user_display}\n"
                f"🎁 <b>{_esc(g_name)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📥 Покупка: <b>{row['buy_amount']} GRAM</b>\n"
                f"📅 {row['date']}\n"
                f"{EMOJI_LINK} <a href='{nft_link}'>Открыть NFT</a>"
            )
        except Exception as e:
            logger.debug(f"reload placeholders caption pending: {e}")
        thumb_id = await upload_thumb_to_telegram(row["nft_image"], gift_name=row["gift_name"] or "NFT", profit=0.0, slug=slug, caption=caption)
        if thumb_id:
            await conn.execute("UPDATE pending_sales SET thumb_file_id=? WHERE id=?", (thumb_id, row["id"]))
            await conn.commit()
            updated += 1
        await asyncio.sleep(1)

    total = len(sales_rows) + len(pending_rows)
    await log_action(callback.from_user.id, "", "thumb_refresh", f"placeholders: {updated}/{total}")
    await callback.message.edit_text(f"✅ Обновлено: {updated} из {total} (заглушки → реальные картинки).")

@dp.callback_query(F.data == "admin_ext_stats")
async def admin_ext_stats(callback: CallbackQuery):
    await callback.answer()
    await show_extended_stats(callback.message)

async def show_extended_stats(message: Message):
    conn = await get_db()
    now = datetime.now()
    today = now.strftime("%d.%m.%Y")
    cur = await conn.execute("SELECT COUNT(*) FROM users")
    total_users = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM users WHERE joined_date >= ?", (today,))
    new_today = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(DISTINCT user_id) FROM sales WHERE date = ?", (today,))
    active_today = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*), AVG(profit_gram), AVG(buy_amount) FROM sales")
    total_deals, avg_profit, avg_check = await cur.fetchone()
    cur = await conn.execute("SELECT COUNT(*) FROM sales WHERE date = ?", (today,))
    today_deals = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM sales WHERE created_at >= datetime(?, 'unixepoch')", (time.time() - 7*86400,))
    week_deals = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT SUM(profit_gram), SUM(profit_usd) FROM sales")
    total_g, total_u = await cur.fetchone()
    cur = await conn.execute("SELECT date, SUM(profit_gram) as s FROM sales GROUP BY date ORDER BY s DESC LIMIT 1")
    best_row = await cur.fetchone()
    cur = await conn.execute("SELECT category, COUNT(*) FROM sales GROUP BY category ORDER BY COUNT(*) DESC LIMIT 5")
    top_cols = await cur.fetchall()
    cur = await conn.execute("SELECT user_id, COUNT(*) FROM sales GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 5")
    top_users = await cur.fetchall()
    cur = await conn.execute("SELECT COUNT(DISTINCT user_id), COUNT(*) FROM inline_stats")
    inl_row = await cur.fetchone()

    text = "📊 <b>Расширенная статистика</b>\n\n"
    text += "━━━ 👥 ПОЛЬЗОВАТЕЛИ ━━━\n"
    text += f"• Всего: {total_users}\n• Новых сегодня: {new_today}\n• Активных сегодня: {active_today}\n\n"
    text += "━━━ 📈 СДЕЛКИ ━━━\n"
    text += f"• Всего: {total_deals or 0}\n• Сегодня: {today_deals}\n• За неделю: {week_deals}\n• Средняя прибыль: {avg_profit or 0:+.4f} GRAM\n• Средний чек: {avg_check or 0:.2f} GRAM\n\n"
    text += "━━━ 💰 ПРИБЫЛЬ ━━━\n"
    text += f"• TON: {total_g or 0:+.4f} GRAM\n• USD: ${total_u or 0:+.2f}\n"
    if best_row:
        text += f"• Лучший день: {_esc(best_row[0])} ({best_row[1]:+.2f} GRAM)\n"
    text += "\n━━━ 📁 ТОП-5 КОЛЛЕКЦИЙ ━━━\n"
    for i, (cat, cnt) in enumerate(top_cols, 1):
        text += f"{i}. {_esc(cat)} — {cnt} сделок\n"
    text += "\n━━━ 👑 ТОП-5 ЮЗЕРОВ ━━━\n"
    for i, (uid, cnt) in enumerate(top_users, 1):
        name = await get_user_display(conn, uid)
        text += f"{i}. {name} — {cnt} сделок\n"
    if inl_row:
        text += f"\n━━━ 📱 ИНЛАЙН-РЕЖИМ ━━━\n• Уникальных: {inl_row[0]}\n• Всего отправок: {inl_row[1]}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 По дням", callback_data="adm_stats_days"), InlineKeyboardButton(text="📈 По часам", callback_data="adm_stats_hours")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "adm_stats_days")
async def adm_stats_days(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT date, COUNT(*), SUM(profit_gram) FROM sales GROUP BY date ORDER BY id DESC LIMIT 7")
    rows = await cur.fetchall()
    text = "📅 <b>Статистика по дням</b>\n\n"
    for r in reversed(rows):
        text += f"• {_esc(r[0])}: {r[1]} сделок, {r[2] or 0:+.4f} GRAM\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_ext_stats")]])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except: pass

@dp.callback_query(F.data == "adm_stats_hours")
async def adm_stats_hours(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT CAST(strftime('%H', created_at) AS INTEGER) AS h, COUNT(*) FROM sales GROUP BY h ORDER BY h")
    rows = await cur.fetchall()
    text = "📈 <b>Статистика по часам</b>\n\n"
    for r in rows:
        text += f"• {r[0]:02d}:00 — {r[1]} сделок\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_ext_stats")]])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except: pass

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT user_id, username, first_name FROM users ORDER BY joined_date DESC LIMIT 20")
    text = "👥 <b>Последние пользователи:</b>\n\n" + "\n".join([f"• <code>{r[0]}</code> {r[2] or ''} (@{r[1] or '—'})" for r in await cur.fetchall()])
    await callback.message.answer(text)

@dp.callback_query(F.data == "admin_inline_stats")
async def admin_inline_stats(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(DISTINCT user_id), COUNT(*) FROM inline_stats")
    users, total = await cur.fetchone()
    if not total:
        await callback.message.answer("📈 Инлайн-режимом пока никто не пользовался.")
        return
    cur = await conn.execute("SELECT user_id, COUNT(*) FROM inline_stats GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 10")
    top = await cur.fetchall()
    text = "📈 <b>Инлайн-статистика</b>\n\n" + f"👥 Уникальных пользователей: {users}\n" + f"📤 Всего отправок: {total}\n\n🏆 <b>Топ-10 активных:</b>\n"
    for i, (uid, cnt) in enumerate(top, 1):
        name = await get_user_display(conn, uid)
        cur2 = await conn.execute("SELECT points FROM user_inline_points WHERE user_id=?", (uid,))
        pr = await cur2.fetchone()
        pts = pr[0] if pr else 0
        lvl_emoji, lvl_name, _ = get_inline_level(pts)
        text += f"{i}. {name} — {cnt} отправок ({pts} очков {lvl_emoji})\n"
    await callback.message.answer(text)

@dp.callback_query(F.data == "admin_logs")
async def admin_logs(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT user_id, username, action, details, timestamp FROM action_logs ORDER BY id DESC LIMIT 20")
    rows = await cur.fetchall()
    if not rows:
        text = "📋 <b>Логов пока нет.</b>"
    else:
        lines = ["📋 <b>Последние действия:</b>\n"]
        for uid, uname, action, details, ts in rows:
            name = await get_user_display(conn, uid) if uid else "Система"
            label = ACTION_LABELS.get(action, action)
            time_str = str(ts)[11:16] if ts else "--:--"
            line = f"🕐 <b>{time_str}</b> · {name} — {label}"
            if details:
                line += f"\n     └ <i>{_esc(str(details)[:90])}</i>"
            lines.append(line)
        text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except: pass

@dp.callback_query(F.data == "admin_errors")
async def admin_errors(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT error_type, details, timestamp FROM error_logs ORDER BY id DESC LIMIT 5")
    rows = await cur.fetchall()
    text = "🚨 <b>Последние ошибки:</b>\n\n" + "\n".join([f"⚠️ {r[0]} — {str(r[2])[:16]}\n{r[1][:100]}" for r in rows]) if rows else "✅ Ошибок нет."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except: pass

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.message.answer("📢 Введите текст для рассылки:", reply_markup=get_cancel_kb(await get_user_lang(callback.from_user.id)))

@dp.message(BroadcastState.waiting_for_message)
async def do_broadcast(message: Message, state: FSMContext):
    conn = await get_db()
    cur = await conn.execute("SELECT user_id FROM users")
    users = [row[0] async for row in cur]
    success = 0
    for uid in users:
        try:
            await bot.send_message(uid, message.text)
            success += 1
            await asyncio.sleep(0.05)
        except: pass
    await state.clear()
    await log_action(message.from_user.id, "", "broadcast", f"{success}/{len(users)}")
    await message.answer(f"✅ Рассылка завершена: {success}/{len(users)}")

@dp.callback_query(F.data == "admin_backup")
async def admin_backup(callback: CallbackQuery):
    await callback.answer()
    try:
        await create_and_send_backup(callback.from_user.id)
        await log_action(callback.from_user.id, "", "backup", "")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка бэкапа: {e}")

async def create_and_send_backup(admin_id: int):
    date_str = datetime.now().strftime("%Y-%m-%d")
    zip_filename = f"backup_{date_str}.zip"
    files_to_backup = ["sales.db", "sales.db-wal", "sales.db-shm"]
    existing = [f for f in files_to_backup if Path(f).exists()]
    if not existing:
        return
    with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in existing:
            zf.write(f, f)
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM users")
    users_count = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM sales")
    deals_count = (await cur.fetchone())[0]
    size_kb = Path(zip_filename).stat().st_size / 1024
    caption = f"💾 <b>Бэкап БД</b>\n\n📅 Дата: {date_str}\n📊 Размер: {size_kb:.1f} КБ\n• Пользователей: {users_count}\n• Сделок: {deals_count}\n• Файлов: {len(existing)}"
    try:
        await bot.send_document(admin_id, FSInputFile(zip_filename), caption=caption)
    except: pass
    try:
        Path(zip_filename).unlink()
    except: pass

  # ---------- ДИАГНОСТИКА БД ----------
@dp.message(Command("dbcheck"))
async def dbcheck_cmd(message: Message):
    if not await is_admin(message.from_user.id):
        return await message.answer("⛔ Только для админа")
    conn = await get_db()
    lines = ["🔍 <b>Диагностика БД</b>\n"]

    cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in await cur.fetchall()]
    lines.append(f"📋 Таблиц: {len(tables)}")
    lines.append(", ".join(tables))

    for tbl in ["sales", "pending_sales", "thumb_cache", "gif_cache", "daily_profit", "user_achievements", "timers"]:
        try:
            cur = await conn.execute(f"PRAGMA table_info({tbl})")
            cols = [r[1] for r in await cur.fetchall()]
            if cols:
                lines.append(f"\n📁 <b>{tbl}</b> ({len(cols)} колонок):")
                lines.append(f"  {', '.join(cols[:10])}{'…' if len(cols) > 10 else ''}")
            else:
                lines.append(f"\n❌ <b>{tbl}</b> — НЕТ ТАБЛИЦЫ")
        except Exception as e:
            lines.append(f"\n❌ <b>{tbl}</b> — ошибка: {e}")

    lines.append("\n📊 <b>Счётчики:</b>")
    for tbl in ["sales", "pending_sales", "thumb_cache", "gif_cache", "timers", "daily_profit"]:
        try:
            cur = await conn.execute(f"SELECT COUNT(*) FROM {tbl}")
            n = (await cur.fetchone())[0]
            lines.append(f"  {tbl}: {n}")
        except:
            lines.append(f"  {tbl}: ❌")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3900] + "\n… (обрезано)"
    await message.answer(text)

# ---------- ПРОВЕРКА ТАЙМЕРОВ ----------
async def timer_checker():
    """
    Каждую минуту проверяет таймеры и шлёт напоминание ТОЛЬКО когда событие наступило.
    - mint/relist/unlock: сообщение в момент event_time
    - если событие прошло больше 24 часов — помечаем как notified и не шлём
    """
    while True:
        try:
            conn = await get_db()
            now_ts = time.time()
            cur = await conn.execute(
                "SELECT id, user_id, event_type, nft_link, stars_amount, event_time, description "
                "FROM timers WHERE notified=0 ORDER BY event_time"
            )
            timers = await cur.fetchall()
            for t in timers:
                event_time = t["event_time"] or 0
                time_left = event_time - now_ts
                if time_left > 0:
                    continue
                if time_left < -86400:
                    await conn.execute("UPDATE timers SET notified=1 WHERE id=?", (t["id"],))
                    await conn.commit()
                    continue

                ev_type = t["event_type"]
                if ev_type == "mint":
                    emoji, label, action = "🎁", "Минтинг", "Минт открылся — забирай!"
                elif ev_type == "relist":
                    emoji, label, action = "🔄", "Ре-листинг", "Ре-листинг доступен — выставляй!"
                else:
                    emoji, label, action = "🔓", "Разблокировка", "Разблокировка — можно передавать!"

                link = t["nft_link"] or ""
                gift_name = "NFT"
                if "t.me/nft/" in link:
                    try:
                        seg = link.split("/nft/")[1].split("/")[0]
                        if "-" in seg:
                            gift_name = seg.rsplit("-", 1)[0]
                    except: pass

                ev_date = datetime.fromtimestamp(event_time).strftime("%d.%m.%Y %H:%M")
                mins_passed = int(abs(time_left) // 60)

                text = (
                    f"🚨 <b>ПОРА ДЕЙСТВОВАТЬ!</b>\n\n"
                    f"{emoji} <b>{_esc(gift_name)}</b> · {label}\n"
                    f"📅 {ev_date}\n"
                    f"🕐 Наступило <b>{mins_passed} мин. назад</b>\n\n"
                    f"👉 <b>{action}</b>\n"
                )
                if link:
                    text += f"\n🔗 <a href='{link}'>Открыть NFT в Fragment</a>"
                if t["description"]:
                    text += f"\n\n<i>{_esc(t['description'])}</i>"

                kb_rows = []
                if link:
                    kb_rows.append([InlineKeyboardButton(text="🔗 Открыть NFT", url=link)])
                kb_rows.append([InlineKeyboardButton(text="✅ Готово — удалить таймер", callback_data=f"timer_del_{t['id']}")])
                kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

                try:
                    await bot.send_message(t["user_id"], text, reply_markup=kb, disable_notification=False)
                    logger.info(f"[TIMER] Событие наступило: user_id={t['user_id']} timer #{t['id']} ({ev_type})")
                except Exception as e:
                    logger.warning(f"[TIMER] Не удалось отправить user_id={t['user_id']}: {e}")

                await conn.execute("UPDATE timers SET notified=1 WHERE id=?", (t["id"],))
                await conn.commit()
        except Exception as e:
            logger.error(f"timer_checker error: {e}")
        await asyncio.sleep(60)

# ---------- ФОНОВЫЕ ЗАДАЧИ ----------
async def backfill_thumbs():
    """
    Каждые 24 часа:
    1) Берёт сделки, где thumb_file_id пустой.
    2) Берёт сделки, где thumb — заглушка (thumb_cache.is_placeholder = 1).
    Пробует загрузить реальную картинку. Учитывает retry_after.
    """
    while True:
        try:
            conn = await get_db()

            cur = await conn.execute(
                "SELECT id, nft_image, thumb_file_id, gift_name, profit_gram, nft_link "
                "FROM sales "
                "WHERE (thumb_file_id IS NULL OR thumb_file_id = '') "
                "AND nft_link IS NOT NULL AND nft_link != '' "
                "ORDER BY id DESC LIMIT 20"
            )
            empty_rows = await cur.fetchall()

            cur = await conn.execute(
                "SELECT s.id, s.nft_image, s.thumb_file_id, s.gift_name, s.profit_gram, s.nft_link "
                "FROM sales s "
                "JOIN thumb_cache tc ON tc.slug = SUBSTR(s.nft_link, INSTR(s.nft_link, '/nft/') + 5, "
                "    INSTR(SUBSTR(s.nft_link, INSTR(s.nft_link, '/nft/') + 5), '/') - 1) "
                "WHERE tc.is_placeholder = 1 "
                "AND (tc.retry_after IS NULL OR tc.retry_after = 0 OR tc.retry_after <= ?) "
                "ORDER BY s.id DESC LIMIT 20",
                (time.time(),)
            )
            placeholder_rows = await cur.fetchall()

            all_rows = list(empty_rows) + list(placeholder_rows)
            if not all_rows:
                logger.info("[BACKFILL-THUMB] Нет пустых превью и заглушек — пропуск")
                await asyncio.sleep(86400)
                continue

            updated = 0
            for row in all_rows:
                nft_link = row["nft_link"] or ""
                slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0] if "t.me/nft/" in nft_link else None

                if slug:
                    await conn.execute("UPDATE thumb_cache SET unavailable=0, retry_after=0 WHERE slug=?", (slug,))
                    await conn.commit()

                caption = None
                try:
                    cur_u = await conn.execute(
                        "SELECT user_id, category, gift_name, buy_amount, sell_amount, profit_gram, profit_usd, date "
                        "FROM sales WHERE id=?",
                        (row["id"],)
                    )
                    info = await cur_u.fetchone()
                    if info:
                        cur_uu = await conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (info["user_id"],))
                        u = await cur_uu.fetchone()
                        user_display = "—"
                        if u:
                            if u["username"]:
                                user_display = f"@{u['username']}"
                            elif u["first_name"]:
                                user_display = _esc(u["first_name"])
                        g_name = info["gift_name"] or info["category"] or "NFT"
                        caption = (
                            f"🔄 <b>Обновлена картинка сделки</b>\n\n"
                            f"👤 {user_display}\n"
                            f"🎁 <b>{_esc(g_name)}</b>\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"💎 {info['buy_amount']} → {info['sell_amount']} GRAM\n"
                            f"{EMOJI_MONEY} <b>{info['profit_gram']:+.4f} GRAM</b> · {EMOJI_DOLLAR} <b>{info['profit_usd']:+.2f}$</b>\n"
                            f"📅 {info['date']}\n"
                        )
                        if nft_link:
                            caption += f"{EMOJI_LINK} <a href='{nft_link}'>Открыть NFT</a>"
                except Exception as e:
                    logger.debug(f"[BACKFILL-THUMB] caption: {e}")

                gift_name = row["gift_name"] or "NFT"
                profit = row["profit_gram"] or 0
                thumb_id = await upload_thumb_to_telegram(
                    row["nft_image"], gift_name=gift_name, profit=profit, slug=slug, caption=caption
                )
                if thumb_id:
                    await conn.execute("UPDATE sales SET thumb_file_id=? WHERE id=?", (thumb_id, row["id"]))
                    await conn.commit()
                    updated += 1
                    logger.info(f"[BACKFILL-THUMB] #{row['id']}: обновлено")
                await asyncio.sleep(2)

            if updated:
                logger.info(f"[BACKFILL-THUMB] Обновлено: {updated} из {len(all_rows)}")
        except Exception as e:
            logger.warning(f"backfill_thumbs error: {e}")

        await asyncio.sleep(86400)

async def backfill_pending_thumbs():
    """Каждые 24 часа: pending с пустым thumb или заглушкой — пробуем загрузить реальную."""
    while True:
        try:
            conn = await get_db()
            cur = await conn.execute(
                "SELECT id, nft_image, thumb_file_id, gift_name, nft_link "
                "FROM pending_sales "
                "WHERE (thumb_file_id IS NULL OR thumb_file_id = '') "
                "AND nft_link IS NOT NULL AND nft_link != '' "
                "ORDER BY id DESC LIMIT 20"
            )
            empty_rows = await cur.fetchall()

            cur = await conn.execute(
                "SELECT p.id, p.nft_image, p.thumb_file_id, p.gift_name, p.nft_link "
                "FROM pending_sales p "
                "JOIN thumb_cache tc ON tc.slug = SUBSTR(p.nft_link, INSTR(p.nft_link, '/nft/') + 5, "
                "    INSTR(SUBSTR(p.nft_link, INSTR(p.nft_link, '/nft/') + 5), '/') - 1) "
                "WHERE tc.is_placeholder = 1 "
                "AND (tc.retry_after IS NULL OR tc.retry_after = 0 OR tc.retry_after <= ?) "
                "ORDER BY p.id DESC LIMIT 20",
                (time.time(),)
            )
            placeholder_rows = await cur.fetchall()

            all_rows = list(empty_rows) + list(placeholder_rows)
            if not all_rows:
                logger.info("[BACKFILL-PEND-THUMB] Нет пустых превью и заглушек — пропуск")
                await asyncio.sleep(86400)
                continue

            updated = 0
            for row in all_rows:
                nft_link = row["nft_link"] or ""
                slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0] if "t.me/nft/" in nft_link else None
                if slug:
                    await conn.execute("UPDATE thumb_cache SET unavailable=0, retry_after=0 WHERE slug=?", (slug,))
                    await conn.commit()

                caption = None
                try:
                    cur_u = await conn.execute(
                        "SELECT user_id, category, gift_name, buy_amount, date FROM pending_sales WHERE id=?",
                        (row["id"],)
                    )
                    info = await cur_u.fetchone()
                    if info:
                        cur_uu = await conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (info["user_id"],))
                        u = await cur_uu.fetchone()
                        user_display = "—"
                        if u:
                            if u["username"]:
                                user_display = f"@{u['username']}"
                            elif u["first_name"]:
                                user_display = _esc(u["first_name"])
                        g_name = info["gift_name"] or info["category"] or "NFT"
                        caption = (
                            f"🔄 <b>Обновлена картинка pending</b>\n\n"
                            f"👤 {user_display}\n"
                            f"🎁 <b>{_esc(g_name)}</b>\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"📥 Покупка: <b>{info['buy_amount']} GRAM</b>\n"
                            f"📅 {info['date']}\n"
                        )
                        if nft_link:
                            caption += f"{EMOJI_LINK} <a href='{nft_link}'>Открыть NFT</a>"
                except Exception as e:
                    logger.debug(f"[BACKFILL-PEND-THUMB] caption: {e}")

                gift_name = row["gift_name"] or "NFT"
                thumb_id = await upload_thumb_to_telegram(
                    row["nft_image"], gift_name=gift_name, profit=0.0, slug=slug, caption=caption
                )
                if thumb_id:
                    await conn.execute("UPDATE pending_sales SET thumb_file_id=? WHERE id=?", (thumb_id, row["id"]))
                    await conn.commit()
                    updated += 1
                    logger.info(f"[BACKFILL-PEND-THUMB] #{row['id']}: обновлено")
                await asyncio.sleep(2)

            if updated:
                logger.info(f"[BACKFILL-PEND-THUMB] Обновлено: {updated} из {len(all_rows)}")
        except Exception as e:
            logger.warning(f"backfill_pending_thumbs error: {e}")

        await asyncio.sleep(86400)

async def backfill_gifs():
    """
    Каждые 10 минут:
    - Ищет сделки, где gif_file_id пустой.
    - И сделки, где гифка-заглушка (unavailable=1), но прошло >6 часов.
    - Пробует ensure_gif_rendered (Fragment → api.changes.tg).
    - Если гифка появилась — обновляет gif_file_id у ВСЕХ сделок с этим slug
      и шлёт пользователю уведомление «гифка готова».
    """
    while True:
        try:
            conn = await get_db()

            cur = await conn.execute(
                "SELECT DISTINCT nft_link FROM sales "
                "WHERE nft_link IS NOT NULL AND nft_link != '' "
                "AND (gif_file_id IS NULL OR gif_file_id = '') "
                "LIMIT 10"
            )
            empty_links = [r[0] for r in await cur.fetchall()]

            cur = await conn.execute(
                "SELECT DISTINCT s.nft_link "
                "FROM sales s "
                "JOIN gif_cache gc ON gc.slug = SUBSTR(s.nft_link, INSTR(s.nft_link, '/nft/') + 5, "
                "    INSTR(SUBSTR(s.nft_link, INSTR(s.nft_link, '/nft/') + 5), '/') - 1) "
                "WHERE gc.unavailable = 1 "
                "AND (s.gif_file_id IS NULL OR s.gif_file_id = '') "
                "AND (gc.retry_after IS NULL OR gc.retry_after = 0 OR gc.retry_after <= ?) "
                "LIMIT 10",
                (time.time() + 6 * 3600,)
            )
            stale_links = [r[0] for r in await cur.fetchall()]

            all_links = list({*empty_links, *stale_links})
            if not all_links:
                await asyncio.sleep(600)
                continue

            updated_count = 0
            for nft_link in all_links:
                if "t.me/nft/" not in nft_link:
                    continue
                slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0]

                try:
                    await conn.execute("UPDATE gif_cache SET unavailable=0, retry_after=0 WHERE slug=?", (slug,))
                    await conn.commit()
                except:
                    pass

                gif_id = None
                try:
                    gif_id = await ensure_gif_rendered(slug, nft_link)
                except Exception as e:
                    logger.warning(f"[BACKFILL-GIF] {slug}: {e}")

                if not gif_id:
                    continue

                cur = await conn.execute(
                    "SELECT id, user_id, buy_amount, sell_amount, profit_gram, profit_usd, gift_name, category, date "
                    "FROM sales WHERE nft_link=? AND (gif_file_id IS NULL OR gif_file_id = '')",
                    (nft_link,)
                )
                deals = await cur.fetchall()
                if not deals:
                    continue

                await conn.execute("UPDATE sales SET gif_file_id=? WHERE nft_link=?", (gif_id, nft_link))
                await conn.commit()
                updated_count += len(deals)
                logger.info(f"[BACKFILL-GIF] {slug}: обновлено {len(deals)} сделок")

                for d in deals:
                    try:
                        g_name = d["gift_name"] or d["category"] or "NFT"
                        text = (
                            f"🎬 <b>Гифка к сделке готова!</b>\n\n"
                            f"🎁 <b>{_esc(g_name)}</b> · сделка <b>#{d['id']}</b>\n"
                            f"{EMOJI_DIAMOND} {d['buy_amount']} → {d['sell_amount']} GRAM\n"
                            f"{EMOJI_MONEY} <b>{(d['profit_gram'] or 0):+.4f} GRAM</b> · {EMOJI_DOLLAR} <b>{(d['profit_usd'] or 0):+.2f}$</b>\n\n"
                            f"📤 Поделись ею в чате — пусть другие увидят твой профит."
                        )
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="📤 Поделиться сделкой", switch_inline_query=str(d["id"]))],
                            [InlineKeyboardButton(text="📋 История", callback_data="open_history")],
                        ])
                        await bot.send_animation(chat_id=d["user_id"], animation=gif_id, caption=text, reply_markup=kb)
                    except Exception as e:
                        logger.debug(f"[BACKFILL-GIF] notify user {d['user_id']}: {e}")
                    await asyncio.sleep(0.5)

                await asyncio.sleep(2)

            if updated_count:
                logger.info(f"[BACKFILL-GIF] Всего обновлено сделок: {updated_count}")
        except Exception as e:
            logger.warning(f"backfill_gifs error: {e}")

        await asyncio.sleep(600)

async def backfill_pending_emojis():
    while True:
        try:
            conn = await get_db()
            cur = await conn.execute("SELECT id, nft_link, collection_emoji_id, model_emoji_id FROM pending_sales WHERE nft_link IS NOT NULL AND nft_link != '' AND (collection_emoji_id IS NULL OR model_emoji_id IS NULL OR backdrop_emoji_id IS NULL OR symbol_emoji_id IS NULL) LIMIT 5")
            rows = await cur.fetchall()
            for row in rows:
                nft_data = await parse_nft_link(row["nft_link"])
                if nft_data:
                    await conn.execute("UPDATE pending_sales SET collection_emoji_id=COALESCE(collection_emoji_id, ?), model_emoji_id=COALESCE(model_emoji_id, ?), backdrop_emoji_id=COALESCE(backdrop_emoji_id, ?), symbol_emoji_id=COALESCE(symbol_emoji_id, ?) WHERE id=?", (nft_data.get("collection_emoji_id"), nft_data.get("model_emoji_id"), nft_data.get("backdrop_emoji_id"), nft_data.get("symbol_emoji_id"), row["id"]))
                    await conn.commit()
                await asyncio.sleep(1.5)
        except: pass
        await asyncio.sleep(120)

async def daily_backup_task():
    last_backup_ts = 0
    INTERVAL = 6 * 3600
    while True:
        try:
            now_ts = time.time()
            if now_ts - last_backup_ts >= INTERVAL:
                main_admin = ADMIN_IDS[0]
                try:
                    await create_and_send_backup(main_admin)
                    last_backup_ts = now_ts
                    logger.info(f"✅ Бэкап отправлен (каждые 6 часов)")
                except Exception as e:
                    logger.error(f"Backup error: {e}")
        except: pass
        await asyncio.sleep(300)

async def send_startup_errors():
    try:
        conn = await get_db()
        cur = await conn.execute("SELECT COUNT(*) FROM error_logs WHERE timestamp >= datetime(?, 'unixepoch')", (time.time() - 86400,))
        count = (await cur.fetchone())[0]
        if count > 0:
            await bot.send_message(ADMIN_IDS[0], f"🚨 <b>Ошибки при запуске</b>\nНайдено: {count} ошибок за 24ч.\nОткрой админку.")
    except: pass

# ---------- ЗАПУСК ----------
@dp.message(F.text)
async def debug_all_messages(message: Message):
    logger.info(f"[DEBUG] Пришло сообщение: '{message.text}' (длина: {len(message.text)})")

async def main():
    global browser_instance
    logger.info("🚀 Бот запускается...")
    await init_db()
    try:
        browser_instance = await pyppeteer.launch(
            headless=True,
            executablePath='/usr/bin/chromium',
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        logger.info("Chromium запущен.")
    except Exception as e:
        logger.error(f"Chromium error: {e}")
        browser_instance = None
    asyncio.create_task(backfill_thumbs())
    asyncio.create_task(backfill_pending_thumbs())
    asyncio.create_task(backfill_gifs())
    asyncio.create_task(backfill_pending_emojis())
    asyncio.create_task(daily_backup_task())
    asyncio.create_task(timer_checker())
    await send_startup_errors()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except: pass
    logger.info("🤖 Бот запущен!")
    try:
        await dp.start_polling(bot)
    finally:
        if browser_instance:
            try:
                await browser_instance.close()
            except: pass
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
