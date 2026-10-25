import asyncio
import aiohttp
import logging
import re
import time
from datetime import datetime, timedelta
from aiogram import Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

GIFT_SAT_API = "https://gift-satellite.dev/api"
GIFT_SAT_TOKEN = "ВСТАВЬ_СВОЙ_ТОКЕН" # <--- ТОКЕН

class GiftSatStates(StatesGroup):
    waiting_custom_sell = State()

class GiftSatModule:
    def __init__(self, bot, get_db, get_user_lang, ADMIN_IDS, AddProfit=None):
        self.bot = bot
        self.get_db = get_db
        self.get_user_lang = get_user_lang
        self.ADMIN_IDS = ADMIN_IDS
        self.AddProfit = AddProfit
        self._cache = {}
        self._cache_ttl = 300
        self._session = None

    async def get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def slug_to_collection_name(self, slug: str) -> str:
        if not slug: return slug
        parts = slug.split("-")
        return "".join(word.capitalize() for word in parts)

    def extract_slug_from_link(self, nft_link: str) -> str:
        if not nft_link: return None
        link = nft_link.strip().split("?")[0].split("#")[0].rstrip("/")
        patterns = [r"/nft/([^/?#]+)", r"/gift/([^/?#]+)", r"gift/([^/?#]+)"]
        for pattern in patterns:
            match = re.search(pattern, link)
            if match:
                slug = match.group(1)
                if re.match(r'^[A-Za-z0-9-]+$', slug): return slug
        return None

    async def get_cached(self, cache_key: str, fetch_func, *args, **kwargs):
        current_time = time.time()
        if cache_key in self._cache:
            value, timestamp = self._cache[cache_key]
            if current_time - timestamp < self._cache_ttl:
                return value
        result = await fetch_func(*args, **kwargs)
        self._cache[cache_key] = (result, current_time)
        return result

    async def api_get(self, path, params=None):
        headers = {"Authorization": f"Token {GIFT_SAT_TOKEN}"}
        try:
            session = await self.get_session()
            async with session.get(f"{GIFT_SAT_API}{path}", headers=headers, params=params or {}, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 401: logger.error("[GiftSat] 401 Unauthorized"); return None
                if r.status == 429: logger.warning("[GiftSat] 429 Rate limit"); return None
                if r.status != 200: return None
                return await r.json()
        except Exception as e:
            logger.warning(f"[GiftSat] GET {path}: {e}")
            return None

    async def api_post(self, path, body=None):
        headers = {"Authorization": f"Token {GIFT_SAT_TOKEN}"}
        try:
            session = await self.get_session()
            async with session.post(f"{GIFT_SAT_API}{path}", headers=headers, json=body or {}, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 401: logger.error("[GiftSat] 401 Unauthorized"); return None
                if r.status == 429: logger.warning("[GiftSat] 429 Rate limit"); return None
                if r.status not in (200, 201): return None
                return await r.json()
        except Exception as e:
            logger.warning(f"[GiftSat] POST {path}: {e}")
            return None

    async def validate_token(self):
        data = await self.api_get("/user/me")
        if not data:
            logger.error("❌ [GiftSat] Невалидный токен или API недоступен!")
            return False
        logger.info(f"✅ [GiftSat] Авторизован как: {data.get('username', 'unknown')}")
        return True

    async def get_last_purchase_price(self, slug: str, user_star_rate: float = 0.013):
        cache_key = f"purchase_{slug}"
        async def fetch():
            data = await self.api_get("/user/purchases", {"page": 0})
            if not data or "purchases" not in data: return None
            for p in data["purchases"]:
                if p.get("slug") == slug:
                    price = float(p.get("price") or 0)
                    if p.get("currency") == "stars": return round(price * user_star_rate, 4)
                    return price
            return None
        return await self.get_cached(cache_key, fetch)

    async def get_last_sale_price(self, slug: str, collection: str):
        collection_name = self.slug_to_collection_name(collection)
        cache_key = f"sale_{slug}"
        async def fetch():
            body = {"page": 0, "pageSize": 20, "sortBy": "date"}
            data = await self.api_post(f"/history/{collection_name}", body)
            if not data or "content" not in data: return None
            for sale in data["content"]:
                if sale.get("slug") == slug:
                    price = float(sale.get("normalizedPrice") or 0)
                    if price > 0: return (price, sale.get("market", "unknown"))
            return None
        return await self.get_cached(cache_key, fetch)

    async def get_listing_price(self, slug: str, collection: str):
        collection_name = self.slug_to_collection_name(collection)
        cache_key = f"listing_{slug}"
        async def fetch():
            for market in ["portals", "tonnel", "mrkt"]:
                try:
                    data = await self.api_get(f"/search/{market}/{collection_name}")
                    if data and isinstance(data, list):
                        for listing in data:
                            if listing.get("slug") == slug:
                                price = float(listing.get("normalizedPrice") or 0)
                                if price > 0: return (price, market)
                    await asyncio.sleep(0.3)
                except: continue
            return None
        return await self.get_cached(cache_key, fetch)

    async def ask_sell_price(self, chat_id: int, slug: str, price_ton: float, force_manual: bool = False):
        if force_manual:
            await self.bot.send_message(chat_id, f"💰 NFT <code>{slug}</code> продалась на Fragment (Telegram).\nВведи сумму продажи в TON:")
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Да, {price_ton:.2f} TON", callback_data=f"sell_yes:{slug}:{price_ton}")],
            [InlineKeyboardButton(text="✏️ Другая сумма", callback_data=f"sell_custom:{slug}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"sell_cancel:{slug}")]
        ])
        await self.bot.send_message(chat_id, f"💰 NFT <code>{slug}</code> продалась за <b>{price_ton:.2f} TON</b>?\nЗафиксировать продажу?", reply_markup=kb)

    async def poll_sales(self):
        while True:
            try:
                conn = await self.get_db()
                cur = await conn.execute("SELECT DISTINCT slug FROM tracking WHERE state='bought'")
                slugs = [row["slug"] for row in await cur.fetchall()]
                if not slugs:
                    await asyncio.sleep(120)
                    continue
                collections = {}
                for slug in slugs:
                    if "-" in slug:
                        c_slug = slug.rsplit("-", 1)[0]
                        collections.setdefault(c_slug, []).append(slug)
                for c_slug, c_slugs in collections.items():
                    c_name = self.slug_to_collection_name(c_slug)
                    data = await self.api_post(f"/history/{c_name}", {"page": 0, "pageSize": 20, "sortBy": "date"})
                    if not data or "content" not in data: continue
                    for sale in data["content"]:
                        s_slug = sale.get("slug")
                        if s_slug not in c_slugs: continue
                        price = float(sale.get("normalizedPrice") or 0)
                        market = sale.get("market", "unknown")
                        sold_at = sale.get("soldAt")
                        if sold_at:
                            try:
                                s_time = datetime.fromisoformat(sold_at.replace("Z", "+00:00"))
                                if s_time < datetime.now(s_time.tzinfo) - timedelta(hours=24): continue
                            except: pass
                        cur2 = await conn.execute("SELECT id, user_id FROM tracking WHERE slug=? AND state='bought'", (s_slug,))
                        for row in await cur2.fetchall():
                            if market == "telegram":
                                await self.ask_sell_price(row["user_id"], s_slug, 0, force_manual=True)
                                await conn.execute("UPDATE tracking SET state='awaiting_manual' WHERE id=?", (row["id"],))
                            else:
                                await self.ask_sell_price(row["user_id"], s_slug, price)
                    await conn.commit()
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"[GiftSat] poll_sales error: {e}")
            await asyncio.sleep(120)

    def register(self, dp: Dispatcher):
        get_db = self.get_db

        @dp.callback_query(F.data.startswith("sell_yes:"))
        async def sell_yes(callback: CallbackQuery):
            parts = callback.data.split(":"); slug = parts[1]; price = float(parts[2])
            conn = await get_db()
            cur = await conn.execute("SELECT id, sale_id FROM tracking WHERE user_id=? AND slug=? AND state='bought'", (callback.from_user.id, slug))
            row = await cur.fetchone()
            if not row: return await callback.answer("Запись не найдена", show_alert=True)
            await conn.execute("UPDATE sales SET sell_amount=? WHERE id=?", (price, row["sale_id"]))
            await conn.execute("UPDATE tracking SET state='sold' WHERE id=?", (row["id"],))
            await conn.commit()
            await callback.message.edit_text(f"✅ Продажа зафиксирована: {price:.2f} TON")
            await callback.answer()

        @dp.callback_query(F.data.startswith("sell_custom:"))
        async def sell_custom(callback: CallbackQuery, state: FSMContext):
            slug = callback.data.split(":")[1]
            await state.update_data(custom_sell_slug=slug)
            await state.set_state(GiftSatStates.waiting_custom_sell)
            await callback.message.edit_text(f"Введи сумму продажи для <code>{slug}</code> в TON:")
            await callback.answer()

        @dp.message(GiftSatStates.waiting_custom_sell)
        async def sell_custom_input(message: Message, state: FSMContext):
            try:
                price = float(message.text.replace(",", "."))
                if price <= 0: raise ValueError
            except: return await message.answer("❌ Введи корректное число.")
            data = await state.get_data(); slug = data.get("custom_sell_slug")
            conn = await get_db()
            cur = await conn.execute("SELECT id, sale_id FROM tracking WHERE user_id=? AND slug=? AND state='bought'", (message.from_user.id, slug))
            row = await cur.fetchone()
            if row:
                await conn.execute("UPDATE sales SET sell_amount=? WHERE id=?", (price, row["sale_id"]))
                await conn.execute("UPDATE tracking SET state='sold' WHERE id=?", (row["id"],))
                await conn.commit()
                await message.answer(f"✅ Зафиксировано: {price:.2f} TON")
            else: await message.answer("❌ Запись не найдена.")
            await state.clear()

        @dp.callback_query(F.data.startswith("sell_cancel:"))
        async def sell_cancel(callback: CallbackQuery):
            slug = callback.data.split(":")[1]
            conn = await get_db()
            await conn.execute("UPDATE tracking SET state='sold' WHERE user_id=? AND slug=? AND state IN ('bought','awaiting_manual')", (callback.from_user.id, slug))
            await conn.commit()
            await callback.message.edit_text("❌ Отменено. Запись закрыта без обновления цены.")
            await callback.answer()

        @dp.message(F.text.regexp(r"^\d+(?:[.,]\d+)?$"))
        async def catch_manual_sell(message: Message, state: FSMContext):
            if await state.get_state() is not None: return
            conn = await get_db()
            cur = await conn.execute("SELECT id, slug, sale_id FROM tracking WHERE user_id=? AND state='awaiting_manual' LIMIT 1", (message.from_user.id,))
            row = await cur.fetchone()
            if not row: return
            try:
                price = float(message.text.replace(",", "."))
                if price <= 0: raise ValueError
            except: return await message.answer("❌ Введи корректное число.")
            await conn.execute("UPDATE sales SET sell_amount=? WHERE id=?", (price, row["sale_id"]))
            await conn.execute("UPDATE tracking SET state='sold' WHERE id=?", (row["id"],))
            await conn.commit()
            await message.answer(f"✅ Зафиксировано: {price:.2f} TON")

def init_gift_sat(dp: Dispatcher, bot, get_db, get_user_lang, ADMIN_IDS, AddProfit=None):
    module = GiftSatModule(bot, get_db, get_user_lang, ADMIN_IDS, AddProfit)
    module.register(dp)
    return module
