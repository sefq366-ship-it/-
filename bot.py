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
from widgets import (
    handle_widget_query_raw, 
    send_widget_raw, 
    STATS_WIDGET_HTML, 
    DONATE_WIDGET_HTML, 
    SETTINGS_WIDGET_HTML,
    CALC_WIDGET_HTML
)

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
BOT_TOKEN = "9A"
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
        # База данных больше не очищается при перезапуске!
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
        if not row: return f"ID {user_id}"
        if row[0]: return f"@{row[0]}"
        if row[1]: return _esc(row[1])
        return f"ID {user_id}"
    except: return f"ID {user_id}"

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
        gp_buy = float(gram_price_buy or 0); gp_sell = float(gram_price_sell or 0)
        if gp_buy > 0 and gp_sell > 0:
            cost_usd = float(buy_amount) * gp_buy
            revenue_usd = float(sell_amount) * gp_sell
            royalty_usd = float(royalty or 0) * gp_sell
            return round(revenue_usd - cost_usd - royalty_usd, 2)
        profit_gram = float(sell_amount) - float(buy_amount) - float(royalty or 0)
        gp = float(fallback_gram_price or 0)
        return round(profit_gram * gp, 2)
    except: return 0.0

def get_profit_emoji(p):
    if p > 1: return "🚀"
    elif p > 0.5: return "💎"
    elif p > 0: return "📈"
    elif p == 0: return "➖"
    elif p > -0.5: return "📉"
    else: return "💀"

def make_progress_bar(value, max_value, length=12):
    if max_value <= 0: return "░" * length + " 0%"
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
    await conn.execute("INSERT OR REPLACE INTO user_royalty (user_id, royalty_gram, updated_at) VALUES (?,?,datetime('now'))", (user_id, float(royalty_gram)))
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

def _esc(s):
    if s is None: return ""
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
        if catalog_by_slug: catalog = catalog_by_slug
    source_data = await get_gift_from_fragment(slug, number)
    if not source_data: source_data = await get_gift_from_tme(nft_link)
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
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]])

