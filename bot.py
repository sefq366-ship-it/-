# ============================================================
# bot.py — Gram2Profit v1.2
# Премиум-эмодзи, два курса GRAM, парсинг 3 источников,
# таймеры с pending_id, гифки в инлайне, админ-панель гиф.
# ============================================================

# ===== АВТОУСТАНОВКА БИБЛИОТЕК =====
import subprocess
import sys
import importlib

REQUIRED_LIBS = {
    "aiogram": "aiogram",
    "aiosqlite": "aiosqlite",
    "aiohttp": "aiohttp",
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
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent,
    LabeledPrice, PreCheckoutQuery,
    ChosenInlineResult, FSInputFile,
    InlineQueryResultCachedMpeg4Gif,
)

from messages import MESSAGES

# ============================================================
# v1.2: импорты для гифок
# ============================================================
import gif_db
import gif_renderer

# ---------- КОНФИГ ----------
BOT_TOKEN = "ТОКЕН"
ADMIN_IDS = [1012040843]
DB_PATH = "sales.db"
BOT_URL = "https://t.me/Stars2ProfitBot"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# ВЕРСИЯ (видит только админ в /admin и в логах при старте)
# ============================================================
VERSION = "v1.2 (gif-inline, timers-pending, show-usd, admin-gif-panel)"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

db = None

# ---------- ГЛОБАЛЬНЫЕ ПРЕМИУМ-ЭМОДЗИ ----------
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
    waiting_for_buy_amount = State()
    waiting_for_category = State()
    waiting_for_nft_link = State()
    waiting_for_sell_amount = State()
    waiting_for_royalty = State()

class PendingBuy(StatesGroup):
    waiting_for_buy_amount = State()
    waiting_for_category = State()
    waiting_for_nft_link = State()
    waiting_for_royalty = State()
    waiting_for_timer_days = State()  # v1.2

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

# ============================================================
# v1.2: состояния для админ-панели гифок
# ============================================================
class AdminGifAdd(StatesGroup):
    waiting_for_link = State()

class AdminGifEditMeta(StatesGroup):
    waiting_for_value = State()

class AdminGifEditParams(StatesGroup):
    waiting_for_value = State()