async def init_db():
    conn = await get_db()

    await conn.executescript('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, category TEXT, nft_link TEXT, nft_image TEXT,
            thumb_file_id TEXT, nft_name TEXT, date TEXT, buy_amount REAL, sell_amount REAL, gram_price REAL DEFAULT 0,
            gram_price_buy REAL DEFAULT 0, gram_price_sell REAL DEFAULT 0, profit_gram REAL, profit_usd REAL,
            royalty_gram REAL DEFAULT 0, gift_name TEXT, model TEXT, model_rarity TEXT, model_emoji_id TEXT,
            backdrop TEXT, backdrop_rarity TEXT, backdrop_emoji_id TEXT, symbol TEXT, symbol_rarity TEXT,
            symbol_emoji_id TEXT, collection_emoji_id TEXT, gif_file_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pending_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, category TEXT, nft_link TEXT, nft_image TEXT,
            thumb_file_id TEXT, date TEXT, buy_amount REAL, gram_price REAL DEFAULT 0, gram_price_buy REAL DEFAULT 0,
            royalty_gram REAL DEFAULT 0, gift_name TEXT, model TEXT, model_rarity TEXT, model_emoji_id TEXT,
            backdrop TEXT, backdrop_rarity TEXT, backdrop_emoji_id TEXT, symbol TEXT, symbol_rarity TEXT,
            symbol_emoji_id TEXT, collection_emoji_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_royalty (user_id INTEGER PRIMARY KEY, royalty_gram REAL DEFAULT 0.3, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, joined_date TIMESTAMP, last_activity TIMESTAMP, referred_by INTEGER);
        CREATE TABLE IF NOT EXISTS profit_goals (user_id INTEGER PRIMARY KEY, goal_gram REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, notified INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS gram_alerts (user_id INTEGER PRIMARY KEY, target_price REAL, enabled INTEGER DEFAULT 1, notified INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS user_star_rates (user_id INTEGER PRIMARY KEY, star_rate REAL DEFAULT 0.013, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS user_change_alerts (user_id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 0, percent REAL DEFAULT 5.0, disabled_until REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS gram_price_log (timestamp REAL PRIMARY KEY, price REAL);
        CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS user_settings (user_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'ru');
        CREATE TABLE IF NOT EXISTS donations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount INTEGER NOT NULL, date TEXT, telegram_payment_charge_id TEXT);
        CREATE TABLE IF NOT EXISTS timers (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, event_type TEXT, nft_link TEXT, stars_amount INTEGER, event_time REAL, description TEXT, notified INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS user_earnings_reports (user_id INTEGER PRIMARY KEY, weekly INTEGER DEFAULT 1, monthly INTEGER DEFAULT 1, yearly INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS user_collections (user_id INTEGER, collection_name TEXT, last_used TIMESTAMP, use_count INTEGER DEFAULT 1, PRIMARY KEY (user_id, collection_name));
        CREATE TABLE IF NOT EXISTS referrals (user_id INTEGER PRIMARY KEY, referrer_id INTEGER, date_joined TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_active INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS action_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, action TEXT, details TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS inline_stats (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, username TEXT, first_name TEXT, deal_id INTEGER, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS error_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, error_type TEXT, details TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, reported INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS gif_settings (id INTEGER PRIMARY KEY CHECK (id = 1), width INTEGER DEFAULT 1024, height INTEGER DEFAULT 576, fps INTEGER DEFAULT 30, frame_skip INTEGER DEFAULT 3, crf INTEGER DEFAULT 23, preset TEXT DEFAULT 'veryfast');
        INSERT OR IGNORE INTO gif_settings (id) VALUES (1);
        CREATE TABLE IF NOT EXISTS gif_cache (slug TEXT PRIMARY KEY, file_id TEXT, unavailable INTEGER DEFAULT 0, retry_after REAL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS user_inline_points (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_shared_at TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS user_achievements (user_id INTEGER NOT NULL, code TEXT NOT NULL, unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, code));
        CREATE TABLE IF NOT EXISTS daily_profit (user_id INTEGER NOT NULL, date TEXT NOT NULL, profit_gram REAL DEFAULT 0, profit_usd REAL DEFAULT 0, deals INTEGER DEFAULT 0, PRIMARY KEY (user_id, date));
        CREATE TABLE IF NOT EXISTS thumb_cache (slug TEXT PRIMARY KEY, file_id TEXT, unavailable INTEGER DEFAULT 0, retry_after REAL DEFAULT 0, attempts INTEGER DEFAULT 0, is_placeholder INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    ''')

    REQUIRED_COLUMNS = {
        "sales": [("nft_link", "TEXT"), ("nft_image", "TEXT"), ("nft_name", "TEXT"), ("thumb_file_id", "TEXT"), ("gram_price", "REAL DEFAULT 0"), ("gram_price_buy", "REAL DEFAULT 0"), ("gram_price_sell", "REAL DEFAULT 0"), ("royalty_gram", "REAL DEFAULT 0"), ("gift_name", "TEXT"), ("model", "TEXT"), ("model_rarity", "TEXT"), ("model_emoji_id", "TEXT"), ("backdrop", "TEXT"), ("backdrop_rarity", "TEXT"), ("backdrop_emoji_id", "TEXT"), ("symbol", "TEXT"), ("symbol_rarity", "TEXT"), ("symbol_emoji_id", "TEXT"), ("collection_emoji_id", "TEXT"), ("gif_file_id", "TEXT")],
        "pending_sales": [("nft_link", "TEXT"), ("nft_image", "TEXT"), ("thumb_file_id", "TEXT"), ("gram_price", "REAL DEFAULT 0"), ("gram_price_buy", "REAL DEFAULT 0"), ("royalty_gram", "REAL DEFAULT 0"), ("gift_name", "TEXT"), ("model", "TEXT"), ("model_rarity", "TEXT"), ("model_emoji_id", "TEXT"), ("backdrop", "TEXT"), ("backdrop_rarity", "TEXT"), ("backdrop_emoji_id", "TEXT"), ("symbol", "TEXT"), ("symbol_rarity", "TEXT"), ("symbol_emoji_id", "TEXT"), ("collection_emoji_id", "TEXT")],
        "users": [("referred_by", "INTEGER")],
        "user_change_alerts": [("disabled_until", "REAL DEFAULT 0")],
        "gif_cache": [("unavailable", "INTEGER DEFAULT 0"), ("retry_after", "REAL DEFAULT 0")],
        "thumb_cache": [("is_placeholder", "INTEGER DEFAULT 0")],
    }

    for table_name, columns in REQUIRED_COLUMNS.items():
        try:
            cur = await conn.execute(f"PRAGMA table_info({table_name})")
            existing_cols = {row[1] for row in await cur.fetchall()}
        except: continue
        for col_name, col_type in columns:
            if col_name not in existing_cols:
                try: await conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                except: pass

    for admin_id in ADMIN_IDS:
        try: await conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (admin_id,))
        except: pass

    try:
        await conn.execute("UPDATE sales SET gram_price_buy = gram_price WHERE (gram_price_buy IS NULL OR gram_price_buy = 0) AND gram_price > 0")
        await conn.execute("UPDATE sales SET gram_price_sell = gram_price WHERE (gram_price_sell IS NULL OR gram_price_sell = 0) AND gram_price > 0")
    except: pass

    try:
        cur = await conn.execute("SELECT COUNT(*) FROM daily_profit")
        dp_count = (await cur.fetchone())[0]
        if dp_count == 0:
            cur = await conn.execute("SELECT user_id, date, SUM(profit_gram), SUM(profit_usd), COUNT(*) FROM sales GROUP BY user_id, date")
            for row in await cur.fetchall():
                uid, d, pg, pu, cnt = row
                if d: await conn.execute("INSERT OR IGNORE INTO daily_profit (user_id, date, profit_gram, profit_usd, deals) VALUES (?,?,?,?,?)", (uid, d, pg or 0, pu or 0, cnt or 0))
    except: pass

    await conn.commit()
    logger.info("[MIGRATE] ✅ Инициализация БД завершена")

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

# ---------- ГИФКИ И КАРТИНКИ ----------
async def download_file(url, path):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120), headers={"User-Agent": "Mozilla/5.0"}) as s:
        async with s.get(url) as r:
            if r.status != 200: raise ValueError(f"HTTP {r.status}")
            d = await r.read()
    path.write_bytes(d)

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
        draw.text(((320 - (bbox[2] - bbox[0])) // 2, 130), text, fill=(255, 255, 255), font=font)
        bbox = draw.textbbox((0, 0), profit_text, font=font_small)
        draw.text(((320 - (bbox[2] - bbox[0])) // 2, 170), profit_text, fill=(46, 204, 113) if profit > 0 else (231, 76, 60), font=font_small)
    except:
        draw.text((50, 130), text, fill=(255, 255, 255))
        draw.text((50, 170), profit_text, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()

async def upload_thumb_to_telegram(image_url, gift_name="NFT", profit=0.0, slug=None, caption=None):
    conn = await get_db()
    if slug:
        cur = await conn.execute("SELECT file_id, unavailable, retry_after, is_placeholder FROM thumb_cache WHERE slug=?", (slug,))
        row = await cur.fetchone()
        if row and row["file_id"] and not row["is_placeholder"]: return row["file_id"]
        if row and row["unavailable"] and row["retry_after"] and time.time() < row["retry_after"]: return None

    if not image_url and slug: image_url = f"https://nft.fragment.com/gift/{slug}.webp"
    
    if not image_url:
        try:
            payload = create_placeholder_image(gift_name, profit)
            msg = await bot.send_photo(chat_id=GIF_CHAT_ID, photo=BufferedInputFile(payload, filename="thumb.jpg"), caption=caption, disable_notification=True)
            file_id = msg.photo[-1].file_id
            if slug: await conn.execute("INSERT OR REPLACE INTO thumb_cache (slug, file_id, is_placeholder) VALUES (?, ?, 1)", (slug, file_id))
            await conn.commit()
            return file_id
        except: return None

    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0", "Referer": "https://fragment.com/"}) as s:
            async with s.get(image_url) as r:
                if r.status == 200: data = await r.read()
                else: raise ValueError(f"HTTP {r.status}")
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.thumbnail((320, 320), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            payload, fname, is_placeholder = buf.getvalue(), "thumb.jpg", 0
        except:
            payload, fname, is_placeholder = create_placeholder_image(gift_name, profit), "thumb_ph.jpg", 1

        msg = await bot.send_photo(chat_id=GIF_CHAT_ID, photo=BufferedInputFile(payload, filename=fname), caption=caption, disable_notification=True)
        file_id = msg.photo[-1].file_id
        if slug: await conn.execute("INSERT OR REPLACE INTO thumb_cache (slug, file_id, unavailable, retry_after, is_placeholder) VALUES (?, ?, 0, 0, ?)", (slug, file_id, is_placeholder))
        await conn.commit()
        return file_id
    except Exception as e:
        logger.warning(f"[THUMB] Ошибка: {e}")
        if slug:
            await conn.execute("INSERT OR REPLACE INTO thumb_cache (slug, file_id, unavailable, retry_after) VALUES (?, NULL, 1, ?)", (slug, time.time() + 86400))
            await conn.commit()
        try:
            payload = create_placeholder_image(gift_name, profit)
            msg = await bot.send_photo(chat_id=GIF_CHAT_ID, photo=BufferedInputFile(payload, filename="thumb.jpg"), caption=caption, disable_notification=True)
            return msg.photo[-1].file_id
        except: return None

async def render_gif_for_nft(slug, work_dir):
    s = await get_gif_settings()
    R_W, R_H, R_FPS, R_SKIP, R_CRF, R_PRESET = s["width"], s["height"], s["fps"], s["frame_skip"], s["crf"], s["preset"]
    json_path, mp4_path = work_dir / "a.json", work_dir / "a.mp4"
    
    lottie_downloaded = False
    try:
        await download_file(f"https://nft.fragment.com/gift/{slug}.lottie.json", json_path)
        lottie_downloaded = True
    except: pass
    
    if not lottie_downloaded:
        try:
            await download_file(f"https://nft.fragment.com/gift/{slug}.json", work_dir / "meta.json")
            with open(work_dir / "meta.json", "r") as f: meta = json.load(f)
            gift_id = meta.get("gift_id") or meta.get("id")
            if gift_id:
                await download_file(f"https://api.changes.tg/original/{gift_id}.json", json_path)
                lottie_downloaded = True
        except: pass
        
    if not lottie_downloaded: raise RuntimeError("Lottie not found")

    with open(json_path, "r") as f: data = json.load(f)
    comp_w, comp_h = int(data.get('w', 512)), int(data.get('h', 512))
    frame_rate, ip, op = float(data.get('fr', 60)), float(data.get('ip', 0)), float(data.get('op', 1))
    step = max(1, round(frame_rate / R_FPS))
    frame_numbers = list(range(int(ip), int(op), step))[::R_SKIP]
    final_fps = max(1, math.ceil(R_FPS / R_SKIP))
    
    bg_layers = [x for x in data.get('layers', []) if x.get('nm') in {'Background', 'Pattern', 'Color Icon'}]
    anim_layers = [x for x in data.get('layers', []) if x.get('nm') in {'Gift'}]
    
    bg_data, anim_data = dict(data), dict(data)
    bg_data['layers'], anim_data['layers'] = bg_layers, anim_layers
    
    html_content = f"""
    <html><head><script src="https://cdnjs.cloudflare.com/ajax/libs/bodymovin/5.12.2/lottie.min.js"></script>
    <style>body {{ margin:0; background:transparent; }} #bg {{ position:absolute; top:0; left:0; width:{R_W}px; height:{R_H}px; }} #gift {{ position:absolute; top:{(R_H-comp_h)//2}px; left:{(R_W-comp_w)//2}px; width:{comp_w}px; height:{comp_h}px; }} svg {{ width:100% !important; height:100% !important; }}</style>
    </head><body><div id="bg"></div><div id="gift"></div><script>
    const bgAnim = lottie.loadAnimation({{container: document.getElementById('bg'), renderer: 'svg', autoplay: false, animationData: {json.dumps(bg_data)}}});
    const giftAnim = lottie.loadAnimation({{container: document.getElementById('gift'), renderer: 'svg', autoplay: false, animationData: {json.dumps(anim_data)}}});
    window.setFrame = (f) => {{ bgAnim.goToAndStop(f, true); giftAnim.goToAndStop(f, true); }}; window.ready = true;
    </script></body></html>"""
    
    html_path = work_dir / "render.html"
    with open(html_path, "w") as f: f.write(html_content)
    
    page = await browser_instance.newPage()
    await page.setViewport({'width': R_W, 'height': R_H})
    await page.goto(f"file://{html_path}")
    await page.waitForFunction('window.ready === true')
    
    fdir = work_dir / "frames"; fdir.mkdir(exist_ok=True)
    for idx, i in enumerate(frame_numbers):
        await page.evaluate(f'setFrame({i})')
        await page.screenshot({'path': str(fdir / f"f_{idx:06d}.png"), 'omitBackground': True})
    await page.close()
    
    cmd = ["ffmpeg", "-y", "-framerate", str(final_fps), "-i", str(fdir / "f_%06d.png"), "-an", "-c:v", "libx264", "-profile:v", "main", "-preset", R_PRESET, "-crf", str(R_CRF), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4_path)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if res.returncode != 0: raise RuntimeError(f"ffmpeg err: {res.stderr[-500:]}")
    return mp4_path

async def ensure_gif_rendered(slug: str, nft_link: str, notify_user_id: int = None):
    conn = await get_db()
    cur = await conn.execute("SELECT file_id, unavailable, retry_after FROM gif_cache WHERE slug=?", (slug,))
    row = await cur.fetchone()
    if row and row["file_id"]: return row["file_id"]
    if row and row["unavailable"] and row["retry_after"] and time.time() < row["retry_after"]: return None

    task = gif_render_tasks.get(slug)
    if task and not task.done(): return await task

    async def _do():
        async with gif_render_lock:
            cur2 = await conn.execute("SELECT file_id FROM gif_cache WHERE slug=?", (slug,))
            r2 = await cur2.fetchone()
            if r2 and r2["file_id"]: return r2["file_id"]
            if not browser_instance: return None
            
            with tempfile.TemporaryDirectory() as tmp:
                mp4_path = await render_gif_for_nft(slug, Path(tmp))
                caption = None
                msg = await bot.send_animation(chat_id=GIF_CHAT_ID, animation=FSInputFile(str(mp4_path), filename=f"{slug}.mp4"), caption=caption, disable_notification=True)
                file_id = msg.animation.file_id
                await conn.execute("INSERT OR REPLACE INTO gif_cache (slug, file_id, unavailable, retry_after) VALUES (?, ?, 0, 0)", (slug, file_id))
                await conn.commit()
                return file_id

    task = asyncio.create_task(_do())
    gif_render_tasks[slug] = task
    try: result = await task
    except Exception as e:
        if "404" in str(e):
            await conn.execute("INSERT OR REPLACE INTO gif_cache (slug, file_id, unavailable, retry_after) VALUES (?, NULL, 1, ?)", (slug, time.time() + 86400))
            await conn.commit()
        result = None
    finally: gif_render_tasks.pop(slug, None)
    return result

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
    if not rows: return 0, 0
    def parse(d):
        try: return datetime.strptime(d, "%d.%m.%Y").date()
        except: return None
    dates = [parse(r[0]) for r in rows if parse(r[0])]
    if not dates: return 0, 0
    today = datetime.now().date()
    cur_streak = 0
    check = today
    dates_set = set(dates)
    if check not in dates_set:
        check = today - timedelta(days=1)
        if check not in dates_set: cur_streak = 0
    while check in dates_set:
        cur_streak += 1
        check -= timedelta(days=1)
    best, run = 0, 1
    sorted_dates = sorted(dates)
    for i in range(1, len(sorted_dates)):
        if (sorted_dates[i] - sorted_dates[i-1]).days == 1: run += 1
        else: best = max(best, run); run = 1
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
        total_deals, total_profit, wins = row[0] or 0, row[1] or 0, row[2] or 0

        if total_deals >= 1 and "first_deal" not in existing: new_codes.append("first_deal")
        if total_deals >= 10 and "ten_deals" not in existing: new_codes.append("ten_deals")
        if total_deals >= 100 and "hundred_deals" not in existing: new_codes.append("hundred_deals")
        if total_profit >= 10 and "profit_10" not in existing: new_codes.append("profit_10")
        if total_profit >= 100 and "profit_100" not in existing: new_codes.append("profit_100")
        if total_profit >= 1000 and "profit_1000" not in existing: new_codes.append("profit_1000")
        
        cur_streak, _ = await get_streak(user_id)
        if cur_streak >= 3 and "streak_3" not in existing: new_codes.append("streak_3")
        if cur_streak >= 7 and "streak_7" not in existing: new_codes.append("streak_7")
        if cur_streak >= 30 and "streak_30" not in existing: new_codes.append("streak_30")
        
        if total_deals >= 10 and (wins / total_deals) >= 0.7 and "winrate_70" not in existing: new_codes.append("winrate_70")
        
        cur = await conn.execute("SELECT notified FROM profit_goals WHERE user_id=?", (user_id,))
        g = await cur.fetchone()
        if g and g[0] and "goal_achieved" not in existing: new_codes.append("goal_achieved")
        
        cur = await conn.execute("SELECT points FROM user_inline_points WHERE user_id=?", (user_id,))
        p = await cur.fetchone()
        if p and p[0] >= 20 and "inline_10" not in existing: new_codes.append("inline_10")

        for code in new_codes:
            await conn.execute("INSERT OR IGNORE INTO user_achievements (user_id, code) VALUES (?,?)", (user_id, code))
        await conn.commit()

        for code in new_codes:
            info = ACHIEVEMENTS.get(code, {})
            try:
                await bot.send_message(user_id, f"🏆 <b>Новое достижение!</b>\n\n{info.get('emoji','🏆')} <b>{info.get('title', code)}</b>\n<i>{info.get('desc','')}</i>")
                await log_action(user_id, "", "achievement", code)
            except: pass
    except Exception as e:
        logger.warning(f"check_achievements: {e}")

def render_profit_chart(daily: list, title: str = "Прибыль за 7 дней (GRAM)"):
    if not daily: return None
    try:
        W, H = 800, 400
        PAD_L, PAD_R, PAD_T, PAD_B = 60, 30, 50, 60
        img = Image.new("RGB", (W, H), (24, 26, 36))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        except: font = font_small = font_title = ImageFont.load_default()

        profits = [p for _, p in daily]
        max_v = max(max(profits), 0.001)
        min_v = min(min(profits), 0)
        span = max_v - min_v
        if span <= 0: span = 1

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
            if bar_h < 2: bar_h = 2
            x0, x1 = x_center - bar_w / 2, x_center + bar_w / 2
            if p >= 0: y0, y1, color = zero_y - bar_h, zero_y, (46, 204, 113)
            else: y0, y1, color = zero_y, zero_y + bar_h, (231, 76, 60)
            draw.rectangle([x0, y0, x1, y1], fill=color)
            if n <= 40:
                val_text = f"{p:+.1f}"
                try: bbox = draw.textbbox((0, 0), val_text, font=font_small); tw = bbox[2] - bbox[0]
                except: tw = len(val_text) * 7
                draw.text((x_center - tw / 2, y0 - 20 if p >= 0 else y1 + 4), val_text, fill=(200, 200, 210), font=font_small)
            try: short_date = d[:5]
            except: short_date = d
            if n <= 15 or i % max(1, n // 12) == 0:
                try: bbox = draw.textbbox((0, 0), short_date, font=font_small); tw = bbox[2] - bbox[0]
                except: tw = len(short_date) * 7
                draw.text((x_center - tw / 2, H - PAD_B + 20), short_date, fill=(160, 160, 170), font=font_small)

        draw.line([(PAD_L, zero_y), (W - PAD_R, zero_y)], fill=(80, 80, 100), width=1)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"render_profit_chart: {e}")
        return None

# ---------- ХЕНДЛЕРЫ ВИДЖЕТОВ (СТАТИСТИКА, НАСТРОЙКИ, ДОНАТ, КАЛЬКУЛЯТОР) ----------
@dp.message(F.text.in_(["📊 Статистика", "📊 Stats"]))
@dp.message(Command("stats"))
async def user_stats_handler(message: Message):
    user_id = message.from_user.id
    conn = await get_db()
    
    cur = await conn.execute("SELECT COUNT(*), SUM(profit_gram), SUM(profit_usd), SUM(CASE WHEN profit_gram > 0 THEN 1 ELSE 0 END) FROM sales WHERE user_id=?", (user_id,))
    total, sum_g, sum_u, wins = await cur.fetchone()
    total, sum_g, sum_u, wins = total or 0, sum_g or 0.0, sum_u or 0.0, wins or 0
    winrate = (wins / total * 100) if total else 0
    
    cur = await conn.execute("SELECT gift_name, category, profit_gram, model FROM sales WHERE user_id=? AND profit_gram > 0 ORDER BY profit_gram DESC LIMIT 1", (user_id,))
    top_deal = await cur.fetchone()
    top_deal_html = ""
    if top_deal:
        name, model, profit = top_deal[0] or top_deal[1] or "NFT", top_deal[3] or "", top_deal[2] or 0
        top_deal_html = f'<div class="top-deal"><div class="top-deal-bg">🏆</div><div class="top-deal-title">🔥 Лучшая сделка</div><div class="top-deal-name">{name} <span style="font-size:11px;color:#aab2c8;">({model})</span></div><div class="top-deal-profit">+{profit:.2f} GRAM</div></div>'
    
    today = datetime.now().date()
    days = [(today - timedelta(days=i)).strftime("%d.%m.%Y") for i in range(6, -1, -1)]
    placeholders = ",".join("?" * len(days))
    cur = await conn.execute(f"SELECT date, profit_gram FROM daily_profit WHERE user_id=? AND date IN ({placeholders})", (user_id, *days))
    by_date = {r[0]: r[1] or 0 for r in await cur.fetchall()}
    profits = [by_date.get(d, 0) for d in days]
    max_profit = max(max(profits), 0.01)
    
    chart_bars = ""
    for p in profits:
        height = int((p / max_profit) * 100) if p > 0 else 5
        color = "linear-gradient(to top, #3987ff, #6659ed)" if p >= 0 else "linear-gradient(to top, #ff7777, #ff4444)"
        chart_bars += f'<div class="chart-bar" style="height: {height}%; background: {color};" title="{p:+.2f}"></div>'
    
    html = STATS_WIDGET_HTML
    html = html.replace("{{TOTAL_DEALS}}", str(total)).replace("{{WINRATE}}", f"{winrate:.0f}%")
    html = html.replace("{{PROFIT_GRAM}}", f"{sum_g:+.2f}").replace("{{PROFIT_USD}}", f"{sum_u:+.2f}$")
    html = html.replace("{{PROFIT_CLASS}}", "profit-green" if sum_g >= 0 else "profit-red")
    html = html.replace("{{TOP_DEAL_HTML}}", top_deal_html).replace("{{CHART_BARS}}", chart_bars)
    html = html.replace("{{CHART_DATES}}", f"{days[0][:5]} — {days[-1][:5]}").replace("{{CHART_TOTAL}}", f"{sum(profits):+.2f} GRAM")
    
    result = await send_widget_raw(BOT_TOKEN, message.chat.id, html)
    if result is None: await message.answer("❌ Не удалось открыть статистику. Попробуйте позже.")

@dp.message(F.text.in_(["⚙️ Настройки", "⚙️ Settings"]))
async def settings(message: Message):
    user_id = message.from_user.id
    royalty = await get_user_royalty(user_id)
    star_rate = await get_user_star_rate(user_id)
    conn = await get_db()
    cur = await conn.execute("SELECT goal_gram FROM profit_goals WHERE user_id=?", (user_id,))
    goal_row = await cur.fetchone()
    goal = goal_row[0] if goal_row else 0
    
    html = SETTINGS_WIDGET_HTML
    html = html.replace("{{ROYALTY}}", f"{royalty:.2f}").replace("{{GOAL}}", f"{goal:.2f}" if goal else "Не задана").replace("{{STAR_RATE}}", f"{star_rate:.6f}")
    
    result = await send_widget_raw(BOT_TOKEN, message.chat.id, html)
    if result is None: await message.answer("❌ Не удалось открыть настройки. Попробуйте позже.")

@dp.message(F.text.in_(["💎 Поддержать", "💎 Donate"]))
async def donate_menu(message: Message, state: FSMContext):
    await state.clear()
    result = await send_widget_raw(BOT_TOKEN, message.chat.id, DONATE_WIDGET_HTML)
    if result is None: await message.answer("❌ Не удалось открыть донат-виджет. Попробуйте позже.")

@dp.message(F.text.in_(["🔄 Калькулятор", "🔄 Calculator"]))
async def calc_start(message: Message, state: FSMContext):
    await state.clear()
    result = await send_widget_raw(BOT_TOKEN, message.chat.id, CALC_WIDGET_HTML)
    if result is None: await message.answer("❌ Не удалось открыть калькулятор. Попробуйте позже.")

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
        if amount <= 0: raise ValueError
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
    if user_id is None:
        user_id = message.from_user.id if hasattr(message, 'from_user') else message.chat.id
    data = await state.get_data()
    buy_amount = data["buy_amount"]
    sell_amount = data["sell_amount"]
    gram_price_buy = data.get("gram_price_buy") or 0
    gram_price_sell = data.get("gram_price_sell") or 0
    if gram_price_buy <= 0: gram_price_buy = await get_gram_price()
    if gram_price_sell <= 0: gram_price_sell = await get_gram_price()

    profit_gram = sell_amount - buy_amount - royalty
    profit_usd = compute_profit_usd(buy_amount, sell_amount, royalty, gram_price_buy, gram_price_sell, fallback_gram_price=gram_price_sell)
    date = datetime.now().strftime("%d.%m.%Y")
    gift_name = data.get('gift_name') or data.get('category') or 'NFT'
    nft_link = data.get("nft_link") or ""
    slug = nft_link.split("/nft/")[1].split("/")[0].split("?")[0] if "t.me/nft/" in nft_link else None

    user_display = f"@{message.from_user.username}" if message.from_user.username else f"ID {user_id}"
    attrs_for_caption = format_gift_attributes(data)
    caption_for_group = f"📊 <b>Новая сделка</b>\n\n👤 {_esc(user_display)}\n🎁 <b>{_esc(gift_name)}</b>\n"
    if attrs_for_caption: caption_for_group += f"{attrs_for_caption}\n"
    caption_for_group += f"━━━━━━━━━━━━━━━━━━\n💎 {buy_amount} → {sell_amount} GRAM\n🔸 Комиссия: {royalty:.2f} GRAM\n{EMOJI_MONEY} <b>{profit_gram:+.4f} GRAM</b> · {EMOJI_DOLLAR} <b>{profit_usd:+.2f}$</b>\n📅 {date}\n"
    if nft_link: caption_for_group += f"{EMOJI_LINK} <a href='{nft_link}'>Открыть NFT</a>"

    thumb_id = data.get("thumb_file_id")
    if not thumb_id or not str(thumb_id).startswith("AgAC"):
        thumb_id = await upload_thumb_to_telegram(data.get("nft_image"), gift_name=gift_name, profit=profit_gram, slug=slug, caption=caption_for_group)

    conn = await get_db()
    await conn.execute(
        "INSERT INTO sales (user_id, category, nft_link, nft_image, thumb_file_id, date, buy_amount, sell_amount, gram_price, gram_price_buy, gram_price_sell, profit_gram, profit_usd, royalty_gram, gift_name, model, model_rarity, model_emoji_id, backdrop, backdrop_rarity, backdrop_emoji_id, symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, data["category"], data["nft_link"], data.get("nft_image"), thumb_id, date, buy_amount, sell_amount, gram_price_sell, gram_price_buy, gram_price_sell, round(profit_gram, 4), profit_usd, royalty, data.get("gift_name"), data.get("model"), data.get("model_rarity"), data.get("model_emoji_id"), data.get("backdrop"), data.get("backdrop_rarity"), data.get("backdrop_emoji_id"), data.get("symbol"), data.get("symbol_rarity"), data.get("symbol_emoji_id"), data.get("collection_emoji_id"))
    )
    await conn.commit()
    await log_action(user_id, "", "add_deal", f"{data['category']}: {buy_amount} → {sell_amount} GRAM")
    await _update_daily_profit(user_id, date, profit_gram, profit_usd, 1)
    await add_user_collection(user_id, data["category"])
    await state.clear()
    await activate_referral(user_id)
    await check_goal_achievement(user_id)
    await check_achievements(user_id)

    msgs = MESSAGES[lang]
    attrs = format_gift_attributes(data)
    ce = premium_emoji(data.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
    text = msgs["sale_saved"].format(category=data['category'], buy=buy_amount, sell=sell_amount, royalty=f"{royalty:.2f}", profit=f"{profit_gram:+.4f}", usd=f"{profit_usd:+.2f}")
    header = f"{ce} <b>{gift_name}</b>\n{EMOJI_DOLLAR} Курс покупки: <b>${gram_price_buy:.4f}</b>\n{EMOJI_DOLLAR} Курс продажи: <b>${gram_price_sell:.4f}</b>"
    if attrs: header += f"\n{attrs}"
    await message.answer(f"{header}\n\n{text}", reply_markup=get_main_kb(lang))
    if slug: asyncio.create_task(ensure_gif_rendered(slug, nft_link, notify_user_id=user_id))

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
    if not message.text: return await message.answer("❌ Отправь ссылку текстом.", reply_markup=get_cancel_kb(lang))
    link = message.text.strip()
    if not link: return await message.answer(MESSAGES[lang]["link_required"], reply_markup=get_cancel_kb(lang))
    await state.update_data(nft_link=link)
    nft_data = await parse_nft_link(link)
    if nft_data:
        await state.update_data(**nft_data)
        gift_name = nft_data.get('gift_name', 'NFT')
        slug = link.split("/nft/")[1].split("/")[0].split("?")[0] if "t.me/nft/" in link else None
        thumb_id = await upload_thumb_to_telegram(nft_data.get("nft_image"), gift_name=gift_name, profit=0.0, slug=slug)
        if thumb_id: await state.update_data(thumb_file_id=thumb_id)
        attrs = format_gift_attributes(nft_data)
        await message.answer(f"{premium_emoji(nft_data.get('collection_emoji_id'), '🎁')} <b>{gift_name}</b>\n{attrs}", reply_markup=get_cancel_kb(lang))
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
        return await callback.message.answer("Введите комиссию в GRAM:", reply_markup=get_cancel_kb(lang))
    await save_pending(callback.message, state, float(val), callback.from_user.id, lang)

@dp.message(PendingBuy.waiting_for_royalty)
async def process_pending_custom_royalty(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    try: await save_pending(message, state, float(message.text.replace(",", ".")), message.from_user.id, lang)
    except: await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

async def save_pending(message: Message, state: FSMContext, royalty: float, user_id: int, lang: str = "ru"):
    data = await state.get_data()
    if "category" not in data or "nft_link" not in data:
        await message.answer("❌ Ошибка: данные потеряны. Начни создание отложенной покупки заново.", reply_markup=get_main_kb(lang))
        await state.clear()
        return
    gram_price_buy = data.get("gram_price_buy") or await get_gram_price()
    conn = await get_db()
    await conn.execute(
        "INSERT INTO pending_sales (user_id, category, nft_link, nft_image, thumb_file_id, date, buy_amount, gram_price, gram_price_buy, royalty_gram, gift_name, model, model_rarity, model_emoji_id, backdrop, backdrop_rarity, backdrop_emoji_id, symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, data["category"], data["nft_link"], data.get("nft_image"), data.get("thumb_file_id"), datetime.now().strftime("%d.%m.%Y"), data["buy_amount"], gram_price_buy, gram_price_buy, royalty, data.get("gift_name"), data.get("model"), data.get("model_rarity"), data.get("model_emoji_id"), data.get("backdrop"), data.get("backdrop_rarity"), data.get("backdrop_emoji_id"), data.get("symbol"), data.get("symbol_rarity"), data.get("symbol_emoji_id"), data.get("collection_emoji_id"))
    )
    await conn.commit()
    await log_action(user_id, "", "add_pending", f"{data['category']}: покупка {data['buy_amount']} GRAM, комиссия {royalty:.2f}")
    await state.clear()
    await message.answer(f"✅ Отложенная покупка сохранена!\n🎁 {data.get('gift_name')}\n📥 {data['buy_amount']} GRAM", reply_markup=get_main_kb(lang))

# ---------- ЗАВЕРШЕНИЕ СДЕЛКИ ----------
@dp.message(F.text.in_(["📤 Завершить сделку", "📤 Complete Deal"]))
async def complete_start(message: Message, state: FSMContext):
    await state.clear()
    await show_pending_page(message, message.from_user.id, 0)

async def show_pending_page(message: Message, user_id: int, page: int):
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM pending_sales WHERE user_id=?", (user_id,))
    total = (await cur.fetchone())[0]
    if total == 0: return await message.answer(MESSAGES["ru"]["no_pending"], reply_markup=get_main_kb())
    cur = await conn.execute("SELECT * FROM pending_sales WHERE user_id=? ORDER BY id DESC LIMIT 5 OFFSET ?", (user_id, page * 5))
    rows = await cur.fetchall()
    text = f"📤 <b>Отложенные сделки</b>\n\n"
    kb_rows = []
    for p in rows:
        text += f"<b>#{p['id']}</b> · {p['gift_name'] or p['category']}\n💎 {p['buy_amount']} GRAM · 📅 {p['date']}\n\n"
        kb_rows.append([InlineKeyboardButton(text=f"✅ Завершить #{p['id']}", callback_data=f"complete_{p['id']}"), InlineKeyboardButton(text=f"🗑 #{p['id']}", callback_data=f"delete_pending_{p['id']}")])
    kb_rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_deal")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

@dp.callback_query(F.data.regexp(r"^complete_\d+$"))
async def process_complete(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    pending_id = int(callback.data.split("_")[1])
    await state.update_data(pending_id=pending_id)
    await state.set_state(CompletePending.waiting_for_sell_amount)
    await callback.message.answer("💵 Введи сумму продажи в GRAM:", reply_markup=get_cancel_kb())

@dp.message(CompletePending.waiting_for_sell_amount)
async def process_complete_sell(message: Message, state: FSMContext):
    try:
        sell_amount = float(message.text.replace(",", "."))
        await state.update_data(sell_amount=sell_amount)
        await state.set_state(CompletePending.waiting_for_royalty)
        await message.answer("🔸 Введи комиссию (или 0):", reply_markup=get_cancel_kb())
    except: await message.answer("❌ Введи число.")

@dp.message(CompletePending.waiting_for_royalty)
async def process_complete_royalty(message: Message, state: FSMContext):
    try:
        royalty = float(message.text.replace(",", "."))
        data = await state.get_data()
        user_id = message.from_user.id
        conn = await get_db()
        cur = await conn.execute("SELECT * FROM pending_sales WHERE id=? AND user_id=?", (data['pending_id'], user_id))
        row = await cur.fetchone()
        
        gp_sell = await get_gram_price()
        profit_gram = data['sell_amount'] - row['buy_amount'] - royalty
        profit_usd = compute_profit_usd(row['buy_amount'], data['sell_amount'], royalty, row['gram_price_buy'], gp_sell)
        
        await conn.execute("INSERT INTO sales (user_id, category, nft_link, nft_image, thumb_file_id, date, buy_amount, sell_amount, gram_price_buy, gram_price_sell, profit_gram, profit_usd, royalty_gram, gift_name, model, model_rarity, model_emoji_id, backdrop, backdrop_rarity, backdrop_emoji_id, symbol, symbol_rarity, symbol_emoji_id, collection_emoji_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, row['category'], row['nft_link'], row['nft_image'], row['thumb_file_id'], row['date'], row['buy_amount'], data['sell_amount'], row['gram_price_buy'], gp_sell, profit_gram, profit_usd, royalty, row['gift_name'], row['model'], row['model_rarity'], row['model_emoji_id'], row['backdrop'], row['backdrop_rarity'], row['backdrop_emoji_id'], row['symbol'], row['symbol_rarity'], row['symbol_emoji_id'], row['collection_emoji_id']))
        await conn.execute("DELETE FROM pending_sales WHERE id=?", (row['id'],))
        await conn.commit()
        await _update_daily_profit(user_id, row['date'], profit_gram, profit_usd)
        await state.clear()
        await message.answer(f"🎉 Сделка закрыта!\n💰 Прибыль: <b>{profit_gram:+.4f} GRAM</b>", reply_markup=get_main_kb())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await state.clear()

# ---------- ИСТОРИЯ ----------
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
    if total == 0: return await message.answer(MESSAGES[lang]["history_empty"])
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages-1))
    offset = page * PAGE_SIZE
    cur = await conn.execute("SELECT * FROM sales WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?", (user_id, PAGE_SIZE, offset))
    deals = [dict(row) for row in await cur.fetchall()]
    
    text = MESSAGES[lang]["history_title"].format(page=page+1, total=total_pages)
    for d in deals:
        emoji = get_profit_emoji(d['profit_gram'])
        link = f"<a href='{d['nft_link']}'>NFT</a>" if d.get('nft_link') else "—"
        ce = premium_emoji(d.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
        gift_line = f"{ce} {d['gift_name']}\n" if d.get('gift_name') else ""
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
    kb_rows.append([InlineKeyboardButton(text="🔍 Найти сделку", callback_data="history_search")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

@dp.callback_query(F.data.startswith("hist_"))
async def history_pagination(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split("_")
    new_page = int(parts[2]) - 1 if parts[1] == "prev" else int(parts[2]) + 1
    try: await callback.message.delete()
    except: pass
    await show_history_page(callback.message, callback.from_user.id, new_page)

# ---------- ПОИСК В ИСТОРИИ ----------
@dp.callback_query(F.data == "history_search")
async def history_search_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(HistorySearch.waiting_for_query)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ К истории", callback_data="hist_back")]])
    await callback.message.answer("🔍 <b>Поиск по истории</b>\n\nВведи:\n• номер сделки — <code>42</code> или <code>#42</code>\n• коллекцию — <code>LuckyLocket</code>\n• ссылку — <code>t.me/nft/LuckyLocket-42</code>\n• модель — <code>Peach</code>", reply_markup=kb)

@dp.callback_query(F.data == "hist_back")
async def hist_back_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await show_history_page(callback.message, callback.from_user.id, 0)

@dp.message(HistorySearch.waiting_for_query)
async def history_search_process(message: Message, state: FSMContext):
    if not message.text: return
    query = message.text.strip()
    if not query: return await message.answer("❌ Пустой запрос.")
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
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔍 Новый поиск", callback_data="history_search")], [InlineKeyboardButton(text="⬅️ К истории", callback_data="hist_back")]])
        await message.answer(f"🔍 По запросу <code>{_esc(query)}</code> ничего не найдено.", reply_markup=kb)
        await state.clear()
        return

    text = f"🔍 <b>Найдено: {len(results)}</b>\n\n"
    kb_rows = []
    for d in results[:10]:
        emoji = get_profit_emoji(d['profit_gram'])
        ce = premium_emoji(d.get("collection_emoji_id"), EMOJI_COLLECTION_FALLBACK)
        gift_line = f"{ce} {_esc(d['gift_name'])}" if d['gift_name'] else f"📁 {_esc(d['category'])}"
        link = f"<a href='{d['nft_link']}'>NFT</a>" if d.get('nft_link') else "—"
        text += f"{emoji} <b>#{d['id']}</b> · {gift_line}\n   💎 {d['buy_amount']} → {d['sell_amount']} GRAM · 💰 {d['profit_gram']:+.4f} GRAM\n   📅 {d['date']} · {link}\n\n"
        kb_rows.append([InlineKeyboardButton(text=f"✏️ #{d['id']}", callback_data=f"edit_{d['id']}"), InlineKeyboardButton(text=f"🗑 #{d['id']}", callback_data=f"delete_{d['id']}")])
    kb_rows.append([InlineKeyboardButton(text="🔍 Новый поиск", callback_data="history_search"), InlineKeyboardButton(text="⬅️ К истории", callback_data="hist_back")])
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
    try: await callback.message.edit_text(MESSAGES[lang]["deleted"])
    except: await callback.message.answer(MESSAGES[lang]["deleted"])

# ---------- РЕДАКТИРОВАНИЕ СДЕЛКИ ----------
@dp.callback_query(F.data.regexp(r"^edit_\d+$"))
async def edit_deal_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    try: deal_id = int(callback.data.split("_")[1])
    except ValueError: return
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM sales WHERE id=? AND user_id=?", (deal_id, callback.from_user.id))
    row = await cur.fetchone()
    if not row: return await callback.message.answer(MESSAGES[lang]["error_not_found"])
    await state.clear()
    await state.update_data(edit_deal_id=deal_id)
    await state.set_state(EditProfit.waiting_for_buy_amount)
    gift_name = (row["gift_name"] if "gift_name" in row.keys() else None) or row["category"] or "NFT"
    ce = premium_emoji(row["collection_emoji_id"] if "collection_emoji_id" in row.keys() else None, EMOJI_COLLECTION_FALLBACK)
    text = (f"✏️ <b>Редактирование сделки #{deal_id}</b>\n\n{ce} <b>{_esc(gift_name)}</b>\n━━━━━━━━━━━━━━━━━━\n💎 Покупка: <b>{row['buy_amount']} GRAM</b>\n💎 Продажа: <b>{row['sell_amount']} GRAM</b>\n🔸 Комиссия: <b>{(row['royalty_gram'] or 0):.2f} GRAM</b>\n📅 {row['date']}\n\nВведи <b>новую сумму покупки</b> в GRAM:")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_deal")]])
    await callback.message.answer(text, reply_markup=kb)

@dp.message(EditProfit.waiting_for_buy_amount)
async def edit_deal_buy_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    if not message.text: return await message.answer("❌ Введи число текстом.", reply_markup=get_cancel_kb(lang))
    try:
        new_buy = float(message.text.replace(",", "."))
        if new_buy <= 0: raise ValueError
    except ValueError: return await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))
    await state.update_data(edit_buy_amount=new_buy)
    await state.set_state(EditProfit.waiting_for_sell_amount)
    await message.answer(f"✅ Покупка: <b>{new_buy} GRAM</b>\n\nВведи <b>новую сумму продажи</b> в GRAM:", reply_markup=get_cancel_kb(lang))

@dp.message(EditProfit.waiting_for_sell_amount)
async def edit_deal_sell_amount(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    if not message.text: return await message.answer("❌ Введи число текстом.", reply_markup=get_cancel_kb(lang))
    try:
        new_sell = float(message.text.replace(",", "."))
        if new_sell <= 0: raise ValueError
    except ValueError: return await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))
    await state.update_data(edit_sell_amount=new_sell)
    data = await state.get_data()
    deal_id = data.get("edit_deal_id")
    conn = await get_db()
    cur = await conn.execute("SELECT royalty_gram FROM sales WHERE id=? AND user_id=?", (deal_id, message.from_user.id))
    row = await cur.fetchone()
    saved_royalty = float(row[0] or 0) if row else 0.0
    await state.set_state(EditProfit.waiting_for_royalty)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔸 Оставить {(saved_royalty):.2f} GRAM", callback_data=f"edit_royalty_keep_{saved_royalty}")],
        [InlineKeyboardButton(text="🔸 Ввести новую комиссию", callback_data="edit_royalty_custom")],
        [InlineKeyboardButton(text="0 (без комиссии)", callback_data="edit_royalty_keep_0")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_deal")]
    ])
    await message.answer(f"✅ Продажа: <b>{new_sell} GRAM</b>\n\n🔸 Текущая комиссия: <b>{saved_royalty:.2f} GRAM</b>\n\nОставить её или ввести новую?", reply_markup=kb)

@dp.callback_query(F.data.startswith("edit_royalty_keep_"))
async def edit_royalty_keep(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    val = callback.data.replace("edit_royalty_keep_", "")
    try: royalty = float(val)
    except: royalty = 0.0
    await _apply_edit_deal(callback.message, state, royalty, callback.from_user.id, lang)

@dp.callback_query(F.data == "edit_royalty_custom")
async def edit_royalty_custom_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = await get_user_lang(callback.from_user.id)
    await callback.message.answer("🔸 Введи новую комиссию в GRAM:", reply_markup=get_cancel_kb(lang))

@dp.message(EditProfit.waiting_for_royalty)
async def edit_deal_custom_royalty(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    if not message.text: return await message.answer("❌ Введи число текстом.", reply_markup=get_cancel_kb(lang))
    try:
        royalty = float(message.text.replace(",", "."))
        if royalty < 0: raise ValueError
    except ValueError: return await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))
    await _apply_edit_deal(message, state, royalty, message.from_user.id, lang)

async def _apply_edit_deal(message: Message, state: FSMContext, new_royalty: float, user_id: int, lang: str = "ru"):
    data = await state.get_data()
    deal_id = data.get("edit_deal_id")
    new_buy = data.get("edit_buy_amount")
    new_sell = data.get("edit_sell_amount")
    if not deal_id or new_buy is None or new_sell is None:
        await message.answer("❌ Данные потеряны. Начни редактирование заново.", reply_markup=get_main_kb(lang))
        await state.clear()
        return
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM sales WHERE id=? AND user_id=?", (deal_id, user_id))
    old = await cur.fetchone()
    if not old: return await message.answer(MESSAGES[lang]["error_not_found"], reply_markup=get_main_kb(lang))
    
    gp_buy = old["gram_price_buy"] if "gram_price_buy" in old.keys() and old["gram_price_buy"] else (old["gram_price"] or 0)
    gp_sell = old["gram_price_sell"] if "gram_price_sell" in old.keys() and old["gram_price_sell"] else (old["gram_price"] or 0)
    if gp_buy <= 0: gp_buy = await get_gram_price()
    if gp_sell <= 0: gp_sell = await get_gram_price()
    new_profit_gram = new_sell - new_buy - new_royalty
    new_profit_usd = compute_profit_usd(new_buy, new_sell, new_royalty, gp_buy, gp_sell, fallback_gram_price=gp_sell)

    await conn.execute("UPDATE sales SET buy_amount=?, sell_amount=?, royalty_gram=?, profit_gram=?, profit_usd=? WHERE id=? AND user_id=?", (new_buy, new_sell, new_royalty, round(new_profit_gram, 4), new_profit_usd, deal_id, user_id))
    await conn.commit()

    old_date = old["date"]
    try:
        await conn.execute("DELETE FROM daily_profit WHERE user_id=? AND date=?", (user_id, old_date))
        cur = await conn.execute("SELECT SUM(profit_gram), SUM(profit_usd), COUNT(*) FROM sales WHERE user_id=? AND date=?", (user_id, old_date))
        agg = await cur.fetchone()
        if agg and agg[2]:
            await conn.execute("INSERT INTO daily_profit (user_id, date, profit_gram, profit_usd, deals) VALUES (?,?,?,?,?)", (user_id, old_date, agg[0] or 0, agg[1] or 0, agg[2]))
            await conn.commit()
    except: pass

    await log_action(user_id, "", "edit_deal", f"#{deal_id}: {old['buy_amount']}→{new_buy}, {old['sell_amount']}→{new_sell}")
    await state.clear()
    sign = "📈" if new_profit_gram > (old["profit_gram"] or 0) else "📉"
    await message.answer(f"✅ <b>Сделка #{deal_id} обновлена!</b>\n━━━━━━━━━━━━━━━━━━\n💎 Покупка: <b>{new_buy} GRAM</b>\n💎 Продажа: <b>{new_sell} GRAM</b>\n🔸 Комиссия: <b>{new_royalty:.2f} GRAM</b>\n{sign} {EMOJI_MONEY} <b>{new_profit_gram:+.4f} GRAM</b> · {EMOJI_DOLLAR} <b>{new_profit_usd:+.2f}$</b>\n📅 {old_date}", reply_markup=get_main_kb(lang))
    await check_achievements(user_id)
    await check_goal_achievement(user_id)

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
        text += f"━━━━━━━━━━━━━━━━━━\nВсего: {len(timers)}\n\n"
        for t in timers:
            link = t['nft_link'] or ""
            ev_type = t['event_type']
            emoji, label = ("🎁", "Минтинг") if ev_type == 'mint' else (("🔄", "Ре-листинг") if ev_type == 'relist' else ("🔓", "Разблокировка"))
            gift_name = "NFT"
            if "t.me/nft/" in link:
                try:
                    seg = link.split("/nft/")[1].split("/")[0]
                    if "-" in seg: gift_name = seg.rsplit("-", 1)[0]
                except: pass
            time_left = t['event_time'] - time.time()
            if time_left <= 0: time_str = "⚠️ <b>Сработает сегодня!</b>"
            else:
                days, hours = int(time_left // 86400), int((time_left % 86400) // 3600)
                time_str = f"🕐 Осталось: <b>{days} дн.</b>" if days > 0 else f"🕐 Осталось: <b>{hours} ч.</b>"
            ev_date = datetime.fromtimestamp(t['event_time']).strftime("%d.%m")
            text += f"{emoji} <b>{_esc(gift_name)}</b> · {label}\n   📅 {ev_date} · {time_str}\n   🔗 <a href='{link}'>Открыть NFT</a>\n\n"
            kb_rows.append([InlineKeyboardButton(text=f"🔗 {gift_name}", url=link), InlineKeyboardButton(text=f"🗑 Удалить", callback_data=f"timer_del_{t['id']}")])
    kb_rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="timer_add_menu")])
    kb_rows.append([InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

@dp.callback_query(F.data == "timer_add_menu")
async def timer_add_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Минтинг", callback_data="timer_mint")], [InlineKeyboardButton(text="🔓 Разблокировка", callback_data="timer_unlock")], [InlineKeyboardButton(text="🔄 Ре-листинг", callback_data="timer_relist")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="timer_back")]])
    try: await callback.message.edit_text("➕ <b>Новый таймер</b>\n\nВыбери тип события:", reply_markup=kb)
    except: await callback.message.answer("➕ <b>Новый таймер</b>\n\nВыбери тип:", reply_markup=kb)

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
    try: await callback.message.edit_text("✅ Таймер удалён.")
    except: await callback.message.answer("✅ Таймер удалён.")

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
    if not message.text: return await message.answer("❌ Отправьте ссылку текстом.", reply_markup=get_cancel_kb(lang))
    link = message.text.strip()
    if not link or "t.me/nft" not in link: return await message.answer(MESSAGES[lang]["timer_invalid_link"], reply_markup=get_cancel_kb(lang))
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
        await log_action(message.from_user.id, "", "timer_add", f"{data.get('event_type')} через {days} дн.")
        await state.clear()
        await message.answer(MESSAGES[lang]["timer_saved"].format(days=days), reply_markup=get_main_kb(lang))
    except ValueError:
        await message.answer(MESSAGES[lang]["error_positive_number"], reply_markup=get_cancel_kb(lang))

# ---------- РЕФЕРАЛЫ ----------
def get_inline_level(points: int):
    if points >= 400: return "🥇", "Легенда инлайнов", 0
    elif points >= 100: return "🥈", "Промоутер", 400 - points
    elif points >= 20: return "🥉", "Новичок", 100 - points
    else: return "🌱", "Начинающий", 20 - points

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
    
    text = f"👥 <b>Рефералы</b>\n\nТвоя ссылка:\n<code>{ref_link}</code>\n\nПриглашено: {invited}\nАктивных: {active}\nОчков: {points}\nУровень: {level}\nДо след. уровня: {next_pts}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=MESSAGES[lang]["referrals_share"], url=f"https://t.me/share/url?url={quote(ref_link)}")], [InlineKeyboardButton(text=MESSAGES[lang]["cancel"], callback_data="cancel_deal")]])
    await message.answer(text, reply_markup=kb)

# ---------- АДМИН-ПАНЕЛЬ ----------
@dp.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext = None):
    if state: await state.clear()
    if not await is_admin(message.from_user.id): return await message.answer("⛔ Доступ запрещён")
    await show_admin_panel(message)

async def show_admin_panel(message: Message):
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM users")
    total_users = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*), SUM(profit_gram), SUM(profit_usd) FROM sales")
    total_deals, total_g, total_u = await cur.fetchone()
    text = f"⚙️ <b>Админ-панель Stars2Profit</b>\n\n👥 Пользователей: {total_users}\n📊 Всего сделок: {total_deals or 0}\n💰 Общая прибыль: {total_g or 0:+.4f} GRAM (${total_u or 0:+.2f})"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Логи действий", callback_data="admin_logs")],
        [InlineKeyboardButton(text="🚨 Проверить ошибки", callback_data="admin_errors")],
        [InlineKeyboardButton(text="🎨 Настройки гифки", callback_data="admin_gif_settings")],
        [InlineKeyboardButton(text="🔄 Обновить картинки", callback_data="admin_refresh_thumbs")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💾 Бэкап БД", callback_data="admin_backup")],
        [InlineKeyboardButton(text="⬅️ Закрыть", callback_data="close_admin")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "close_admin")
async def close_admin(callback: CallbackQuery):
    await callback.answer()
    try: await callback.message.delete()
    except: pass

@dp.callback_query(F.data == "admin_logs")
async def admin_logs(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT user_id, username, action, details, timestamp FROM action_logs ORDER BY id DESC LIMIT 20")
    rows = await cur.fetchall()
    if not rows: text = "📋 <b>Логов пока нет.</b>"
    else:
        lines = ["📋 <b>Последние действия:</b>\n"]
        for uid, uname, action, details, ts in rows:
            name = await get_user_display(conn, uid) if uid else "Система"
            label = ACTION_LABELS.get(action, action)
            time_str = str(ts)[11:16] if ts else "--:--"
            line = f"🕐 <b>{time_str}</b> · {name} — {label}"
            if details: line += f"\n     └ <i>{_esc(str(details)[:90])}</i>"
            lines.append(line)
        text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel_back")]])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: await callback.message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "admin_panel_back")
async def admin_panel_back(callback: CallbackQuery):
    await callback.answer()
    try: await callback.message.delete()
    except: pass
    await show_admin_panel(callback.message)

@dp.callback_query(F.data == "admin_errors")
async def admin_errors(callback: CallbackQuery):
    await callback.answer()
    conn = await get_db()
    cur = await conn.execute("SELECT error_type, details, timestamp FROM error_logs ORDER BY id DESC LIMIT 5")
    rows = await cur.fetchall()
    text = "🚨 <b>Последние ошибки:</b>\n\n" + "\n".join([f"⚠️ {r[0]} — {str(r[2])[:16]}\n{r[1][:100]}" for r in rows]) if rows else "✅ Ошибок нет."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel_back")]])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: await callback.message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.message.answer("📢 Введите текст для рассылки:", reply_markup=get_cancel_kb())

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
    await message.answer(f"✅ Рассылка завершена: {success}/{len(users)}", reply_markup=get_main_kb())

@dp.callback_query(F.data == "admin_backup")
async def admin_backup(callback: CallbackQuery):
    await callback.answer()
    try:
        await create_and_send_backup(callback.from_user.id)
        await log_action(callback.from_user.id, "", "backup", "")
    except Exception as e: await callback.message.answer(f"❌ Ошибка бэкапа: {e}")

async def create_and_send_backup(admin_id: int):
    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    zip_filename = f"backup_{date_str}.zip"
    files = [f for f in ["sales.db", "sales.db-wal", "sales.db-shm"] if Path(f).exists()]
    if not files: return
    with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files: zf.write(f, f)
    try: await bot.send_document(admin_id, FSInputFile(zip_filename), caption="💾 Бэкап БД")
    except: pass
    try: Path(zip_filename).unlink()
    except: pass

    # ---------- ИНЛАЙН-РЕЖИМ ----------
def inline_bot_keyboard(user_id: int = None):
    url = f"{BOT_URL}?start=ref_{user_id}" if user_id else BOT_URL
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Открыть бота", url=url)]])

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

def build_stats_inline_html(user_id: int, username: str, first_name: str, stats: dict) -> str:
    lines = []
    display_name = f"@{username}" if username else (first_name or f"ID {user_id}")
    lines.append(f"📊 <b>Статистика {_esc(display_name)}</b>\n━━━━━━━━━━━━━━━━━━")
    lines.append(f"📈 Сделок: <b>{stats['total']}</b>")
    lines.append(f"✅ В плюс: <b>{stats['wins']}</b> · ❌ В минус: <b>{stats['losses']}</b>")
    lines.append(f"🎯 Winrate: <b>{stats['winrate']:.1f}%</b>\n")
    lines.append(f"💰 <b>Прибыль:</b>")
    lines.append(f"💎 {stats['sum_g']:+.4f} GRAM")
    lines.append(f"🪙 {stats['sum_u']:+.2f}$")
    if stats.get("best") is not None: lines.append(f"🏆 Лучшая: {stats['best']:+.4f} GRAM")
    if stats.get("streak", 0) > 0: lines.append(f"🔥 Серия: {stats['streak']} дн.")
    if stats.get("goal"): lines.append(f"🎯 Цель: {stats['sum_g']:.2f} / {stats['goal']:.2f} GRAM")
    lines.append(f"\n🚀 Попробуй и ты → @Stars2ProfitBot")
    return "\n".join(lines)

async def _get_user_stats_for_inline(user_id: int) -> dict:
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*), SUM(profit_gram), SUM(profit_usd), SUM(CASE WHEN profit_gram > 0 THEN 1 ELSE 0 END), SUM(CASE WHEN profit_gram < 0 THEN 1 ELSE 0 END), MAX(profit_gram) FROM sales WHERE user_id=?", (user_id,))
    total, sum_g, sum_u, wins, losses, best = await cur.fetchone()
    total, wins, losses = total or 0, wins or 0, losses or 0
    winrate = (wins / total * 100) if total else 0
    cur_streak, _ = await get_streak(user_id)
    cur = await conn.execute("SELECT goal_gram FROM profit_goals WHERE user_id=?", (user_id,))
    g_row = await cur.fetchone()
    goal = g_row[0] if g_row else None
    return {"total": total, "sum_g": sum_g or 0, "sum_u": sum_u or 0, "wins": wins, "losses": losses, "winrate": winrate, "best": best, "streak": cur_streak, "goal": goal}

@dp.inline_query()
async def inline_query(inline_query):
    uid = inline_query.from_user.id
    query = (inline_query.query or "").strip()
    conn = await get_db()

    if query.lower() in ("stats", "стата", "статистика") or query.lower().startswith("stats_"):
        target_id = uid
        stats = await _get_user_stats_for_inline(target_id)
        if stats["total"] == 0:
            results = [InlineQueryResultArticle(id="no_stats", title="Нет сделок", description="Сначала добавь хотя бы одну сделку", input_message_content=InputTextMessageContent(message_text="📊 У меня пока нет сделок — начну прямо сейчас!", parse_mode="HTML"), reply_markup=inline_bot_keyboard(user_id=uid))]
            try: await bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=True)
            except: pass
            return
        cur = await conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (target_id,))
        u_row = await cur.fetchone()
        username, first_name = (u_row["username"] if u_row else "", u_row["first_name"] if u_row else "")
        stats_html = build_stats_inline_html(target_id, username or "", first_name or "", stats)
        results = [InlineQueryResultArticle(id=f"stats_{target_id}", title=f"📊 Статистика", description=f"Сделок: {stats['total']} · Winrate: {stats['winrate']:.1f}%", input_message_content=InputTextMessageContent(message_text=stats_html, parse_mode="HTML"), reply_markup=inline_bot_keyboard(user_id=uid))]
        try: await bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=True)
        except: pass
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
        desc = f"💎 {d['buy_amount']} → {d['sell_amount']} GRAM | 💰 {profit:+.4f} GRAM"
        caption_html = build_inline_html(d)
        thumb_id = d.get("thumb_file_id")
        
        if thumb_id and isinstance(thumb_id, str) and thumb_id.startswith("AgAC"):
            results.append(InlineQueryResultCachedPhoto(id=f"sale_{d['id']}", photo_file_id=thumb_id, title=f"#{d['id']} {gift_name}", description=desc, caption=caption_html, parse_mode="HTML", reply_markup=inline_bot_keyboard(user_id=uid)))
        else:
            results.append(InlineQueryResultArticle(id=f"sale_{d['id']}", title=f"#{d['id']} {gift_name}", description=desc, input_message_content=InputTextMessageContent(message_text=caption_html, parse_mode="HTML"), reply_markup=inline_bot_keyboard(user_id=uid)))

    if not results:
        results.append(InlineQueryResultArticle(id="no_deals", title="Ничего не найдено", description="Введи номер сделки или «stats»", input_message_content=InputTextMessageContent(message_text="🔍 Нет сделок."), reply_markup=inline_bot_keyboard(user_id=uid)))

    try: await bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=True)
    except: pass

@dp.chosen_inline_result()
async def chosen_inline_result_handler(chosen: ChosenInlineResult):
    if not chosen.inline_message_id or not chosen.result_id.startswith("sale_"): return
    try: deal_id = int(chosen.result_id.replace("sale_", ""))
    except ValueError: return
    uid = chosen.from_user.id
    conn = await get_db()
    try:
        await conn.execute("INSERT INTO inline_stats (user_id, username, first_name, deal_id) VALUES (?,?,?,?)", (uid, chosen.from_user.username or "", chosen.from_user.first_name or "", deal_id))
        await conn.execute("INSERT INTO user_inline_points (user_id, points) VALUES (?, 2) ON CONFLICT(user_id) DO UPDATE SET points = points + 2", (uid,))
        await conn.commit()
    except: pass

# ---------- ФОНОВЫЕ ЗАДАЧИ ----------
async def timer_checker():
    while True:
        try:
            conn = await get_db()
            now_ts = time.time()
            cur = await conn.execute("SELECT id, user_id, event_type, nft_link, event_time FROM timers WHERE notified=0 ORDER BY event_time")
            for t in await cur.fetchall():
                time_left = (t["event_time"] or 0) - now_ts
                if time_left > 0: continue
                if time_left < -86400:
                    await conn.execute("UPDATE timers SET notified=1 WHERE id=?", (t["id"],))
                    await conn.commit()
                    continue
                ev_type = t["event_type"]
                emoji, label = ("🎁", "Минтинг") if ev_type == "mint" else (("🔄", "Ре-листинг") if ev_type == "relist" else ("🔓", "Разблокировка"))
                link = t["nft_link"] or ""
                gift_name = "NFT"
                if "t.me/nft/" in link:
                    try:
                        seg = link.split("/nft/")[1].split("/")[0]
                        if "-" in seg: gift_name = seg.rsplit("-", 1)[0]
                    except: pass
                text = f"🚨 <b>ПОРА ДЕЙСТВОВАТЬ!</b>\n\n{emoji} <b>{_esc(gift_name)}</b> · {label}\n🕐 Наступило!\n"
                if link: text += f"\n🔗 <a href='{link}'>Открыть NFT</a>"
                try: await bot.send_message(t["user_id"], text)
                except: pass
                await conn.execute("UPDATE timers SET notified=1 WHERE id=?", (t["id"],))
                await conn.commit()
        except: pass
        await asyncio.sleep(60)

async def daily_backup_task():
    last_backup_ts = 0
    while True:
        try:
            now_ts = time.time()
            if now_ts - last_backup_ts >= 6 * 3600:
                try:
                    await create_and_send_backup(ADMIN_IDS[0])
                    last_backup_ts = now_ts
                except: pass
        except: pass
        await asyncio.sleep(300)

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
        
    asyncio.create_task(timer_checker())
    asyncio.create_task(daily_backup_task())
    
    try: await bot.delete_webhook(drop_pending_updates=True)
    except: pass
    logger.info("🤖 Бот запущен!")
    
    offset = 0
    while True:
        try:
            updates = await bot.get_updates(offset=offset, timeout=30, allowed_updates=["message", "callback_query", "inline_query", "chosen_inline_result", "widget_query"])
            for update in updates:
                offset = update.update_id + 1
                update_dict = update.model_dump()
                if "widget_query" in update_dict and update_dict["widget_query"]:
                    asyncio.create_task(handle_widget_query_raw(update_dict["widget_query"], bot, BOT_TOKEN, get_user_star_rate=get_user_star_rate, get_gram_price=get_gram_price, get_db=get_db))
                    continue
                try: await dp.feed_update(bot, update)
                except Exception as e: logger.error(f"feed_update error: {e}")
        except Exception as e:
            logger.error(f"Polling error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