# ---------- ЯЗЫК / НАСТРОЙКИ ----------
async def get_user_lang(user_id):
    conn = await get_db()
    cur = await conn.execute("SELECT lang FROM user_settings WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return row[0] if row else "ru"


async def set_user_lang(user_id, lang):
    conn = await get_db()
    await conn.execute("INSERT OR REPLACE INTO user_settings (user_id, lang) VALUES (?,?)", (user_id, lang))
    await conn.commit()


# ============================================================
# v1.2: настройка "показывать в USD"
# ============================================================
async def get_user_show_usd(user_id):
    conn = await get_db()
    cur = await conn.execute("SELECT show_usd FROM user_settings WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    if row and row[0] is not None:
        return bool(row[0])
    return True


async def set_user_show_usd(user_id, show: bool):
    conn = await get_db()
    await conn.execute(
        "UPDATE user_settings SET show_usd=? WHERE user_id=?",
        (int(show), user_id)
    )
    await conn.commit()


# ---------- БАЗА ДАННЫХ ----------
async def get_db():
    global db
    if db is None:
        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db():
    conn = await get_db()
    await conn.executescript('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT,
            nft_link TEXT,
            nft_image TEXT,
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pending_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT,
            nft_link TEXT,
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
    ''')

    # --- Миграции для старых БД ---
    for col, typ in [
        ('nft_link', 'TEXT'),
        ('gram_price', 'REAL DEFAULT 0'),
        ('gram_price_buy', 'REAL DEFAULT 0'),
        ('royalty_gram', 'REAL DEFAULT 0'),
    ]:
        try:
            await conn.execute(f"ALTER TABLE pending_sales ADD COLUMN {col} {typ}")
        except:
            pass

    for col in ['nft_image', 'nft_name', 'collection_emoji_id']:
        try:
            await conn.execute(f"ALTER TABLE sales ADD COLUMN {col} TEXT")
        except:
            pass

    for col, typ in [('gram_price_buy', 'REAL DEFAULT 0'), ('gram_price_sell', 'REAL DEFAULT 0')]:
        try:
            await conn.execute(f"ALTER TABLE sales ADD COLUMN {col} {typ}")
        except:
            pass

    nft_cols = [
        ('gift_name', 'TEXT'),
        ('model', 'TEXT'), ('model_rarity', 'TEXT'), ('model_emoji_id', 'TEXT'),
        ('backdrop', 'TEXT'), ('backdrop_rarity', 'TEXT'), ('backdrop_emoji_id', 'TEXT'),
        ('symbol', 'TEXT'), ('symbol_rarity', 'TEXT'), ('symbol_emoji_id', 'TEXT'),
        ('collection_emoji_id', 'TEXT'),
    ]
    for col, typ in nft_cols:
        try:
            await conn.execute(f"ALTER TABLE sales ADD COLUMN {col} {typ}")
        except:
            pass

    for col, typ in nft_cols:
        try:
            await conn.execute(f"ALTER TABLE pending_sales ADD COLUMN {col} {typ}")
        except:
            pass

    try:
        await conn.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
    except:
        pass
    try:
        await conn.execute("ALTER TABLE user_change_alerts ADD COLUMN disabled_until REAL DEFAULT 0")
    except:
        pass

    # ============================================================
    # МИГРАЦИИ v1.2: show_usd, pending_id в timers, gif_cache
    # ============================================================
    try:
        await conn.execute("ALTER TABLE user_settings ADD COLUMN show_usd INTEGER DEFAULT 1")
    except:
        pass

    try:
        await conn.execute("ALTER TABLE timers ADD COLUMN pending_id INTEGER")
    except:
        pass

    await conn.execute('''
        CREATE TABLE IF NOT EXISTS gif_cache (
            slug TEXT PRIMARY KEY,
            nft_link TEXT,
            gift_name TEXT,
            model TEXT,
            backdrop TEXT,
            symbol TEXT,
            model_rarity TEXT,
            backdrop_rarity TEXT,
            symbol_rarity TEXT,
            mpeg4_file_id TEXT,
            caption TEXT,
            status TEXT DEFAULT 'pending',
            error TEXT,
            params_json TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_gif_cache_status ON gif_cache(status)",
        "CREATE INDEX IF NOT EXISTS idx_gif_cache_gift ON gif_cache(gift_name)",
        "CREATE INDEX IF NOT EXISTS idx_timers_pending ON timers(pending_id)",
    ]:
        try:
            await conn.execute(idx_sql)
        except:
            pass

    for admin_id in ADMIN_IDS:
        try:
            await conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (admin_id,))
        except:
            pass
    await conn.commit()


# ---------- ЛОГИРОВАНИЕ ----------
async def log_action(user_id: int, username: str, action: str, details: str = ""):
    try:
        conn = await get_db()
        await conn.execute(
            "INSERT INTO action_logs (user_id, username, action, details) VALUES (?,?,?,?)",
            (user_id, username or "", action, details[:500])
        )
        await conn.execute(
            "DELETE FROM action_logs WHERE id NOT IN (SELECT id FROM action_logs ORDER BY id DESC LIMIT 500)"
        )
        await conn.commit()
    except Exception as e:
        logger.error(f"Log action error: {e}")


async def log_error(error_type: str, details: str):
    try:
        conn = await get_db()
        await conn.execute(
            "INSERT INTO error_logs (error_type, details) VALUES (?,?)",
            (error_type, details[:2000])
        )
        await conn.execute(
            "DELETE FROM error_logs WHERE id NOT IN (SELECT id FROM error_logs ORDER BY id DESC LIMIT 500)"
        )
        await conn.commit()
    except Exception as e:
        logger.error(f"Log error failure: {e}")


# ---------- КЭШ КУРСА ----------
gram_cache = {"price": 0.0, "timestamp": 0}

async def get_gram_price():
    if gram_cache["price"] > 0 and (time.time() - gram_cache["timestamp"]) < 300:
        return gram_cache["price"]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd",
                timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = data.get("the-open-network", {}).get("usd", 2.5)
                    gram_cache["price"] = price
                    gram_cache["timestamp"] = time.time()
                    return price
                else:
                    await log_error("coingecko", f"HTTP {resp.status}")
    except asyncio.TimeoutError:
        await log_error("coingecko", "Timeout (10s)")
    except Exception as e:
        await log_error("coingecko", str(e)[:500])
    return gram_cache["price"] or 2.5


# ---------- USD-ПРОФИТ ПО ДВУМ КУРСАМ ----------
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


# ---------- ПРОЧИЕ УТИЛИТЫ ----------
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
    await conn.execute(
        "INSERT INTO user_collections (user_id, collection_name, last_used, use_count) "
        "VALUES (?,?,datetime('now'),1) ON CONFLICT(user_id, collection_name) DO UPDATE SET "
        "last_used=datetime('now'), use_count=use_count+1",
        (user_id, collection_name)
    )
    await conn.commit()

async def get_user_star_rate(user_id):
    conn = await get_db()
    cur = await conn.execute("SELECT star_rate FROM user_star_rates WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return row[0] if row else 0.013

async def save_user_star_rate(user_id, rate):
    conn = await get_db()
    await conn.execute(
        "INSERT OR REPLACE INTO user_star_rates (user_id, star_rate, updated_at) VALUES (?,?,datetime('now'))",
        (user_id, rate)
    )
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
    if row:
        return bool(row[0]), row[1], row[2] or 0
    return False, 5.0, 0

async def set_user_change_alert(user_id, enabled, percent=5.0):
    conn = await get_db()
    await conn.execute(
        "INSERT OR REPLACE INTO user_change_alerts (user_id, enabled, percent) VALUES (?,?,?)",
        (user_id, int(enabled), percent)
    )
    await conn.commit()


# ---------- ЦЕЛЬ ----------
async def check_goal_achievement(user_id):
    conn = await get_db()
    cur = await conn.execute("SELECT goal_gram, notified FROM profit_goals WHERE user_id=?", (user_id,))
    goal_row = await cur.fetchone()
    if not goal_row:
        return
    goal_gram, notified = goal_row
    if notified:
        return
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
            await bot.send_message(
                user_id,
                MESSAGES[lang]["goal_achieved"].format(goal=f"{goal_gram:.2f}", total=f"{total_profit:.4f}"),
                reply_markup=kb
            )
            await log_action(user_id, "", "goal_achieved", f"Цель {goal_gram:.2f} GRAM")
        except Exception as e:
            logger.error(f"Goal notification error: {e}")


# ---------- РЕФЕРАЛЫ ----------
async def activate_referral(user_id: int):
    conn = await get_db()
    cur = await conn.execute("SELECT referrer_id, is_active FROM referrals WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    if not row:
        return
    referrer_id, is_active = row
    if is_active:
        return
    await conn.execute("UPDATE referrals SET is_active=1 WHERE user_id=?", (user_id,))
    await conn.commit()
    if referrer_id:
        try:
            await bot.send_message(
                referrer_id,
                f"🎉 <b>Ваш реферал активен!</b>\n\n"
                f"Пользователь сделал первую сделку.\n"
                f"Вам начислено <b>+10 очков</b> репутации."
            )
        except:
            pass

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


# ============================================================
# ПАРСИНГ NFT (Fragment → t.me → changes.tg для эмодзи)
# ============================================================
def parse_gift_info_from_link(nft_link: str):
    if not nft_link:
        return None, None, None
    link = nft_link.strip()
    link = link.split("?")[0].split("#")[0].rstrip("/")
    if "/nft/" not in link:
        return None, None, None
    try:
        gift_part = link.split("/nft/")[1]
        gift_segment = gift_part.split("/")[0]
        if "-" not in gift_segment:
            return None, None, None
        slug_raw, number_raw = gift_segment.rsplit("-", 1)
        if not number_raw.isdigit():
            return None, None, None
        number = int(number_raw)
        slug = slug_raw.lower()
        gift_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', slug_raw)
        gift_name = gift_name.replace("Durovs", "Durov's")
        gift_name = re.sub(r'\bs\s', "'s ", gift_name).strip()
        return gift_name, slug, number
    except Exception as e:
        logger.warning(f"[parse_gift_info] ошибка для '{nft_link}': {e}")
        return None, None, None


async def get_gift_from_fragment(slug: str, number: int):
    url = f"https://nft.fragment.com/gift/{slug}-{number}.json"
    logger.info(f"[fragment] → запрос: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.info(f"[fragment] HTTP {resp.status} (попробуем другой источник)")
                    return None
                data = json.loads(await resp.text())
                attrs = data.get("attributes") or []
                result = {}
                for attr in attrs:
                    t = (attr.get("trait_type") or "").lower()
                    v = attr.get("value")
                    if t == "model":
                        result["model_name"] = v
                    elif t == "backdrop":
                        result["backdrop_name"] = v
                    elif t == "symbol":
                        result["symbol_name"] = v
                result["gift_name"] = data.get("name") or None
                result["image"] = data.get("image") or None
                if any(result.get(k) for k in ("model_name", "backdrop_name", "symbol_name")):
                    logger.info(
                        f"[fragment] ✅ OK: {slug}-{number} → "
                        f"model={result.get('model_name')!r} "
                        f"backdrop={result.get('backdrop_name')!r} "
                        f"symbol={result.get('symbol_name')!r}"
                    )
                    return result
                logger.warning(f"[fragment] нет атрибутов для {slug}-{number}")
                return None
    except asyncio.TimeoutError:
        logger.warning(f"[fragment] Timeout для {url}")
    except Exception as e:
        logger.warning(f"[fragment] {type(e).__name__}: {e}")
    return None


def _parse_tme_description(description: str) -> dict:
    result = {}
    if not description:
        return result
    for raw_line in description.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        m = re.match(r'^Model\s*:\s*(.+)$', line, re.IGNORECASE)
        if m:
            result["model_name"] = m.group(1).strip().rstrip(".")
            continue
        m = re.match(r'^Backdrop\s*:\s*(.+)$', line, re.IGNORECASE)
        if m:
            result["backdrop_name"] = m.group(1).strip().rstrip(".")
            continue
        m = re.match(r'^Symbol\s*:\s*(.+)$', line, re.IGNORECASE)
        if m:
            result["symbol_name"] = m.group(1).strip().rstrip(".")
            continue
    if result:
        return result

    m = re.search(
        r'appearance\s+(.+?)\s+on\s+an?\s+(.+?)\s+background\s+with\s+(.+?)\s+icons?',
        description, re.IGNORECASE
    )
    if m:
        result["model_name"]    = m.group(1).strip()
        result["backdrop_name"] = m.group(2).strip()
        result["symbol_name"]   = m.group(3).strip()
        return result

    for key, field in (("model_name", "Model"), ("backdrop_name", "Backdrop"), ("symbol_name", "Symbol")):
        m = re.search(rf'{field}\s*:\s*([^.\n]+)', description, re.IGNORECASE)
        if m:
            result[key] = m.group(1).strip()
    return result


async def get_gift_from_tme(nft_link: str):
    url = nft_link.strip()
    if not url.startswith("http"):
        url = "https://" + url
    url = url.rstrip("/")
    logger.info(f"[t.me] → запрос: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, allow_redirects=True) as resp:
                if resp.status != 200:
                    logger.warning(f"[t.me] HTTP {resp.status} для {url}")
                    return None
                html_text = await resp.text()

                m = re.search(
                    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
                    html_text
                )
                if not m:
                    m = re.search(
                        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
                        html_text
                    )
                if not m:
                    logger.warning(f"[t.me] og:description не найден в {url}")
                    return None

                description = html.unescape(m.group(1))
                logger.info(f"[t.me] og:description: {description[:400]!r}")

                result = _parse_tme_description(description)

                # ============================================================
                # v1.2: ищем <tg-emoji emoji-id="..."> в HTML t.me
                # ============================================================
                emoji_patterns = {
                    "model_emoji_id":    r'Model[^<]*</td>.*?<tg-emoji\s+emoji-id="(\d+)"',
                    "backdrop_emoji_id": r'Backdrop[^<]*</td>.*?<tg-emoji\s+emoji-id="(\d+)"',
                    "symbol_emoji_id":   r'Symbol[^<]*</td>.*?<tg-emoji\s+emoji-id="(\d+)"',
                }
                for key, pattern in emoji_patterns.items():
                    m2 = re.search(pattern, html_text, re.IGNORECASE | re.DOTALL)
                    if m2:
                        result[key] = m2.group(1)
                        logger.info(f"[t.me] <tg-emoji> {key} = {m2.group(1)}")

                if any(result.get(k) for k in ("model_name", "backdrop_name", "symbol_name",
                                                "model_emoji_id", "backdrop_emoji_id", "symbol_emoji_id")):
                    logger.info(
                        f"[t.me] ✅ OK: model={result.get('model_name')!r} "
                        f"backdrop={result.get('backdrop_name')!r} "
                        f"symbol={result.get('symbol_name')!r} "
                        f"emojis=({result.get('model_emoji_id')},{result.get('backdrop_emoji_id')},{result.get('symbol_emoji_id')})"
                    )
                    return result

                logger.warning(f"[t.me] не удалось распарсить описание: {description[:200]!r}")
                return None
    except asyncio.TimeoutError:
        logger.warning(f"[t.me] Timeout для {url}")
    except Exception as e:
        logger.warning(f"[t.me] {type(e).__name__}: {e}")
    return None


async def get_gift_catalog_from_changes(gift_name: str):
    if not gift_name:
        return None
    slug = gift_name.lower().strip()
    slug = slug.replace("’", "").replace("'", "").replace("`", "").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    if not slug:
        return None

    url = f"https://api.changes.tg/emoji/{slug}"
    logger.info(f"[changes.tg] → запрос каталога: {url}")
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    def fmt_rarity(val):
        if val is None:
            return None
        try:
            v = float(val)
            return f"{int(v) if v == int(v) else v}%"
        except (TypeError, ValueError):
            return f"{val}%"

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(await resp.text())

                catalog = {"models": {}, "backdrops": {}, "symbols": {}}
                for src_key, dst_key in (
                    ("models", "models"),
                    ("backdrops", "backdrops"),
                    ("patterns", "symbols"),
                ):
                    for item in (data.get(src_key) or []):
                        if not isinstance(item, dict):
                            continue
                        name = item.get("name")
                        if not name:
                            continue
                        catalog[dst_key][name.lower()] = {
                            "name":     name,
                            "rarity":   fmt_rarity(item.get("rarity")),
                            "emoji_id": item.get("customEmojiId"),
                        }

                for old_key, dst_key in (
                    ("model", "models"), ("backdrop", "backdrops"), ("pattern", "symbols"),
                ):
                    item = data.get(old_key)
                    if isinstance(item, dict) and item.get("name"):
                        key = item["name"].lower()
                        if key not in catalog[dst_key]:
                            catalog[dst_key][key] = {
                                "name":     item.get("name"),
                                "rarity":   fmt_rarity(item.get("rarity")),
                                "emoji_id": item.get("customEmojiId"),
                            }

                catalog["collection_emoji_id"] = data.get("originalCustomEmojiId")
                total = sum(len(v) for v in catalog.values() if isinstance(v, dict))
                logger.info(f"[changes.tg] ✅ каталог: {total} вариантов ({slug})")
                return catalog
    except Exception as e:
        logger.warning(f"[changes.tg] catalog error: {e}")
    return None


def _find_in_catalog(catalog: dict, section: str, name: str):
    if not catalog or not name:
        return None
    bucket = catalog.get(section) or {}
    key = name.strip().lower()
    if key in bucket:
        return bucket[key]
    def norm(s):
        return re.sub(r"[^a-z0-9]", "", s.lower())
    nkey = norm(name)
    for k, v in bucket.items():
        if norm(k) == nkey:
            return v
    return None


async def parse_nft_link(nft_link: str):
    gift_name, slug, number = parse_gift_info_from_link(nft_link)
    logger.info(f"[parse_nft_link] input='{nft_link}' → name={gift_name!r} slug={slug!r} number={number!r}")
    if not gift_name or slug is None or number is None:
        return None

    result = {"gift_name": gift_name}

    catalog = await get_gift_catalog_from_changes(gift_name)

    source_data = await get_gift_from_fragment(slug, number)
    source_name = "fragment"
    if not source_data:
        logger.info("[parse_nft_link] Fragment не ответил — пробую t.me")
        source_data = await get_gift_from_tme(nft_link)
        source_name = "t.me"

    if not source_data:
        logger.warning(f"[parse_nft_link] ни Fragment, ни t.me не дали данных для {slug}-{number}")
        if catalog and catalog.get("collection_emoji_id"):
            result["collection_emoji_id"] = catalog["collection_emoji_id"]
        return result

    logger.info(f"[parse_nft_link] источник данных: {source_name}")

    if source_data.get("gift_name"):
        result["gift_name"] = source_data["gift_name"]

    # ============================================================
    # v1.2: сначала emoji_id из t.me (если есть), потом changes.tg
    # ============================================================
    for name_key, section, out_prefix in (
        ("model_name",    "models",    "model"),
        ("backdrop_name", "backdrops", "backdrop"),
        ("symbol_name",   "symbols",   "symbol"),
    ):
        real_name = source_data.get(name_key)
        if not real_name:
            continue
        result[out_prefix] = real_name

        tme_emoji_key = f"{out_prefix}_emoji_id"
        if source_data.get(tme_emoji_key):
            result[tme_emoji_key] = source_data[tme_emoji_key]

        match = _find_in_catalog(catalog, section, real_name)
        if match:
            result[f"{out_prefix}_rarity"] = match.get("rarity")
            if not result.get(tme_emoji_key):
                result[tme_emoji_key] = match.get("emoji_id")
        else:
            result[f"{out_prefix}_rarity"] = None
            if not result.get(tme_emoji_key):
                result[tme_emoji_key] = None

    if catalog and catalog.get("collection_emoji_id"):
        result["collection_emoji_id"] = catalog["collection_emoji_id"]

    return result


# ============================================================
# v1.2: утилиты для гифок
# ============================================================
def _extract_slug_from_link(nft_link: str):
    if not nft_link:
        return None, None, None
    link = nft_link.strip().split("?")[0].split("#")[0].rstrip("/")
    if "/nft/" not in link:
        return None, None, None
    try:
        gift_segment = link.split("/nft/")[1].split("/")[0]
        if "-" not in gift_segment:
            return None, None, None
        slug_raw, number_raw = gift_segment.rsplit("-", 1)
        if not number_raw.isdigit():
            return None, None, None
        slug_full = slug_raw.lower()
        return f"{slug_full}-{number_raw}", slug_full, int(number_raw)
    except:
        return None, None, None


def _build_gif_caption(nft_data: dict, deal_id: int = None) -> str:
    gift_name = nft_data.get("gift_name") or "NFT"
    collection_emoji = premium_emoji(nft_data.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)

    lines = [f"{collection_emoji} <b>{html.escape(gift_name)}</b>"]
    if deal_id:
        lines[0] += f" · #{deal_id}"

    attrs = format_gift_attributes(nft_data)
    if attrs:
        lines.append("")
        lines.append(attrs)

    if nft_data.get("nft_link"):
        lines.append("")
        lines.append(f'{EMOJI_LINK} <a href="{html.escape(nft_data["nft_link"])}">Открыть NFT</a>')

    text = "\n".join(lines)
    if len(text) > 1024:
        text = text[:1020] + "…"
    return text


async def generate_gif_background(slug_full: str, slug_short: str, number: int,
                                   nft_link: str, nft_data: dict, user_id: int):
    existing = await gif_db.gif_get_ready(slug_full)
    if existing:
        logger.info(f"[gif] {slug_full}: уже в кэше, пропускаем")
        return

    existing = await gif_db.gif_get(slug_full)
    if existing and existing.get("status") == "pending":
        logger.info(f"[gif] {slug_full}: уже рендерится, пропускаем")
        return

    gift_name = nft_data.get("gift_name") or slug_short
    await gif_db.gif_set_pending(
        slug_full, nft_link, gift_name, user_id,
        params_json=json.dumps(gif_renderer.DEFAULT_PARAMS)
    )

    mp4_path = None
    work_dir = None
    try:
        logger.info(f"[gif] {slug_full}: старт рендера")
        mp4_path, work_dir = await gif_renderer.render_to_tempfile(slug_short)

        admin_chat = ADMIN_IDS[0]
        msg = await bot.send_animation(
            chat_id=admin_chat,
            animation=FSInputFile(str(mp4_path), filename=f"{slug_full}.mp4"),
            caption=f"🎬 {gift_name}",
            request_timeout=300
        )

        file_id = None
        if msg.animation:
            file_id = msg.animation.file_id
        elif msg.document:
            file_id = msg.document.file_id

        try:
            await bot.delete_message(chat_id=admin_chat, message_id=msg.message_id)
        except:
            pass

        if not file_id:
            raise RuntimeError("Telegram не вернул file_id")

        caption = _build_gif_caption(nft_data)
        await gif_db.gif_set_ready(slug_full, file_id, nft_data, caption,
                                    params_json=json.dumps(gif_renderer.DEFAULT_PARAMS))
        logger.info(f"[gif] {slug_full}: ✅ file_id={file_id[:30]}...")

    except Exception as e:
        logger.exception(f"[gif] {slug_full}: ошибка рендера")
        await gif_db.gif_set_error(slug_full, str(e)[:1000])
    finally:
        if work_dir and work_dir.exists():
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except:
                pass


# ---------- ФОРМАТИРОВАНИЕ ПРЕМИУМ-ЭМОДЗИ ----------
def premium_emoji(emoji_id, fallback: str) -> str:
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback


def get_collection_emoji_html(deal: dict) -> str:
    eid = deal.get("collection_emoji_id") if deal else None
    return premium_emoji(eid, EMOJI_COLLECTION_FALLBACK)


def format_gift_attributes(data: dict) -> str:
    if not data:
        return ""
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


# ---------- КЛАВИАТУРЫ ----------
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


# ---------- /start ----------
@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    args = message.text.split()
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
                    await log_action(user_id, message.from_user.username or "", "referral_join", f"referrer={referrer_id}")
        except:
            pass

    await update_user(message.from_user)
    try:
        await bot.set_chat_menu_button(chat_id=message.chat.id, menu_button=None)
    except:
        pass
    lang = await get_user_lang(user_id)
    msgs = MESSAGES[lang]
    await message.answer(msgs["start"].format(name=message.from_user.first_name), reply_markup=get_main_kb(lang))


async def update_user(user):
    conn = await get_db()
    await conn.execute(
        "INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, joined_date, last_activity, referred_by) "
        "VALUES (?,?,?,?, COALESCE((SELECT joined_date FROM users WHERE user_id=?), datetime('now')), datetime('now'), "
        "(SELECT referred_by FROM users WHERE user_id=?))",
        (user.id, user.username, user.first_name, user.last_name, user.id, user.id)
    )
    await conn.execute("INSERT OR IGNORE INTO user_settings (user_id, lang, show_usd) VALUES (?, 'ru', 1)", (user.id,))
    await conn.execute("INSERT OR IGNORE INTO user_earnings_reports (user_id) VALUES (?)", (user.id,))
    await conn.commit()


# ---------- СМЕНА ЯЗЫКА ----------
@dp.message(F.text.in_(["🌐 🇷🇺 Русский", "🌐 🇬🇧 English"]))
async def switch_language(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    current_lang = await get_user_lang(user_id)
    new_lang = "en" if current_lang == "ru" else "ru"
    await set_user_lang(user_id, new_lang)
    await log_action(user_id, message.from_user.username or "", "lang_change", new_lang)
    msgs = MESSAGES[new_lang]
    await message.answer(msgs["lang_changed"], reply_markup=get_main_kb(new_lang))


# ---------- ДОБАВЛЕНИЕ СДЕЛКИ ----------
@dp.message(F.text.in_(["📊 Добавить сделку", "📊 Add Deal"]))
async def add_deal_start(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
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
        await message.answer(
            f"📥 {amount} GRAM\n"
            f"{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n\n"
            f"{MESSAGES[lang]['enter_collection']}",
            reply_markup=get_cancel_kb(lang)
        )
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))


@dp.message(AddProfit.waiting_for_category)
async def process_category(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    await state.update_data(category=message.text.strip())
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
        attrs = format_gift_attributes(nft_data)
        collection_emoji = premium_emoji(nft_data.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
        gift_name = nft_data.get('gift_name', 'NFT')
        if attrs:
            await message.answer(f"{collection_emoji} <b>{gift_name}</b>\n{attrs}", reply_markup=get_cancel_kb(lang))
        else:
            await message.answer(f"{collection_emoji} <b>{gift_name}</b>\n<i>Характеристики не найдены</i>", reply_markup=get_cancel_kb(lang))

    # ============================================================
    # v1.2: фоновый рендер гифки (юзер не ждёт)
    # ============================================================
    if nft_data:
        slug_full, slug_short, number = _extract_slug_from_link(link)
        if slug_full and number is not None:
            asyncio.create_task(generate_gif_background(slug_full, slug_short, number, link, nft_data, message.from_user.id))

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
        await message.answer(
            f"{EMOJI_DOLLAR} Курс покупки: <b>${gp_buy:.4f}</b>\n"
            f"{EMOJI_DOLLAR} Курс продажи: <b>${gram_price_sell:.4f}</b>\n\n"
            f"{MESSAGES[lang]['select_commission'].format(royalty=f'{royalty:.2f}')}",
            reply_markup=kb
        )
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
    if user_id is None:
        user_id = message.from_user.id if hasattr(message, 'from_user') else message.chat.id
    data = await state.get_data()
    buy_amount = data["buy_amount"]
    sell_amount = data["sell_amount"]
    gram_price_buy = data.get("gram_price_buy") or 0
    gram_price_sell = data.get("gram_price_sell") or 0

    current_price = await get_gram_price()
    if gram_price_buy <= 0:
        gram_price_buy = current_price
    if gram_price_sell <= 0:
        gram_price_sell = current_price

    profit_gram = sell_amount - buy_amount - royalty
    profit_usd = compute_profit_usd(
        buy_amount, sell_amount, royalty,
        gram_price_buy, gram_price_sell,
        fallback_gram_price=gram_price_sell
    )
    date = datetime.now().strftime("%d.%m.%Y")

    conn = await get_db()
    await conn.execute(
        """INSERT INTO sales (user_id, category, nft_link, date, buy_amount, sell_amount, gram_price,
           gram_price_buy, gram_price_sell, profit_gram, profit_usd, royalty_gram,
           gift_name, model, model_rarity, model_emoji_id,
           backdrop, backdrop_rarity, backdrop_emoji_id,
           symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, data["category"], data["nft_link"], date, buy_amount, sell_amount, gram_price_sell,
         gram_price_buy, gram_price_sell,
         round(profit_gram, 4), profit_usd, royalty,
         data.get("gift_name"), data.get("model"), data.get("model_rarity"), data.get("model_emoji_id"),
         data.get("backdrop"), data.get("backdrop_rarity"), data.get("backdrop_emoji_id"),
         data.get("symbol"), data.get("symbol_rarity"), data.get("symbol_emoji_id"),
         data.get("collection_emoji_id"))
    )
    await conn.commit()
    await add_user_collection(user_id, data["category"])
    await state.clear()
    await activate_referral(user_id)
    await check_goal_achievement(user_id)
    await log_action(user_id, "", "add_sale", f"{data['category']}, profit={profit_gram:+.4f}")

    msgs = MESSAGES[lang]
    attrs = format_gift_attributes(data)
    collection_emoji = premium_emoji(data.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
    gift_name = data.get('gift_name') or data.get('category') or 'NFT'
    text = msgs["sale_saved"].format(
        category=data['category'], buy=buy_amount, sell=sell_amount,
        royalty=f"{royalty:.2f}", profit=f"{profit_gram:+.4f}", usd=f"{profit_usd:+.2f}"
    )
    header = (
        f"{collection_emoji} <b>{gift_name}</b>\n"
        f"{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n"
        f"{EMOJI_DOLLAR} Курс продажи: <b>${gram_price_sell:.4f}</b>"
    )
    if attrs:
        header = f"{header}\n{attrs}"
    await message.answer(f"{header}\n\n{text}", reply_markup=get_main_kb(lang))


# ---------- ОТЛОЖЕННАЯ ПОКУПКА ----------
@dp.message(F.text.in_(["📥 Отложенная покупка", "📥 Pending Buy"]))
async def pending_start(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
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
        await message.answer(
            f"📥 {amount} GRAM\n"
            f"{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n\n"
            f"{MESSAGES[lang]['enter_collection']}",
            reply_markup=get_cancel_kb(lang)
        )
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))


@dp.message(PendingBuy.waiting_for_category)
async def process_pending_category(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    await state.update_data(category=message.text.strip())
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
    cur = await conn.execute(
        """INSERT INTO pending_sales (user_id, category, nft_link, date, buy_amount, gram_price, gram_price_buy, royalty_gram,
           gift_name, model, model_rarity, model_emoji_id,
           backdrop, backdrop_rarity, backdrop_emoji_id,
           symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, data["category"], data["nft_link"], datetime.now().strftime("%d.%m.%Y"),
         data["buy_amount"], gram_price_buy, gram_price_buy, royalty,
         data.get("gift_name"), data.get("model"), data.get("model_rarity"), data.get("model_emoji_id"),
         data.get("backdrop"), data.get("backdrop_rarity"), data.get("backdrop_emoji_id"),
         data.get("symbol"), data.get("symbol_rarity"), data.get("symbol_emoji_id"),
         data.get("collection_emoji_id"))
    )
    await conn.commit()
    pending_id = cur.lastrowid
    await state.update_data(pending_id=pending_id)

    await log_action(user_id, "", "add_pending", f"{data['category']}, {data['buy_amount']} GRAM, id={pending_id}")

    # ============================================================
    # v1.2: спрашиваем, через сколько дней напомнить о минте
    # ============================================================
    await state.set_state(PendingBuy.waiting_for_timer_days)
    msgs = MESSAGES[lang]
    await message.answer(
        f"{EMOJI_DOLLAR} Курс покупки зафиксирован: <b>${gram_price_buy:.4f}</b>\n\n"
        f"{msgs['pending_saved'].format(category=data['category'], amount=data['buy_amount'])}\n\n"
        f"⏰ Через сколько дней напомнить о минте?\n"
        f"Введите число дней (например, <code>7</code>) или <code>0</code>, чтобы не напоминать.",
        reply_markup=get_cancel_kb(lang)
    )


# ============================================================
# v1.2: обработка "через сколько дней напомнить о минте"
# ============================================================
@dp.message(PendingBuy.waiting_for_timer_days)
async def process_pending_timer_days(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        days = int(message.text.strip())
        if days < 0:
            raise ValueError

        data = await state.get_data()
        pending_id = data.get("pending_id")
        nft_link = data.get("nft_link")
        buy_amount = data.get("buy_amount")
        category = data.get("category", "—")

        conn = await get_db()

        if days > 0 and pending_id:
            event_time = time.time() + days * 86400
            await conn.execute(
                "INSERT INTO timers (user_id, event_type, nft_link, stars_amount, event_time, description, pending_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (message.from_user.id, "mint", nft_link, 0, event_time, category, pending_id)
            )
            await conn.commit()

        await state.clear()

        if days > 0:
            text = (
                f"✅ <b>Отложенная покупка сохранена!</b>\n"
                f"📁 {category}\n"
                f"💎 {buy_amount} GRAM\n\n"
                f"⏰ Напоминание о минте установлено: через <b>{days} дн.</b>"
            )
        else:
            text = (
                f"✅ <b>Отложенная покупка сохранена!</b>\n"
                f"📁 {category}\n"
                f"💎 {buy_amount} GRAM\n\n"
                f"🔕 Без напоминания."
            )

        await message.answer(text, reply_markup=get_main_kb(lang))
    except ValueError:
        await message.answer(
            "❌ Введите целое число дней (0 — без напоминания).",
            reply_markup=get_cancel_kb(lang)
        )


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
        link_icon = "🔗" if p['nft_link'] else ""
        royalty_info = f" | ⚙️ {p['royalty_gram']:.2f} GRAM" if p['royalty_gram'] else ""
        gp_buy = p['gram_price_buy'] if 'gram_price_buy' in p.keys() and p['gram_price_buy'] else 0
        gp_line = f"💵 Курс покупки: ${gp_buy:.4f}\n" if gp_buy else ""
        text += (
            f"🆔 <b>#{p['id']}</b> | 📁 {p['category']}\n"
            f"💎 {p['buy_amount']} GRAM {link_icon}\n"
            f"{gp_line}"
            f"📅 {p['date']}{royalty_info}\n\n"
        )
        row_buttons = [
            InlineKeyboardButton(text=f"✅ #{p['id']}", callback_data=f"complete_{p['id']}"),
            InlineKeyboardButton(text=f"🗑 #{p['id']}", callback_data=f"delete_pending_{p['id']}")
        ]
        kb.inline_keyboard.append(row_buttons)
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
    gp_buy = row['gram_price_buy'] if 'gram_price_buy' in row.keys() and row['gram_price_buy'] else 0
    gp_line = f"\n💵 Курс покупки: ${gp_buy:.4f}" if gp_buy else ""
    await callback.message.answer(
        MESSAGES[lang]["confirm_complete"].format(
            id=row['id'], category=row['category'], buy=row['buy_amount'],
            link=link, royalty=row['royalty_gram'] or "—", date=row['date']
        ) + gp_line,
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
        await message.answer(
            f"{EMOJI_DOLLAR} Курс продажи: <b>${gram_price_sell:.4f}</b>\n\n"
            f"{MESSAGES[lang]['select_commission'].format(royalty=f'{royalty:.2f}')}",
            reply_markup=kb
        )
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
    pending_id = data["pending_id"]
    sell_amount = data["sell_amount"]
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
    profit_usd = compute_profit_usd(
        buy_amt, sell_amount, royalty,
        gram_price_buy, gram_price_sell,
        fallback_gram_price=gram_price_sell
    )

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
    }
    if not nft_data["model"] and row["nft_link"]:
        fresh = await parse_nft_link(row["nft_link"])
        if fresh:
            nft_data = fresh

    await conn.execute(
        """INSERT INTO sales (user_id, category, nft_link, date, buy_amount, sell_amount, gram_price,
           gram_price_buy, gram_price_sell, profit_gram, profit_usd, royalty_gram,
           gift_name, model, model_rarity, model_emoji_id,
           backdrop, backdrop_rarity, backdrop_emoji_id,
           symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, row["category"], row["nft_link"], row["date"], buy_amt, sell_amount, gram_price_sell,
         gram_price_buy, gram_price_sell,
         round(profit_gram, 4), profit_usd, royalty,
         nft_data.get("gift_name"), nft_data.get("model"), nft_data.get("model_rarity"), nft_data.get("model_emoji_id"),
         nft_data.get("backdrop"), nft_data.get("backdrop_rarity"), nft_data.get("backdrop_emoji_id"),
         nft_data.get("symbol"), nft_data.get("symbol_rarity"), nft_data.get("symbol_emoji_id"),
         nft_data.get("collection_emoji_id"))
    )
    await conn.execute("DELETE FROM pending_sales WHERE id=?", (pending_id,))
    # ============================================================
    # v1.2: удаляем таймер, привязанный к этой отложке
    # ============================================================
    await conn.execute("DELETE FROM timers WHERE pending_id=?", (pending_id,))
    await conn.commit()
    await add_user_collection(user_id, row["category"])
    await state.clear()
    await activate_referral(user_id)
    await check_goal_achievement(user_id)
    await log_action(user_id, "", "complete_sale", f"{row['category']}, profit={profit_gram:+.4f}")

    link = f"<a href='{row['nft_link']}'>NFT</a>" if row['nft_link'] else "—"
    msgs = MESSAGES[lang]
    attrs = format_gift_attributes(nft_data) if nft_data else ""
    collection_emoji = premium_emoji(nft_data.get("collection_emoji_id") if nft_data else None, EMOJI_COLLECTION_FALLBACK)
    gift_name = (nft_data.get("gift_name") if nft_data else None) or row['category'] or 'NFT'
    text = msgs["deal_completed"].format(
        category=row['category'], buy=buy_amt, sell=sell_amount,
        profit=f"{profit_gram:+.4f}", link=link
    )
    header = (
        f"{collection_emoji} <b>{gift_name}</b>\n"
        f"{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n"
        f"{EMOJI_DOLLAR} Курс продажи: <b>${gram_price_sell:.4f}</b>\n"
        f"{EMOJI_DOLLAR} Прибыль в USD: <b>{profit_usd:+.2f}$</b>"
    )
    if attrs:
        header = f"{header}\n{attrs}"
    # ============================================================
    # v1.2: сообщаем, что таймер удалён
    # ============================================================
    text += "\n\n⏰ Напоминание о минте удалено."
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
    if not pending_id:
        try:
            await callback.message.edit_text(MESSAGES[lang]["cancelled"])
        except:
            await callback.message.answer(MESSAGES[lang]["cancelled"])
        await state.clear()
        return
    conn = await get_db()
    await conn.execute("DELETE FROM pending_sales WHERE id=? AND user_id=?", (pending_id, callback.from_user.id))
    # ============================================================
    # v1.2: удаляем таймер, привязанный к этой отложке
    # ============================================================
    await conn.execute("DELETE FROM timers WHERE pending_id=?", (pending_id,))
    await conn.commit()
    await state.clear()
    await log_action(callback.from_user.id, callback.from_user.username or "", "delete_pending", f"id={pending_id}")
    text = f"{MESSAGES[lang]['deleted']}\n⏰ Связанное напоминание тоже удалено."
    try:
        await callback.message.edit_text(text)
    except:
        await callback.message.answer(text)


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
    await callback.message.answer(
        MESSAGES[lang]["edit_buy_amount"].format(old=row['buy_amount']),
        reply_markup=get_cancel_kb(lang)
    )


@dp.message(EditProfit.waiting_for_buy_amount)
async def process_edit_buy_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
        gram_price_buy = await get_gram_price()
        await state.update_data(new_buy=amount, new_gram_price_buy=gram_price_buy)
        await state.set_state(EditProfit.waiting_for_category)
        await message.answer(
            f"{EMOJI_DOLLAR} Новый курс покупки: <b>${gram_price_buy:.4f}</b>\n\n"
            f"{MESSAGES[lang]['edit_category']}",
            reply_markup=get_cancel_kb(lang)
        )
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
        await message.answer(
            f"{EMOJI_DOLLAR} Новый курс продажи: <b>${gram_price_sell:.4f}</b>\n\n"
            f"{MESSAGES[lang]['edit_commission']}",
            reply_markup=kb
        )
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
    new_buy = data.get("new_buy")
    new_sell = data.get("new_sell")
    new_category = data.get("new_category")
    new_link = data.get("new_link")
    new_gram_price_buy = data.get("new_gram_price_buy") or await get_gram_price()
    new_gram_price_sell = data.get("new_gram_price_sell") or new_gram_price_buy

    profit_gram = new_sell - new_buy - royalty
    profit_usd = compute_profit_usd(
        new_buy, new_sell, royalty,
        new_gram_price_buy, new_gram_price_sell,
        fallback_gram_price=new_gram_price_sell
    )

    conn = await get_db()
    has_nft = any(k in data for k in ("model", "backdrop", "symbol", "gift_name"))
    if has_nft:
        await conn.execute(
            """UPDATE sales SET buy_amount=?, sell_amount=?, category=?, nft_link=?,
               profit_gram=?, profit_usd=?, royalty_gram=?, gram_price=?,
               gram_price_buy=?, gram_price_sell=?,
               gift_name=?, model=?, model_rarity=?, model_emoji_id=?,
               backdrop=?, backdrop_rarity=?, backdrop_emoji_id=?,
               symbol=?, symbol_rarity=?, symbol_emoji_id=?, collection_emoji_id=?
               WHERE id=? AND user_id=?""",
            (new_buy, new_sell, new_category, new_link,
             round(profit_gram, 4), profit_usd, royalty, new_gram_price_sell,
             new_gram_price_buy, new_gram_price_sell,
             data.get("gift_name"), data.get("model"), data.get("model_rarity"), data.get("model_emoji_id"),
             data.get("backdrop"), data.get("backdrop_rarity"), data.get("backdrop_emoji_id"),
             data.get("symbol"), data.get("symbol_rarity"), data.get("symbol_emoji_id"),
             data.get("collection_emoji_id"),
             deal_id, user_id)
        )
    else:
        await conn.execute(
            """UPDATE sales SET buy_amount=?, sell_amount=?, category=?, nft_link=?,
               profit_gram=?, profit_usd=?, royalty_gram=?, gram_price=?,
               gram_price_buy=?, gram_price_sell=?
               WHERE id=? AND user_id=?""",
            (new_buy, new_sell, new_category, new_link,
             round(profit_gram, 4), profit_usd, royalty, new_gram_price_sell,
             new_gram_price_buy, new_gram_price_sell,
             deal_id, user_id)
        )
    await conn.commit()
    await state.clear()
    await log_action(user_id, "", "edit_sale", f"id={deal_id}")
    await message.answer(
        f"{EMOJI_DOLLAR} Курс покупки: <b>${new_gram_price_buy:.4f}</b>\n"
        f"{EMOJI_DOLLAR} Курс продажи: <b>${new_gram_price_sell:.4f}</b>\n"
        f"{EMOJI_DOLLAR} Прибыль в USD: <b>{profit_usd:+.2f}$</b>\n\n"
        f"{MESSAGES[lang]['updated']}",
        reply_markup=get_main_kb(lang)
    )


# ---------- УДАЛЕНИЕ СДЕЛКИ ----------
@dp.callback_query(F.data.regexp(r"^delete_\d+$"))
async def delete_deal_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    deal_id = int(callback.data.split("_")[1])
    await state.update_data(delete_deal_id=deal_id)
    await state.set_state(DeleteConfirm.waiting)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=MESSAGES[lang]["delete_yes"], callback_data="confirm_delete"),
         InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]
    ])
    await callback.message.answer(MESSAGES[lang]["delete_confirm"], reply_markup=kb)


@dp.callback_query(F.data == "confirm_delete")
async def confirm_delete(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    deal_id = data.get("delete_deal_id")
    lang = await get_user_lang(callback.from_user.id)
    if not deal_id:
        try:
            await callback.message.edit_text(MESSAGES[lang]["cancelled"])
        except:
            await callback.message.answer(MESSAGES[lang]["cancelled"])
        await state.clear()
        return
    conn = await get_db()
    await conn.execute("DELETE FROM sales WHERE id=? AND user_id=?", (deal_id, callback.from_user.id))
    await conn.commit()
    await state.clear()
    await log_action(callback.from_user.id, callback.from_user.username or "", "delete_sale", f"id={deal_id}")
    try:
        await callback.message.edit_text(MESSAGES[lang]["deleted"])
    except:
        await callback.message.answer(MESSAGES[lang]["deleted"])


# ---------- ИСТОРИЯ ----------
PAGE_SIZE = 5

@dp.message(F.text.in_(["📋 История", "📋 History"]))
@dp.message(Command("history"))
async def history(message: Message):
    await show_history_page(message, message.from_user.id, 0)


async def show_history_page(message: Message, user_id: int, page: int):
    lang = await get_user_lang(user_id)
    show_usd = await get_user_show_usd(user_id)
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
        attrs = format_gift_attributes({
            "model": d.get("model"), "model_rarity": d.get("model_rarity"), "model_emoji_id": d.get("model_emoji_id"),
            "backdrop": d.get("backdrop"), "backdrop_rarity": d.get("backdrop_rarity"), "backdrop_emoji_id": d.get("backdrop_emoji_id"),
            "symbol": d.get("symbol"), "symbol_rarity": d.get("symbol_rarity"), "symbol_emoji_id": d.get("symbol_emoji_id"),
        })
        attrs_line = f"{attrs}\n" if attrs else ""

        gp_buy = d.get("gram_price_buy") or 0
        gp_sell = d.get("gram_price_sell") or d.get("gram_price") or 0
        if show_usd and gp_buy and gp_sell and gp_buy != gp_sell:
            courses_line = f"{EMOJI_DOLLAR} ${gp_buy:.4f} → ${gp_sell:.4f}\n"
        elif show_usd and (gp_buy or gp_sell):
            courses_line = f"{EMOJI_DOLLAR} ${gp_sell or gp_buy:.4f}\n"
        else:
            courses_line = ""

        profit_usd = d.get("profit_usd") or 0
        usd_part = f"{EMOJI_DOLLAR} {profit_usd:+.2f}$ | " if show_usd else ""
        text += (
            f"{emoji} <b>#{d['id']}</b> | {d['category']}\n"
            f"{gift_line}{attrs_line}"
            f"{EMOJI_DIAMOND} {d['buy_amount']} → {d['sell_amount']} GRAM\n"
            f"{courses_line}"
            f"{usd_part}💰 {d['profit_gram']:+.4f} GRAM | {link} | {d['date']}\n\n"
        )
    kb_rows = []
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text=MESSAGES[lang]["history_prev"], callback_data=f"hist_prev_{page}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text=MESSAGES[lang]["history_next"], callback_data=f"hist_next_{page}"))
    if nav_buttons:
        kb_rows.append(nav_buttons)
    action_buttons = []
    for d in deals:
        action_buttons.append(InlineKeyboardButton(text=MESSAGES[lang]["edit_btn"].format(id=d['id']), callback_data=f"edit_{d['id']}"))
        action_buttons.append(InlineKeyboardButton(text=MESSAGES[lang]["delete_btn"].format(id=d['id']), callback_data=f"delete_{d['id']}"))
    for i in range(0, len(action_buttons), 4):
        kb_rows.append(action_buttons[i:i+4])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("hist_"))
async def history_pagination(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split("_")
    direction = parts[1]
    current_page = int(parts[2])
    new_page = current_page - 1 if direction == "prev" else current_page + 1
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
    cur = await conn.execute(
        "SELECT COUNT(*), SUM(profit_gram), SUM(profit_usd), MAX(profit_gram), MIN(profit_gram), AVG(profit_gram) "
        "FROM sales WHERE user_id=?", (user_id,)
    )
    row = await cur.fetchone()
    if not row or row[0] is None:
        return await message.answer(MESSAGES[lang]["stats_no_deals"])
    deals, total_g, total_u, max_g, min_g, avg_g = row
    if not deals:
        return await message.answer(MESSAGES[lang]["stats_no_deals"])

    cur = await conn.execute("SELECT SUM(buy_amount), SUM(sell_amount) FROM sales WHERE user_id=?", (user_id,))
    buy_total, sell_total = await cur.fetchone()
    buy_total = buy_total or 0
    sell_total = sell_total or 0
    cur = await conn.execute("SELECT goal_gram FROM profit_goals WHERE user_id=?", (user_id,))
    goal_row = await cur.fetchone()
    goal = goal_row[0] if goal_row else None
    star_rate = await get_user_star_rate(user_id)
    royalty = await get_user_royalty(user_id)

    msgs = MESSAGES[lang]
    text = msgs["stats_title"]
    text += msgs["stats_total"].format(total=f"{total_g:+.4f}", usd=f"{total_u:+.2f}") + "\n"
    text += msgs["stats_deals"].format(deals=deals) + "\n"
    text += msgs["stats_avg"].format(avg=f"{avg_g:+.4f}") + "\n"
    text += msgs["stats_max"].format(max=f"{max_g:+.4f}") + "\n"
    text += msgs["stats_min"].format(min=f"{min_g:+.4f}") + "\n"
    text += msgs["stats_volume"].format(buy=f"{buy_total:.2f}", sell=f"{sell_total:.2f}") + "\n"
    text += msgs["stats_star_rate"].format(rate=f"{star_rate:.6f}") + "\n"
    text += msgs["stats_royalty"].format(royalty=f"{royalty:.2f}") + "\n"
    if goal:
        text += "\n" + msgs["stats_goal"].format(goal=f"{goal:.2f}", bar=make_progress_bar(total_g, goal)) + "\n"
    text += "\n" + msgs["stats_gram_price"].format(price=f"{await get_gram_price():.4f}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msgs["stats_collections_btn"], callback_data="stats_collections"),
         InlineKeyboardButton(text=msgs["stats_months_btn"], callback_data="stats_months")],
        [InlineKeyboardButton(text=msgs["stats_top_btn"], callback_data="stats_top"),
         InlineKeyboardButton(text=msgs["stats_cumulative_btn"], callback_data="stats_cumulative")],
        [InlineKeyboardButton(text=msgs["stats_chart_btn"], callback_data="stats_chart")],
        [InlineKeyboardButton(text=msgs["stats_close_btn"], callback_data="close_stats")]
    ])
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "stats_collections")
async def stats_collections(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    uid = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute(
        "SELECT category, COUNT(*), SUM(profit_gram), SUM(profit_usd) FROM sales WHERE user_id=? GROUP BY category ORDER BY SUM(profit_gram) DESC", (uid,)
    )
    rows = await cur.fetchall()
    text = MESSAGES[lang]["collections_title"]
    if not rows:
        text += "—"
    else:
        for i, (cat, cnt, profit_g, profit_u) in enumerate(rows, 1):
            emoji = get_profit_emoji(profit_g)
            text += f"{i}. {emoji} {cat}: {profit_g:+.4f} GRAM (${profit_u or 0:+.2f}) — {cnt} сделок\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["stats_back_btn"], callback_data="stats_back")]])
    await callback.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "stats_months")
async def stats_months(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    uid = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute(
        "SELECT substr(date, 4, 7) as month, COUNT(*), SUM(profit_gram) FROM sales WHERE user_id=? GROUP BY month ORDER BY date DESC LIMIT 6", (uid,)
    )
    rows = await cur.fetchall()
    if not rows:
        text = "Нет данных по месяцам."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["stats_back_btn"], callback_data="stats_back")]])
        await callback.message.edit_text(text, reply_markup=kb)
        return
    months = [r[0] for r in reversed(rows)]
    profits = [float(r[2]) for r in reversed(rows)]
    config = {
        "type": "bar", "data": {
            "labels": months,
            "datasets": [{"label": "GRAM", "data": profits, "backgroundColor": ["#2ecc71" if p>0 else "#e74c3c" for p in profits]}]
        }, "options": {"title": {"display": True, "text": "Прибыль по месяцам", "fontSize": 14}}
    }
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
    uid = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute(
        "SELECT id, category, buy_amount, sell_amount, profit_gram, profit_usd, date, nft_link FROM sales WHERE user_id=? ORDER BY profit_gram DESC LIMIT 10", (uid,)
    )
    rows = await cur.fetchall()
    text = MESSAGES[lang]["top_title"]
    if not rows:
        text += "—"
    else:
        for did, cat, buy, sell, pg, pu, dt, link in rows:
            emoji = get_profit_emoji(pg)
            pu = pu or 0
            text += f"{emoji} <b>#{did}</b> {cat} — {buy}→{sell} GRAM\n💰 {pg:+.4f} GRAM ({pu:+.2f}$) | 📅 {dt}\n"
            if link:
                text += f"{EMOJI_LINK} <a href='{link}'>NFT</a>\n"
            text += "\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["stats_back_btn"], callback_data="stats_back")]])
    await callback.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "stats_cumulative")
async def stats_cumulative(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    uid = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT date, profit_gram FROM sales WHERE user_id=? ORDER BY id ASC", (uid,))
    rows = await cur.fetchall()
    if not rows:
        await callback.answer("Нет сделок")
        return
    dates, cum = [], []
    total = 0.0
    for r in rows:
        dates.append(r[0])
        total += float(r[1])
        cum.append(round(total, 4))
    config = {
        "type": "line", "data": {
            "labels": dates, "datasets": [{"label": "GRAM", "data": cum, "borderColor": "#2ecc71", "fill": False}]
        }, "options": {"title": {"display": True, "text": "Рост общей прибыли", "fontSize": 14}}
    }
    chart_url = quickchart_url(config)
    await callback.message.answer_photo(chart_url, caption=MESSAGES[lang]["cumulative_title"])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["stats_back_btn"], callback_data="stats_back")]])
    await callback.message.edit_reply_markup(reply_markup=kb)


@dp.callback_query(F.data == "stats_chart")
async def stats_chart(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    uid = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT profit_gram FROM sales WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,))
    rows = await cur.fetchall()
    if not rows:
        await callback.answer("Нет сделок")
        return
    profits = [float(r[0]) for r in rows]
    labels = [f"#{i+1}" for i in range(len(profits))]
    config = {
        "type": "bar", "data": {
            "labels": labels, "datasets": [{"label": "GRAM", "data": profits, "backgroundColor": ["#2ecc71" if p>0 else "#e74c3c" for p in profits]}]
        }, "options": {"title": {"display": True, "text": "Последние 20 сделок", "fontSize": 14}}
    }
    chart_url = quickchart_url(config)
    await callback.message.answer_photo(chart_url, caption=MESSAGES[lang]["chart_title"])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["stats_back_btn"], callback_data="stats_back")]])
    await callback.message.edit_reply_markup(reply_markup=kb)


@dp.callback_query(F.data == "stats_back")
async def stats_back(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except:
        pass
    await show_stats_dashboard(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "close_stats")
async def close_stats(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except:
        pass


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
    direction = callback.data.replace("calc_", "")
    await state.update_data(calc_dir=direction)
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
            text = MESSAGES[lang]["calc_result_stars"].format(
                amount=amount, gram=f"{gram:.4f}", usd=f"{gram*gram_price:.2f}"
            )
        else:
            stars = (amount * gram_price) / (star_rate * 0.8)
            text = MESSAGES[lang]["calc_result_gram"].format(
                amount=amount, stars=f"{stars:.0f}"
            )
        await message.answer(text, reply_markup=get_main_kb(lang))
        await state.clear()
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))


# ---------- УВЕДОМЛЕНИЯ О КУРСЕ ----------
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
        await conn.execute(
            "INSERT OR REPLACE INTO gram_alerts (user_id, target_price, enabled, notified) VALUES (?,?,1,0)",
            (message.from_user.id, target)
        )
        await conn.commit()
        await state.clear()
        await message.answer(MESSAGES[lang]["alert_set"].format(price=f"{target:.2f}"), reply_markup=get_main_kb(lang))
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))


# ---------- ДОНАТЫ ----------
@dp.message(F.text.in_(["💎 Поддержать", "💎 Donate"]))
async def donate_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    msgs = MESSAGES[lang]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msgs["donate_stars"], callback_data="donate_stars")],
        [InlineKeyboardButton(text=msgs["donate_top"], callback_data="donate_top")],
        [InlineKeyboardButton(text=msgs["donate_wallet"], callback_data="donate_wallet")],
        [InlineKeyboardButton(text=msgs["cancel"], callback_data="cancel_deal")]
    ])
    await message.answer(msgs["donate_menu"], reply_markup=kb)


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
        await bot.send_invoice(
            chat_id=message.chat.id,
            title="Поддержка бота",
            description=f"Донат {amount} звёзд",
            payload=f"donate_{message.from_user.id}_{amount}",
            currency="XTR",
            prices=[LabeledPrice(label="Донат", amount=amount)],
            provider_token=""
        )
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
    await conn.execute(
        "INSERT INTO donations (user_id, amount, date, telegram_payment_charge_id) VALUES (?,?,?,?)",
        (user_id, amount, datetime.now().strftime("%d.%m.%Y"), message.successful_payment.telegram_payment_charge_id)
    )
    await conn.commit()

    lang = await get_user_lang(user_id)
    await message.answer(MESSAGES[lang]["donate_thanks"].format(amount=amount))
    await log_action(user_id, message.from_user.username or "", "donate", f"{amount} stars")

    main_admin = ADMIN_IDS[0]
    if user_id != main_admin:
        try:
            username = message.from_user.username
            name = message.from_user.first_name or "User"
            user_info = f"@{username}" if username else f"{name} (ID: {user_id})"
            await bot.send_message(
                main_admin,
                MESSAGES["ru"]["donate_admin_notify"].format(
                    user=user_info, amount=amount,
                    date=datetime.now().strftime('%d.%m.%Y %H:%M')
                )
            )
        except:
            pass


@dp.callback_query(F.data == "donate_top")
async def donate_top(callback: CallbackQuery):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    conn = await get_db()
    cur = await conn.execute("""
        SELECT d.user_id, SUM(d.amount) as total, u.username, u.first_name
        FROM donations d
        LEFT JOIN users u ON u.user_id = d.user_id
        GROUP BY d.user_id
        ORDER BY total DESC LIMIT 10
    """)
    rows = await cur.fetchall()
    if not rows:
        await callback.message.answer(MESSAGES[lang]["donate_top_empty"])
        return
    text = MESSAGES[lang]["donate_top_title"] + "\n\n"
    for i, (uid, total, username, first_name) in enumerate(rows, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        if username:
            name = f"@{username}"
        elif first_name:
            name = first_name
        else:
            name = f"ID {uid}"
        text += f"{emoji} {name} — {total} ⭐\n"
    await callback.message.answer(text)


# ---------- ТАЙМЕРЫ ----------
@dp.message(F.text.in_(["⏰ Таймеры", "⏰ Timers"]))
async def timers_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    msgs = MESSAGES[lang]
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM timers WHERE user_id=? AND notified=0 ORDER BY event_time", (message.from_user.id,))
    timers = await cur.fetchall()
    text = msgs["timers_title"] + "\n\n"
    if not timers:
        text += msgs["timers_empty"]
    else:
        for t in timers:
            days_left = max(0, int((t['event_time'] - time.time()) / 86400))
            link = t['nft_link'] or ""
            pending_id = t['pending_id'] if 'pending_id' in t.keys() else None
            pending_tag = f" (отложка #{pending_id})" if pending_id else ""
            if t['event_type'] == 'mint':
                text += msgs["timer_mint_item"].format(link=link, days=days_left) + pending_tag + "\n"
            elif t['event_type'] == 'relist':
                text += msgs["timer_relist_item"].format(link=link, days=days_left) + pending_tag + "\n"
            else:
                text += msgs["timer_unlock_item"].format(days=days_left) + pending_tag + "\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msgs["timer_add_mint"], callback_data="timer_mint")],
        [InlineKeyboardButton(text=msgs["timer_add_unlock"], callback_data="timer_unlock")],
        [InlineKeyboardButton(text=msgs["timer_add_relist"], callback_data="timer_relist")],
        [InlineKeyboardButton(text=msgs["cancel"], callback_data="cancel_deal")]
    ])
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "timer_mint")
async def timer_mint_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await state.update_data(event_type="mint")
    await state.set_state(TimerAdd.waiting_for_nft_link)
    await callback.message.answer(MESSAGES[lang]["timer_enter_nft"], reply_markup=get_cancel_kb(lang))


@dp.callback_query(F.data == "timer_unlock")
async def timer_unlock_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await state.update_data(event_type="unlock")
    await state.set_state(TimerAdd.waiting_for_days)
    await callback.message.answer(MESSAGES[lang]["timer_enter_days"], reply_markup=get_cancel_kb(lang))


@dp.callback_query(F.data == "timer_relist")
async def timer_relist_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await state.update_data(event_type="relist")
    await state.set_state(TimerAdd.waiting_for_nft_link)
    await callback.message.answer(MESSAGES[lang]["timer_enter_nft"], reply_markup=get_cancel_kb(lang))


@dp.message(TimerAdd.waiting_for_nft_link)
async def timer_nft_link_process(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    link = message.text.strip()
    if not link or "t.me/nft" not in link:
        await message.answer(MESSAGES[lang]["timer_invalid_link"], reply_markup=get_cancel_kb(lang))
        return
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
        event_time = time.time() + days * 86400
        conn = await get_db()
        await conn.execute(
            "INSERT INTO timers (user_id, event_type, nft_link, stars_amount, event_time, description) VALUES (?,?,?,?,?,?)",
            (message.from_user.id, data.get("event_type"), data.get("nft_link"), 0, event_time, "")
        )
        await conn.commit()
        await state.clear()
        await log_action(message.from_user.id, message.from_user.username or "", "add_timer", f"{data.get('event_type')}, {days}d")
        await message.answer(MESSAGES[lang]["timer_saved"].format(days=days), reply_markup=get_main_kb(lang))
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))


# ---------- ОТЧЁТЫ О ЗАРАБОТКЕ ----------
@dp.message(Command("reports"))
async def reports_menu(message: Message, state: FSMContext = None):
    if state is not None:
        try:
            await state.clear()
        except:
            pass
    lang = await get_user_lang(message.from_user.id)
    msgs = MESSAGES[lang]
    conn = await get_db()
    cur = await conn.execute("SELECT weekly, monthly, yearly FROM user_earnings_reports WHERE user_id=?", (message.from_user.id,))
    row = await cur.fetchone()
    if not row:
        await conn.execute("INSERT INTO user_earnings_reports (user_id) VALUES (?)", (message.from_user.id,))
        await conn.commit()
        row = (1, 1, 1)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{msgs['reports_weekly']}: {'✅' if row[0] else '❌'}", callback_data="toggle_weekly")],
        [InlineKeyboardButton(text=f"{msgs['reports_monthly']}: {'✅' if row[1] else '❌'}", callback_data="toggle_monthly")],
        [InlineKeyboardButton(text=f"{msgs['reports_yearly']}: {'✅' if row[2] else '❌'}", callback_data="toggle_yearly")],
        [InlineKeyboardButton(text=msgs["cancel"], callback_data="cancel_deal")]
    ])
    await message.answer(msgs["reports_title"], reply_markup=kb)


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

    show_usd = await get_user_show_usd(user_id)

    msgs = MESSAGES[lang]
    text = msgs["settings_title"]
    text += msgs["settings_commission"].format(royalty=f"{royalty:.2f}") + "\n"
    text += msgs["settings_goal"].format(goal=f"{goal:.2f}" if goal else "—") + "\n"
    text += msgs["settings_star_rate"].format(rate=f"{star_rate:.6f}") + "\n"
    text += msgs["settings_change_alert"].format(status="вкл" if change_enabled else "выкл", percent=change_percent) + "\n"
    text += f"💵 Показывать в USD: <b>{'✅ вкл' if show_usd else '❌ выкл'}</b>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"💵 Показывать в USD: {'✅' if show_usd else '❌'}",
            callback_data="toggle_show_usd"
        )],
        [InlineKeyboardButton(text=msgs["settings_change_commission"], callback_data="set_royalty")],
        [InlineKeyboardButton(text=msgs["settings_set_goal"], callback_data="set_goal")],
        [InlineKeyboardButton(text=msgs["settings_star_rate_btn"], callback_data="set_star_rate")],
        [InlineKeyboardButton(text=msgs["settings_change_alert_btn"], callback_data="toggle_change_alert")],
        [InlineKeyboardButton(text=msgs["settings_alert_btn"], callback_data="alert_start")],
        [InlineKeyboardButton(text=msgs["settings_reports_btn"], callback_data="open_reports")],
        [InlineKeyboardButton(text=msgs["settings_close"], callback_data="close_settings")]
    ])
    await message.answer(text, reply_markup=kb)


# ============================================================
# v1.2: переключатель "показывать в USD"
# ============================================================
@dp.callback_query(F.data == "toggle_show_usd")
async def toggle_show_usd_cb(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    current = await get_user_show_usd(uid)
    await set_user_show_usd(uid, not current)
    await log_action(uid, callback.from_user.username or "", "toggle_show_usd", f"{not current}")
    try:
        await callback.message.delete()
    except:
        pass
    await settings(callback.message)


@dp.callback_query(F.data == "close_settings")
async def close_settings(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except:
        pass


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
        await log_action(message.from_user.id, message.from_user.username or "", "set_goal", f"{val} GRAM")
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


# ---------- РЕФЕРАЛЫ ----------
@dp.message(F.text.in_(["👥 Рефералы", "👥 Referrals"]))
async def referrals_menu(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    msgs = MESSAGES[lang]

    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
    invited = (await cur.fetchone())[0] or 0
    cur = await conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND is_active=1", (user_id,))
    active = (await cur.fetchone())[0] or 0
    points = active * 10

    level = get_referral_level(points, lang)
    next_pts = get_next_level_points(points)

    text = msgs["referrals_title"]
    ref_link = f"https://t.me/Stars2ProfitBot?start=ref_{user_id}"
    text += msgs["referrals_link"].format(link=ref_link)
    text += msgs["referrals_stats"].format(invited=invited, active=active, points=points)
    text += msgs["referrals_level"].format(
        level=level,
        next_level=msgs["referrals_next_level"].format(points=next_pts) if next_pts > 0 else "—"
    )

    cur = await conn.execute("""
        SELECT referrer_id, COUNT(*) as cnt FROM referrals
        WHERE is_active=1 AND referrer_id IS NOT NULL
        GROUP BY referrer_id ORDER BY cnt DESC LIMIT 10
    """)
    top_rows = await cur.fetchall()
    if top_rows:
        text += msgs["referrals_top_title"] + "\n"
        for i, (rid, cnt) in enumerate(top_rows, 1):
            cur2 = await conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (rid,))
            urow = await cur2.fetchone()
            if urow:
                username, first_name = urow
                name = f"@{username}" if username else (first_name or f"ID {rid}")
            else:
                name = f"ID {rid}"
            text += f"{i}. {name} — {cnt * 10} очков\n"
    else:
        text += "\n" + msgs["referrals_empty"]

    text += "\n\n" + msgs["referrals_points_per"]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msgs["referrals_share"], url=f"https://t.me/share/url?url={quote(ref_link)}")],
        [InlineKeyboardButton(text=msgs["cancel"], callback_data="cancel_deal")]
    ])
    await message.answer(text, reply_markup=kb)


# ---------- ОТМЕНА И ПОЗЖЕ ----------
@dp.callback_query(F.data == "cancel_deal")
async def cancel_deal(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    lang = await get_user_lang(callback.from_user.id)
    try:
        await callback.message.edit_text(MESSAGES[lang]["cancelled"])
    except:
        await callback.message.answer(MESSAGES[lang]["cancelled"])


@dp.callback_query(F.data == "goal_later")
async def goal_later(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except:
        pass


# ============================================================
# ИНЛАЙН-РЕЖИМ
# ============================================================
def _esc(s):
    if s is None:
        return ""
    return html.escape(str(s))


def inline_bot_keyboard(user_id: int = None):
    if user_id:
        url = f"{BOT_URL}?start=ref_{user_id}"
    else:
        url = BOT_URL
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть бота", url=url)]
    ])


def build_inline_plain(deal: dict, lang: str = "ru") -> str:
    gift_name = deal.get('gift_name') or deal.get('category') or 'NFT'
    return MESSAGES[lang]["inline_loading"].format(gift=gift_name, id=deal['id'])


async def build_inline_html(deal: dict) -> str:
    gift_name = deal.get('gift_name') or deal.get('category') or 'NFT'
    profit = deal.get('profit_gram') or 0
    profit_usd = deal.get('profit_usd') or 0

    gp_buy = deal.get('gram_price_buy') or 0
    gp_sell = deal.get('gram_price_sell') or deal.get('gram_price') or 0

    collection_emoji = get_collection_emoji_html(deal)

    lines = [f"{collection_emoji} <b>{_esc(gift_name)}</b> · Сделка #{deal['id']}"]

    attrs = format_gift_attributes({
        "model": deal.get("model"),
        "model_rarity": deal.get("model_rarity"),
        "model_emoji_id": deal.get("model_emoji_id"),
        "backdrop": deal.get("backdrop"),
        "backdrop_rarity": deal.get("backdrop_rarity"),
        "backdrop_emoji_id": deal.get("backdrop_emoji_id"),
        "symbol": deal.get("symbol"),
        "symbol_rarity": deal.get("symbol_rarity"),
        "symbol_emoji_id": deal.get("symbol_emoji_id"),
    })
    if attrs:
        lines.append("")
        lines.append(attrs)

    lines.append("")
    lines.append(f"{EMOJI_DIAMOND} {deal['buy_amount']} → {deal['sell_amount']} GRAM")

    deal_user_id = deal.get("user_id")
    show_usd = True
    if deal_user_id:
        show_usd = await get_user_show_usd(deal_user_id)

    if show_usd and gp_buy and gp_sell and gp_buy != gp_sell:
        lines.append(f"{EMOJI_DOLLAR} Курс: ${gp_buy:.4f} → ${gp_sell:.4f}")
    elif show_usd and (gp_buy or gp_sell):
        lines.append(f"{EMOJI_DOLLAR} Курс: ${gp_sell or gp_buy:.4f}")

    lines.append(f"{EMOJI_MONEY} <b>{profit:+.4f} GRAM</b>")
    if show_usd:
        lines.append(f"{EMOJI_DOLLAR} <b>{profit_usd:+.2f}$</b>")

    if deal.get('nft_link'):
        lines.append("")
        lines.append(f'{EMOJI_LINK} <a href="{_esc(deal["nft_link"])}">Открыть NFT</a>')

    return "\n".join(lines)


@dp.inline_query()
async def inline_query(inline_query):
    uid = inline_query.from_user.id
    query = (inline_query.query or "").strip()

    results = []

    # v1.2: сначала готовые гифки из gif_cache
    gif_results = await gif_db.gif_search(query, limit=10)
    for g in gif_results:
        if not g.get("mpeg4_file_id"):
            continue
        caption = g.get("caption") or _build_gif_caption(g)
        results.append(InlineQueryResultCachedMpeg4Gif(
            id=f"gif_{g['slug']}",
            mpeg4_file_id=g["mpeg4_file_id"],
            title=g.get("gift_name") or g["slug"],
            caption=caption,
            parse_mode="HTML",
            reply_markup=inline_bot_keyboard(user_id=uid)
        ))

    # сделки пользователя (как раньше)
    conn = await get_db()
    if query.isdigit():
        cur = await conn.execute("SELECT * FROM sales WHERE id=? AND user_id=? ORDER BY id DESC", (int(query), uid))
    else:
        cur = await conn.execute(
            "SELECT * FROM sales WHERE user_id=? AND (category LIKE ? OR gift_name LIKE ?) ORDER BY id DESC LIMIT 10",
            (uid, f"%{query}%", f"%{query}%")
        )
    rows = await cur.fetchall()
    deals = [dict(row) for row in rows]

    for deal_dict in deals:
        gift_name = deal_dict.get('gift_name') or deal_dict.get('category') or 'NFT'
        profit = deal_dict.get('profit_gram') or 0
        profit_usd = deal_dict.get('profit_usd') or 0
        results.append(InlineQueryResultArticle(
            id=f"sale_{deal_dict['id']}",
            title=f"#{deal_dict['id']} {gift_name} ({profit:+.4f} GRAM / {profit_usd:+.2f}$)",
            description=f"Куплено: {deal_dict['buy_amount']} → Продано: {deal_dict['sell_amount']} GRAM",
            input_message_content=InputTextMessageContent(
                message_text=build_inline_plain(deal_dict)
            ),
            reply_markup=inline_bot_keyboard(user_id=uid)
        ))

    if not results:
        results.append(InlineQueryResultArticle(
            id="no_deals",
            title="Ничего не найдено",
            description="У вас пока нет сделок и готовых гифок",
            input_message_content=InputTextMessageContent(message_text="🔍 Нет сделок"),
            reply_markup=inline_bot_keyboard(user_id=uid)
        ))

    await bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=True)


@dp.chosen_inline_result()
async def chosen_inline_result_handler(chosen: ChosenInlineResult):
    if not chosen.inline_message_id:
        return

    # v1.2: гифки не редактируем (уже с caption), только статистика
    if chosen.result_id.startswith("gif_"):
        uid = chosen.from_user.id
        slug = chosen.result_id.replace("gif_", "")
        conn = await get_db()
        try:
            await conn.execute(
                "INSERT INTO inline_stats (user_id, username, first_name, deal_id) VALUES (?,?,?,?)",
                (uid, chosen.from_user.username or "", chosen.from_user.first_name or "", 0)
            )
            await conn.execute(
                "DELETE FROM inline_stats WHERE id NOT IN (SELECT id FROM inline_stats ORDER BY id DESC LIMIT 500)"
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"gif inline stats error: {e}")
        return

    if not chosen.result_id.startswith("sale_"):
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
        await conn.execute(
            "INSERT INTO inline_stats (user_id, username, first_name, deal_id) VALUES (?,?,?,?)",
            (uid, chosen.from_user.username or "", chosen.from_user.first_name or "", deal_id)
        )
        await conn.execute(
            "DELETE FROM inline_stats WHERE id NOT IN (SELECT id FROM inline_stats ORDER BY id DESC LIMIT 500)"
        )
        await conn.commit()
    except Exception as e:
        logger.error(f"inlinestats error: {e}")

    await asyncio.sleep(0.5)

    for i in range(4):
        try:
            await chosen.bot.edit_message_text(
                inline_message_id=chosen.inline_message_id,
                text=await build_inline_html(deal_dict),
                parse_mode="HTML",
                reply_markup=inline_bot_keyboard(user_id=uid)
            )
            logger.info(f"Инлайн-сообщение для сделки #{deal_id} отредактировано")
            break
        except Exception as e:
            logger.warning(f"Попытка {i+1}: {e}")
            await asyncio.sleep(0.4)


# ============================================================
# АДМИН-ПАНЕЛЬ
# ============================================================
@dp.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext = None):
    if state is not None:
        try:
            await state.clear()
        except:
            pass
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
        f"⚙️ <b>Админ-панель Gram2Profit</b> <code>{VERSION}</code>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"📊 Всего сделок: {total_deals or 0}\n"
        f"📅 Сделок сегодня: {today_deals}\n"
        f"💰 Общая прибыль: {total_g or 0:+.4f} GRAM (${total_u or 0:+.2f})\n"
        f"👑 Администраторов: {admin_count}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Генерация гиф", callback_data="admin_gif_panel")],
        [InlineKeyboardButton(text="📊 Расширенная статистика", callback_data="admin_ext_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="📈 Инлайн-статистика", callback_data="admin_inline_stats")],
        [InlineKeyboardButton(text="📋 Логи действий", callback_data="admin_logs")],
        [InlineKeyboardButton(text="🚨 Проверить ошибки", callback_data="admin_errors")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add_admin")],
        [InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin_remove_admin")],
        [InlineKeyboardButton(text="📋 Список админов", callback_data="admin_list_admins")],
        [InlineKeyboardButton(text="💾 Бэкап БД", callback_data="admin_backup")],
        [InlineKeyboardButton(text="⬅️ Закрыть", callback_data="close_admin")]
    ])
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "admin_panel")
async def admin_panel_back(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    try:
        await callback.message.delete()
    except:
        pass
    await show_admin_panel(callback.message)


@dp.callback_query(F.data == "close_admin")
async def close_admin(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except:
        pass


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    conn = await get_db()
    cur = await conn.execute("SELECT user_id, username, first_name, last_name FROM users ORDER BY joined_date DESC LIMIT 20")
    rows = await cur.fetchall()
    text = "👥 <b>Последние пользователи:</b>\n\n"
    for r in rows:
        uid = r[0]
        username = _esc(r[1]) if r[1] else "—"
        first = _esc(r[2]) if r[2] else ""
        last = _esc(r[3]) if r[3] else ""
        text += f"• <code>{uid}</code> {first} {last} (@{username})\n"
    await callback.message.answer(text)


@dp.callback_query(F.data == "admin_ext_stats")
async def admin_ext_stats(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
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
    text += f"• Всего: {total_users}\n"
    text += f"• Новых сегодня: {new_today}\n"
    text += f"• Активных сегодня: {active_today}\n\n"

    text += "━━━ 📈 СДЕЛКИ ━━━\n"
    text += f"• Всего: {total_deals or 0}\n"
    text += f"• Сегодня: {today_deals}\n"
    text += f"• За неделю: {week_deals}\n"
    text += f"• Средняя прибыль: {avg_profit or 0:+.4f} GRAM\n"
    text += f"• Средний чек: {avg_check or 0:.2f} GRAM\n\n"

    text += "━━━ 💰 ПРИБЫЛЬ ━━━\n"
    text += f"• TON: {total_g or 0:+.4f} GRAM\n"
    text += f"• USD: ${total_u or 0:+.2f}\n"
    if best_row:
        text += f"• Лучший день: {_esc(best_row[0])} ({best_row[1]:+.2f} GRAM)\n"
    text += "\n"

    text += "━━━ 📁 ТОП-5 КОЛЛЕКЦИЙ ━━━\n"
    for i, (cat, cnt) in enumerate(top_cols, 1):
        text += f"{i}. {_esc(cat)} — {cnt} сделок\n"
    text += "\n"

    text += "━━━ 👑 ТОП-5 ЮЗЕРОВ ━━━\n"
    for i, (uid, cnt) in enumerate(top_users, 1):
        cur2 = await conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (uid,))
        urow = await cur2.fetchone()
        if urow and urow[0]:
            name = f"@{_esc(urow[0])}"
        elif urow and urow[1]:
            name = _esc(urow[1])
        else:
            name = f"ID {uid}"
        text += f"{i}. {name} — {cnt} сделок\n"

    if inl_row:
        text += f"\n━━━ 📱 ИНЛАЙН-РЕЖИМ ━━━\n"
        text += f"• Уникальных: {inl_row[0]}\n"
        text += f"• Всего отправок: {inl_row[1]}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 По дням", callback_data="adm_stats_days"),
         InlineKeyboardButton(text="📈 По часам", callback_data="adm_stats_hours")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "adm_stats_days")
async def adm_stats_days(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    conn = await get_db()
    cur = await conn.execute(
        "SELECT date, COUNT(*), SUM(profit_gram) FROM sales GROUP BY date ORDER BY id DESC LIMIT 7"
    )
    rows = await cur.fetchall()
    text = "📅 <b>Статистика по дням</b>\n\n"
    for r in reversed(rows):
        text += f"• {_esc(r[0])}: {r[1]} сделок, {r[2] or 0:+.4f} GRAM\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_ext_stats")]])
    await callback.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "adm_stats_hours")
async def adm_stats_hours(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    conn = await get_db()
    cur = await conn.execute(
        "SELECT CAST(strftime('%H', created_at) AS INTEGER) AS h, COUNT(*) FROM sales GROUP BY h ORDER BY h"
    )
    rows = await cur.fetchall()
    text = "📈 <b>Статистика по часам</b>\n\n"
    for r in rows:
        text += f"• {r[0]:02d}:00 — {r[1]} сделок\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_ext_stats")]])
    await callback.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "admin_inline_stats")
async def admin_inline_stats(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    conn = await get_db()

    cur = await conn.execute("SELECT COUNT(DISTINCT user_id), COUNT(*) FROM inline_stats")
    users, total = await cur.fetchone()
    if not total:
        await callback.message.answer("📈 Инлайн-режимом пока никто не пользовался.")
        return

    cur = await conn.execute(
        "SELECT user_id, username, first_name, COUNT(*) FROM inline_stats GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 10"
    )
    top = await cur.fetchall()

    cur = await conn.execute(
        "SELECT user_id, username, first_name, deal_id, timestamp FROM inline_stats ORDER BY id DESC LIMIT 10"
    )
    recent = await cur.fetchall()

    text = "📈 <b>Инлайн-статистика</b>\n\n"
    text += f"👥 Уникальных пользователей: {users}\n"
    text += f"📤 Всего отправок: {total}\n"
    text += "\n🏆 <b>Топ-10 активных:</b>\n"
    for i, (uid, uname, fname, cnt) in enumerate(top, 1):
        if uname:
            name = f"@{_esc(uname)}"
        elif fname:
            name = _esc(fname)
        else:
            name = f"ID {uid}"
        text += f"{i}. {name} — {cnt} отправок\n"

    text += "\n📅 <b>Последние 10 отправок:</b>\n"
    for (uid, uname, fname, deal_id, ts) in recent:
        if uname:
            name = f"@{_esc(uname)}"
        elif fname:
            name = _esc(fname)
        else:
            name = f"ID {uid}"
        text += f"• {name} — сделка #{deal_id} — {_esc(str(ts)[:16])}\n"

    await callback.message.answer(text)


@dp.callback_query(F.data == "admin_logs")
async def admin_logs(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    conn = await get_db()
    cur = await conn.execute("SELECT user_id, username, action, details, timestamp FROM action_logs ORDER BY id DESC LIMIT 20")
    rows = await cur.fetchall()
    if not rows:
        await callback.message.answer("📋 Логов пока нет.")
        return
    text = "📋 <b>Логи действий</b> (последние 20)\n\n"
    for (uid, uname, action, details, ts) in rows:
        if uname:
            name = f"@{_esc(uname)}"
        else:
            name = f"ID {uid}"
        time_str = _esc(str(ts)[11:16]) if ts else ""
        text += f"🕐 {time_str} — {name} — {_esc(action)}\n"
        if details:
            text += f"   <i>{_esc(details)[:200]}</i>\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Очистить лог", callback_data="logs_clear")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])
    await callback.message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "logs_clear")
async def logs_clear(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    conn = await get_db()
    await conn.execute("DELETE FROM action_logs")
    await conn.commit()
    await callback.message.answer("✅ Логи действий очищены.")


@dp.callback_query(F.data == "admin_errors")
async def admin_errors(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    await show_errors_menu(callback.message)


async def show_errors_menu(message: Message):
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM error_logs")
    total = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM error_logs WHERE reported=0")
    new = (await cur.fetchone())[0]
    day_ago = time.time() - 86400
    cur = await conn.execute("SELECT COUNT(*) FROM error_logs WHERE timestamp >= datetime(?, 'unixepoch')", (day_ago,))
    last24 = (await cur.fetchone())[0]

    if total == 0:
        text = "🚨 <b>Лог ошибок</b>\n\n✅ Ошибок нет. Всё работает стабильно."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]])
        await message.answer(text, reply_markup=kb)
        return

    text = "🚨 <b>Лог ошибок</b>\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📊 Всего ошибок: {total}\n"
    text += f"🆕 Новых: {new}\n"
    text += f"📅 За последние 24ч: {last24}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n\n"

    cur = await conn.execute("SELECT error_type, details, timestamp FROM error_logs ORDER BY id DESC LIMIT 5")
    rows = await cur.fetchall()
    for (etype, details, ts) in rows:
        text += f"⚠️ <b>{_esc(etype)}</b> — {_esc(str(ts)[:16])}\n"
        text += f"<i>{_esc(details)[:300]}</i>\n\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Скопировать логи", callback_data="errors_copy")],
        [InlineKeyboardButton(text="📤 Скачать файл", callback_data="errors_download")],
        [InlineKeyboardButton(text="🗑 Очистить лог", callback_data="errors_clear")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "errors_copy")
async def errors_copy(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    conn = await get_db()
    cur = await conn.execute("SELECT error_type, details, timestamp FROM error_logs ORDER BY id DESC LIMIT 20")
    rows = await cur.fetchall()
    logs = f"🚨 ЛОГ ОШИБОК — {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
    logs += "━━━━━━━━━━━━━━━━━━━━━\n"
    logs += f"Всего: {len(rows)}\n\n"
    for i, (etype, details, ts) in enumerate(rows, 1):
        logs += f"[{i}] ⚠️ {etype} — {str(ts)[:16]}\n"
        logs += f"{details[:500]}\n\n"
    logs += "━━━━━━━━━━━━━━━━━━━━━"

    safe = html.escape(logs)
    if len(safe) > 3500:
        safe = safe[:3500] + "\n... (обрезано)"

    await callback.message.answer(
        f"📋 <b>Логи для копирования</b>\n\nНажмите на текст ниже — он скопируется.\n\n<code>{safe}</code>"
    )


@dp.callback_query(F.data == "errors_download")
async def errors_download(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    conn = await get_db()
    cur = await conn.execute("SELECT error_type, details, timestamp FROM error_logs ORDER BY id DESC LIMIT 100")
    rows = await cur.fetchall()
    if not rows:
        await callback.message.answer("Нет ошибок.")
        return

    filename = f"error_logs_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.txt"
    content = "🚨 ЛОГ ОШИБОК\n"
    content += f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
    content += f"Всего: {len(rows)}\n\n"
    for i, (etype, details, ts) in enumerate(rows, 1):
        content += "━━━━━━━━━━━━━━━━━━━━━\n"
        content += f"[{i}] {etype}\n"
        content += f"Время: {ts}\n"
        content += f"Детали: {details}\n\n"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    try:
        await callback.message.answer_document(
            FSInputFile(filename),
            caption=f"📤 Файл с логами ошибок ({len(rows)} записей)"
        )
    except:
        pass

    try:
        Path(filename).unlink()
    except:
        pass


@dp.callback_query(F.data == "errors_clear")
async def errors_clear(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    conn = await get_db()
    await conn.execute("DELETE FROM error_logs")
    await conn.commit()
    await callback.message.answer("✅ Лог ошибок очищен.")


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_for_message)
    lang = await get_user_lang(callback.from_user.id)
    await callback.message.answer("📢 Введите текст для рассылки:", reply_markup=get_cancel_kb(lang))


@dp.message(BroadcastState.waiting_for_message)
async def do_broadcast(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    conn = await get_db()
    cur = await conn.execute("SELECT user_id FROM users")
    users = [row[0] async for row in cur]
    success = 0
    for uid in users:
        try:
            await bot.send_message(uid, message.text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await state.clear()
    await message.answer(f"✅ Рассылка завершена: {success}/{len(users)}")
    await log_action(message.from_user.id, message.from_user.username or "", "broadcast", f"sent={success}/{len(users)}")


@dp.callback_query(F.data == "admin_add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(AddAdminState.waiting_for_id)
    lang = await get_user_lang(callback.from_user.id)
    await callback.message.answer("Введите Telegram ID нового администратора:", reply_markup=get_cancel_kb(lang))


@dp.message(AddAdminState.waiting_for_id)
async def add_admin_finish(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        new_id = int(message.text.strip())
        await add_admin(new_id)
        await message.answer(f"✅ Администратор {new_id} добавлен.")
        await log_action(message.from_user.id, message.from_user.username or "", "add_admin", f"id={new_id}")
    except:
        await message.answer("❌ Введите корректный числовой ID.")
    await state.clear()


@dp.callback_query(F.data == "admin_remove_admin")
async def remove_admin_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(RemoveAdminState.waiting_for_id)
    lang = await get_user_lang(callback.from_user.id)
    await callback.message.answer("Введите Telegram ID для удаления:", reply_markup=get_cancel_kb(lang))


@dp.message(RemoveAdminState.waiting_for_id)
async def remove_admin_finish(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        rem_id = int(message.text.strip())
        await remove_admin(rem_id)
        await message.answer(f"✅ Администратор {rem_id} удалён.")
        await log_action(message.from_user.id, message.from_user.username or "", "remove_admin", f"id={rem_id}")
    except:
        await message.answer("❌ Введите корректный числовой ID.")
    await state.clear()


@dp.callback_query(F.data == "admin_list_admins")
async def list_admins(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    conn = await get_db()
    cur = await conn.execute("SELECT user_id FROM admins")
    ids = [str(row[0]) async for row in cur]
    await callback.message.answer("👑 <b>Администраторы:</b>\n" + "\n".join(ids))


@dp.callback_query(F.data == "admin_backup")
async def admin_backup(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    try:
        await create_and_send_backup(callback.from_user.id)
    except Exception as e:
        await callback.message.answer("❌ Ошибка создания бэкапа.")
        logger.error(f"Backup error: {e}")


async def create_and_send_backup(admin_id: int):
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"sales_backup_{date_str}.db"
    shutil.copy(DB_PATH, filename)

    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM users")
    users_count = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM sales")
    deals_count = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM donations")
    donations_count = (await cur.fetchone())[0]

    size_kb = Path(filename).stat().st_size / 1024

    caption = "💾 <b>Бэкап БД</b>\n\n"
    caption += f"📅 Дата: {date_str}\n📁 Файл: {filename}\n📊 Размер: {size_kb:.1f} КБ\n\n"
    caption += f"📈 <b>Содержимое:</b>\n• Пользователей: {users_count}\n• Сделок: {deals_count}\n• Донатов: {donations_count}\n"

    try:
        await bot.send_document(admin_id, FSInputFile(filename), caption=caption)
    except:
        pass

    try:
        Path(filename).unlink()
    except:
        pass


# ============================================================
# v1.2: АДМИН-ПАНЕЛЬ ГИФОК
# ============================================================

@dp.callback_query(F.data == "admin_gif_panel")
async def admin_gif_panel(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    await show_gif_panel(callback.message)


async def show_gif_panel(message: Message):
    counts = await gif_db.gif_count_by_status()
    pending = counts.get("pending", 0)
    ready = counts.get("ready", 0)
    error = counts.get("error", 0)

    text = (
        f"🎬 <b>Генерация гиф</b>\n\n"
        f"📊 Статус кэша:\n"
        f"• ⏳ В процессе: <b>{pending}</b>\n"
        f"• ✅ Готово: <b>{ready}</b>\n"
        f"• ❌ Ошибок: <b>{error}</b>\n\n"
        f"Выбери действие:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Сгенерировать гифку", callback_data="gif_add_start")],
        [InlineKeyboardButton(text="📋 Готовые гифки", callback_data="gif_list_ready")],
        [InlineKeyboardButton(text="⏳ В процессе", callback_data="gif_list_pending")],
        [InlineKeyboardButton(text="❌ Ошибки", callback_data="gif_list_error")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")],
    ])
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "gif_add_start")
async def gif_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(AdminGifAdd.waiting_for_link)
    lang = await get_user_lang(callback.from_user.id)
    await callback.message.answer(
        "🔗 <b>Введи ссылку на NFT</b>\n\n"
        "Пример: <code>https://t.me/nft/DurovsCap-4074</code>\n\n"
        "Бот скачает Lottie, отрендерит MP4 и запишет в кэш.\n"
        "Это займёт 30–120 секунд.",
        reply_markup=get_cancel_kb(lang)
    )


@dp.message(AdminGifAdd.waiting_for_link)
async def gif_add_process(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    lang = await get_user_lang(message.from_user.id)

    link = message.text.strip()
    slug_full, slug_short, number = _extract_slug_from_link(link)
    if not slug_full or number is None:
        await message.answer(
            "❌ Неверная ссылка. Пример: <code>https://t.me/nft/DurovsCap-4074</code>",
            reply_markup=get_cancel_kb(lang)
        )
        return

    await state.clear()

    existing = await gif_db.gif_get(slug_full)
    if existing and existing.get("status") == "ready":
        await message.answer(
            f"✅ Гифка <code>{slug_full}</code> уже в кэше.\n\n"
            f"file_id: <code>{existing['mpeg4_file_id'][:40]}...</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👁 Открыть карточку", callback_data=f"gif_view_{slug_full}")],
                [InlineKeyboardButton(text="🔄 Перегенерировать", callback_data=f"gif_regen_{slug_full}")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_gif_panel")],
            ])
        )
        return

    status_msg = await message.answer(f"⏳ Рендерю <code>{slug_full}</code>... Это может занять до 2 минут.")

    nft_data = await parse_nft_link(link) or {"gift_name": slug_short}

    try:
        await gif_db.gif_set_pending(
            slug_full, link,
            nft_data.get("gift_name") or slug_short,
            message.from_user.id,
            params_json=json.dumps(gif_renderer.DEFAULT_PARAMS)
        )

        mp4_path, work_dir = await gif_renderer.render_to_tempfile(slug_short)
        msg = await bot.send_animation(
            chat_id=ADMIN_IDS[0],
            animation=FSInputFile(str(mp4_path), filename=f"{slug_full}.mp4"),
            caption=f"🎬 {nft_data.get('gift_name', slug_short)}",
            request_timeout=300
        )

        file_id = None
        if msg.animation:
            file_id = msg.animation.file_id
        elif msg.document:
            file_id = msg.document.file_id

        try:
            await bot.delete_message(chat_id=ADMIN_IDS[0], message_id=msg.message_id)
        except:
            pass

        if not file_id:
            raise RuntimeError("Telegram не вернул file_id")

        caption = _build_gif_caption(nft_data)
        await gif_db.gif_set_ready(slug_full, file_id, nft_data, caption,
                                    params_json=json.dumps(gif_renderer.DEFAULT_PARAMS))

        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except:
            pass

        await status_msg.edit_text(
            f"✅ <b>Готово!</b>\n\n"
            f"<code>{slug_full}</code>\n"
            f"file_id: <code>{file_id[:40]}...</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👁 Открыть карточку", callback_data=f"gif_view_{slug_full}")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_gif_panel")],
            ])
        )
    except Exception as e:
        logger.exception(f"[admin gif] {slug_full}: {e}")
        await gif_db.gif_set_error(slug_full, str(e)[:1000])
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except:
            pass
        await status_msg.edit_text(
            f"❌ <b>Ошибка рендера</b>\n\n<code>{e}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data=f"gif_regen_{slug_full}")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_gif_panel")],
            ])
        )


@dp.callback_query(F.data.in_(["gif_list_ready", "gif_list_pending", "gif_list_error"]))
async def gif_list_handler(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return

    status = callback.data.replace("gif_list_", "")
    rows = await gif_db.gif_list(status=status, limit=20)

    if not rows:
        await callback.message.answer(
            f"📭 Список <b>{status}</b> пуст.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_gif_panel")]
            ])
        )
        return

    text = f"📋 <b>{status.upper()}</b> ({len(rows)}):\n\n"
    kb_rows = []
    for r in rows:
        name = r.get("gift_name") or r["slug"]
        snippet = r.get("error", "")[:60] if r.get("error") else ""
        text += f"• <code>{r['slug']}</code> — {html.escape(name)}\n"
        if snippet:
            text += f"  <i>{html.escape(snippet)}</i>\n"
        kb_rows.append([
            InlineKeyboardButton(text=f"👁 {r['slug'][:20]}", callback_data=f"gif_view_{r['slug']}")
        ])

    kb_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_gif_panel")])
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@dp.callback_query(F.data.startswith("gif_view_"))
async def gif_view(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return

    slug = callback.data.replace("gif_view_", "")
    row = await gif_db.gif_get(slug)
    if not row:
        await callback.message.answer("❌ Гифка не найдена.")
        return

    text = (
        f"🎬 <b>{html.escape(row.get('gift_name') or slug)}</b>\n"
        f"<code>{slug}</code>\n\n"
        f"📊 Статус: <b>{row.get('status')}</b>\n"
    )
    if row.get("mpeg4_file_id"):
        text += f"🆔 <code>{row['mpeg4_file_id'][:50]}...</code>\n"
    if row.get("error"):
        text += f"❌ Ошибка: <code>{html.escape(row['error'][:200])}</code>\n"
    if row.get("model"):
        text += f"🎨 Модель: {html.escape(row['model'])} {row.get('model_rarity') or ''}\n"
    if row.get("backdrop"):
        text += f"⚫ Фон: {html.escape(row['backdrop'])} {row.get('backdrop_rarity') or ''}\n"
    if row.get("symbol"):
        text += f"🌸 Узор: {html.escape(row['symbol'])} {row.get('symbol_rarity') or ''}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать метаданные", callback_data=f"gif_edit_meta_{slug}")],
        [InlineKeyboardButton(text="⚙️ Параметры рендера", callback_data=f"gif_edit_params_{slug}")],
        [InlineKeyboardButton(text="🔄 Перегенерировать", callback_data=f"gif_regen_{slug}")],
        [InlineKeyboardButton(text="🗑 Удалить из кэша", callback_data=f"gif_delete_{slug}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_gif_panel")],
    ])
    await callback.message.answer(text, reply_markup=kb)

    if row.get("mpeg4_file_id") and row.get("status") == "ready":
        try:
            await bot.send_animation(
                chat_id=callback.from_user.id,
                animation=row["mpeg4_file_id"],
                caption=f"🎬 {row.get('gift_name') or slug}"
            )
        except:
            pass


META_FIELDS = {
    "gift_name": "Название (gift_name)",
    "model": "Модель",
    "backdrop": "Фон",
    "symbol": "Узор",
    "model_rarity": "Редкость модели",
    "backdrop_rarity": "Редкость фона",
    "symbol_rarity": "Редкость узора",
    "caption": "Подпись под гифкой (HTML)",
}


@dp.callback_query(F.data.startswith("gif_edit_meta_"))
async def gif_edit_meta(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    slug = callback.data.replace("gif_edit_meta_", "")
    kb_rows = []
    for field, label in META_FIELDS.items():
        kb_rows.append([InlineKeyboardButton(text=label, callback_data=f"gif_edit_field_{slug}_{field}")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gif_view_{slug}")])
    await callback.message.answer(
        f"✏️ <b>Что редактируем?</b> <code>{slug}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )


@dp.callback_query(F.data.startswith("gif_edit_field_"))
async def gif_edit_field(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    parts = callback.data.replace("gif_edit_field_", "").rsplit("_", 1)
    slug, field = parts[0], parts[1]

    await state.set_state(AdminGifEditMeta.waiting_for_value)
    await state.update_data(edit_slug=slug, edit_field=field)

    current = await gif_db.gif_get(slug)
    cur_val = (current or {}).get(field, "")
    label = META_FIELDS.get(field, field)

    await callback.message.answer(
        f"✏️ <b>{label}</b>\n\n"
        f"Текущее значение: <code>{html.escape(str(cur_val))}</code>\n\n"
        f"Введи новое значение:",
        reply_markup=get_cancel_kb(await get_user_lang(callback.from_user.id))
    )


@dp.message(AdminGifEditMeta.waiting_for_value)
async def gif_edit_value(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    data = await state.get_data()
    slug = data.get("edit_slug")
    field = data.get("edit_field")
    value = message.text.strip()
    if not slug or not field:
        await state.clear()
        return

    await gif_db.gif_update_meta(slug, {field: value})
    await state.clear()
    await message.answer(
        f"✅ <code>{slug}</code> → <b>{field}</b> = <code>{html.escape(value)}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👁 Открыть карточку", callback_data=f"gif_view_{slug}")],
            [InlineKeyboardButton(text="⬅️ В админ-панель гиф", callback_data="admin_gif_panel")],
        ])
    )


PARAM_FIELDS = {
    "card_w": "Ширина (px)",
    "card_h": "Высота (px)",
    "fps": "FPS",
    "frame_skip": "FRAME_SKIP",
    "crf": "CRF (качество)",
    "preset": "Preset (x264)",
}


@dp.callback_query(F.data.startswith("gif_edit_params_"))
async def gif_edit_params(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    slug = callback.data.replace("gif_edit_params_", "")
    row = await gif_db.gif_get(slug)
    params = gif_renderer.DEFAULT_PARAMS
    if row and row.get("params_json"):
        try:
            params = {**gif_renderer.DEFAULT_PARAMS, **json.loads(row["params_json"])}
        except:
            pass

    text = f"⚙️ <b>Параметры рендера</b> <code>{slug}</code>\n\n"
    for k, v in params.items():
        text += f"• <b>{k}</b>: <code>{v}</code>\n"
    text += "\nЧто меняем?"

    kb_rows = []
    for field, label in PARAM_FIELDS.items():
        kb_rows.append([InlineKeyboardButton(text=label, callback_data=f"gif_param_field_{slug}_{field}")])
    kb_rows.append([InlineKeyboardButton(text="🔄 Перегенерировать", callback_data=f"gif_regen_{slug}")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gif_view_{slug}")])
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@dp.callback_query(F.data.startswith("gif_param_field_"))
async def gif_param_field(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    parts = callback.data.replace("gif_param_field_", "").rsplit("_", 1)
    slug, field = parts[0], parts[1]

    await state.set_state(AdminGifEditParams.waiting_for_value)
    await state.update_data(edit_slug=slug, edit_field=field)

    label = PARAM_FIELDS.get(field, field)
    await callback.message.answer(
        f"⚙️ <b>{label}</b>\n\n"
        f"Введи новое значение (число или строка):",
        reply_markup=get_cancel_kb(await get_user_lang(callback.from_user.id))
    )


@dp.message(AdminGifEditParams.waiting_for_value)
async def gif_param_value(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    data = await state.get_data()
    slug = data.get("edit_slug")
    field = data.get("edit_field")
    raw = message.text.strip()
    if not slug or not field:
        await state.clear()
        return

    new_val = raw
    if field in ("card_w", "card_h", "fps", "frame_skip", "crf"):
        try:
            new_val = int(raw)
        except:
            await message.answer("❌ Нужно целое число.", reply_markup=get_cancel_kb(await get_user_lang(message.from_user.id)))
            return

    row = await gif_db.gif_get(slug)
    params = gif_renderer.DEFAULT_PARAMS
    if row and row.get("params_json"):
        try:
            params = {**gif_renderer.DEFAULT_PARAMS, **json.loads(row["params_json"])}
        except:
            pass
    params[field] = new_val

    conn = await get_db()
    await conn.execute(
        "UPDATE gif_cache SET params_json=?, updated_at=CURRENT_TIMESTAMP WHERE slug=?",
        (json.dumps(params), slug)
    )
    await conn.commit()

    await state.clear()
    await message.answer(
        f"✅ <code>{slug}</code> → <b>{field}</b> = <code>{new_val}</code>\n\n"
        f"Не забудь перегенерировать.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Перегенерировать", callback_data=f"gif_regen_{slug}")],
            [InlineKeyboardButton(text="👁 Карточка", callback_data=f"gif_view_{slug}")],
        ])
    )


@dp.callback_query(F.data.startswith("gif_regen_"))
async def gif_regen(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    slug_full = callback.data.replace("gif_regen_", "")
    row = await gif_db.gif_get(slug_full)
    if not row:
        await callback.message.answer("❌ Не найдено.")
        return

    slug_short = slug_full.rsplit("-", 1)[0]
    params = gif_renderer.DEFAULT_PARAMS
    if row.get("params_json"):
        try:
            params = {**gif_renderer.DEFAULT_PARAMS, **json.loads(row["params_json"])}
        except:
            pass

    status_msg = await callback.message.answer(f"⏳ Перегенерирую <code>{slug_full}</code> с параметрами:\n<code>{json.dumps(params)}</code>")

    try:
        await gif_db.gif_set_pending(
            slug_full, row.get("nft_link") or "",
            row.get("gift_name") or slug_short,
            callback.from_user.id,
            params_json=json.dumps(params)
        )

        mp4_path, work_dir = await gif_renderer.render_to_tempfile(slug_short, params=params)
        msg = await bot.send_animation(
            chat_id=ADMIN_IDS[0],
            animation=FSInputFile(str(mp4_path), filename=f"{slug_full}.mp4"),
            caption=f"🎬 {row.get('gift_name', slug_short)}",
            request_timeout=300
        )

        file_id = None
        if msg.animation:
            file_id = msg.animation.file_id
        elif msg.document:
            file_id = msg.document.file_id

        try:
            await bot.delete_message(chat_id=ADMIN_IDS[0], message_id=msg.message_id)
        except:
            pass

        if not file_id:
            raise RuntimeError("Telegram не вернул file_id")

        await gif_db.gif_set_ready(slug_full, file_id, row, row.get("caption") or "", json.dumps(params))
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except:
            pass

        await status_msg.edit_text(
            f"✅ <b>Перегенерировано!</b>\n\n<code>{slug_full}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👁 Карточка", callback_data=f"gif_view_{slug_full}")],
                [InlineKeyboardButton(text="⬅️ В админ-панель гиф", callback_data="admin_gif_panel")],
            ])
        )
    except Exception as e:
        logger.exception(f"[regen] {slug_full}: {e}")
        await gif_db.gif_set_error(slug_full, str(e)[:1000])
        await status_msg.edit_text(f"❌ Ошибка: <code>{html.escape(str(e)[:300])}</code>")


@dp.callback_query(F.data.startswith("gif_delete_"))
async def gif_delete(callback: CallbackQuery):
    await callback.answer()
    if not await is_admin(callback.from_user.id):
        return
    slug = callback.data.replace("gif_delete_", "")
    await gif_db.gif_delete(slug)
    await callback.message.answer(
        f"🗑 <code>{slug}</code> удалён из кэша.\n\n"
        f"⚠️ В чатах, куда уже отправлена гифка, она останется (Telegram её хранит).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В админ-панель гиф", callback_data="admin_gif_panel")],
        ])
    )


# ============================================================
# ФОНОВЫЕ ЗАДАЧИ
# ============================================================
async def check_alerts():
    while True:
        try:
            price = await get_gram_price()
            conn = await get_db()
            cur = await conn.execute("SELECT user_id, target_price FROM gram_alerts WHERE enabled=1 AND notified=0")
            rows = await cur.fetchall()
            for row in rows:
                if price >= row[1]:
                    try:
                        lang = await get_user_lang(row[0])
                        await bot.send_message(
                            row[0],
                            MESSAGES[lang]["alert_triggered"].format(
                                price=f"{price:.4f}", target=f"{row[1]:.2f}"
                            )
                        )
                        await conn.execute("UPDATE gram_alerts SET notified=1 WHERE user_id=?", (row[0],))
                        await conn.commit()
                    except:
                        pass
        except Exception as e:
            logger.error(f"Alert check error: {e}")
        await asyncio.sleep(300)


async def check_price_changes():
    while True:
        try:
            price = await get_gram_price()
            now = time.time()
            conn = await get_db()
            await conn.execute("INSERT OR REPLACE INTO gram_price_log (timestamp, price) VALUES (?,?)", (now, price))
            await conn.commit()
            day_ago = now - 86400
            cur = await conn.execute("SELECT price FROM gram_price_log WHERE timestamp <= ? ORDER BY timestamp DESC LIMIT 1", (day_ago,))
            old_row = await cur.fetchone()
            if old_row:
                old_price = old_row[0]
                change_pct = abs(price - old_price) / old_price * 100
                cur2 = await conn.execute("SELECT user_id, percent, disabled_until FROM user_change_alerts WHERE enabled=1")
                rows = await cur2.fetchall()
                for row in rows:
                    uid, percent, disabled_until = row
                    if disabled_until and disabled_until > now:
                        continue
                    if change_pct >= percent:
                        try:
                            lang = await get_user_lang(uid)
                            direction = "вырос" if price > old_price else "упал"
                            await bot.send_message(uid, MESSAGES[lang]["price_change"].format(
                                direction=direction, pct=f"{change_pct:.1f}",
                                price=f"{price:.4f}", old_price=f"{old_price:.4f}"
                            ))
                        except:
                            pass
        except Exception as e:
            logger.error(f"Price change check error: {e}")
        await asyncio.sleep(300)


async def check_timers():
    while True:
        try:
            now = time.time()
            conn = await get_db()
            cur = await conn.execute("SELECT * FROM timers WHERE notified=0 AND event_time <= ?", (now,))
            rows = await cur.fetchall()
            for row in rows:
                try:
                    lang = await get_user_lang(row['user_id'])
                    if row['event_type'] == 'mint':
                        text = MESSAGES[lang]["timer_mint_notify"].format(link=row['nft_link'] or "—")
                    elif row['event_type'] == 'relist':
                        text = MESSAGES[lang]["timer_relist_notify"].format(link=row['nft_link'] or "—")
                    else:
                        text = MESSAGES[lang]["timer_unlock_notify"]
                    await bot.send_message(row['user_id'], text)
                    await conn.execute("UPDATE timers SET notified=1 WHERE id=?", (row['id'],))
                    await conn.commit()
                except:
                    pass
        except Exception as e:
            logger.error(f"Timer check error: {e}")
        await asyncio.sleep(300)


async def send_earnings_reports():
    while True:
        try:
            now = datetime.now()
            if now.hour == 12:
                conn = await get_db()
                if now.weekday() == 0:
                    await send_report(conn, "weekly", 7, "неделю")
                if now.day == 1:
                    await send_report(conn, "monthly", 30, "месяц")
                if now.day == 1 and now.month == 1:
                    await send_report(conn, "yearly", 365, "год")
        except Exception as e:
            logger.error(f"Earnings report error: {e}")
        await asyncio.sleep(3600)


async def send_report(conn, report_type, days, period_name):
    cur = await conn.execute(f"SELECT user_id FROM user_earnings_reports WHERE {report_type}=1")
    users = await cur.fetchall()
    since = time.time() - days * 86400
    for (user_id,) in users:
        try:
            cur2 = await conn.execute(
                "SELECT SUM(profit_gram), SUM(profit_usd) FROM sales WHERE user_id=? AND created_at >= datetime(?, 'unixepoch')",
                (user_id, since)
            )
            total_g, total_u = await cur2.fetchone()
            total_g = total_g or 0
            total_u = total_u or 0
            if total_g != 0 or total_u != 0:
                lang = await get_user_lang(user_id)
                await bot.send_message(
                    user_id,
                    f"📊 <b>Отчёт о заработке</b>\n\n"
                    f"За период ({period_name}) вы заработали:\n"
                    f"💰 <b>{total_g:.4f} GRAM</b>\n"
                    f"{EMOJI_DOLLAR} <b>{total_u:+.2f}$</b>\n\n"
                    f"Продолжайте в том же духе!"
                )
        except:
            pass


async def daily_backup_task():
    last_backup_date = None
    while True:
        try:
            now = datetime.utcnow()
            current_date = now.strftime("%Y-%m-%d")
            if now.hour == 3 and last_backup_date != current_date:
                main_admin = ADMIN_IDS[0]
                try:
                    await create_and_send_backup(main_admin)
                    last_backup_date = current_date
                    logger.info(f"Daily backup sent to {main_admin}")
                except Exception as e:
                    logger.error(f"Daily backup error: {e}")
        except Exception as e:
            logger.error(f"Backup task error: {e}")
        await asyncio.sleep(300)


async def send_startup_errors():
    try:
        conn = await get_db()
        day_ago = time.time() - 86400
        cur = await conn.execute(
            "SELECT COUNT(*) FROM error_logs WHERE timestamp >= datetime(?, 'unixepoch')",
            (day_ago,)
        )
        count = (await cur.fetchone())[0]
        if count > 0:
            main_admin = ADMIN_IDS[0]
            text = (
                f"🚨 <b>Ошибки при прошлом запуске</b>\n\n"
                f"Найдено: {count} ошибок за последние 24 часа.\n\n"
                f"Откройте админ-панель → «🚨 Проверить ошибки» для подробностей."
            )
            try:
                await bot.send_message(main_admin, text)
            except:
                pass
    except Exception as e:
        logger.error(f"Startup errors send error: {e}")


# ============================================================
# ЗАПУСК
# ============================================================
async def main():
    logger.info(f"🚀 Бот запускается... {VERSION}")
    await init_db()

    # v1.2: запускаем Chromium для рендера гифок
    try:
        await gif_renderer.init_browser()
    except Exception as e:
        logger.error(f"⚠️ Не удалось запустить Chromium: {e}")
        logger.error("Гифки не будут рендериться. Проверь установку chromium.")

    asyncio.create_task(check_alerts())
    asyncio.create_task(check_price_changes())
    asyncio.create_task(check_timers())
    asyncio.create_task(send_earnings_reports())
    asyncio.create_task(daily_backup_task())
    await send_startup_errors()

    logger.info("🤖 Бот запущен!")
    try:
        await dp.start_polling(bot)
    finally:
        await gif_renderer.close_browser()


if __name__ == "__main__":
    asyncio.run(main())
        
