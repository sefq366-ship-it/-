import asyncio
import aiohttp
import logging
from aiogram import Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

GIFT_SAT_API = "https://gift-satellite.dev/api"
GIFT_SAT_TOKEN = "ВСТАВЬ_СВОЙ_ТОКЕН_GIFTSAT"

class GiftSatStates(StatesGroup):
    waiting_custom_sell = State()

class GiftSatModule:
    def __init__(self, bot, get_db, get_user_lang, ADMIN_IDS, AddProfit=None):
        self.bot = bot
        self.get_db = get_db
        self.get_user_lang = get_user_lang
        self.ADMIN_IDS = ADMIN_IDS
        self.AddProfit = AddProfit

    async def api_get(self, path, params=None):
        headers = {"Authorization": f"Token {GIFT_SAT_TOKEN}"}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{GIFT_SAT_API}{path}", headers=headers, params=params or {}) as r:
                    if r.status != 200: return None
                    return await r.json()
        except: return None

    async def api_post(self, path, body=None):
        headers = {"Authorization": f"Token {GIFT_SAT_TOKEN}"}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(f"{GIFT_SAT_API}{path}", headers=headers, json=body or {}) as r:
                    if r.status not in (200, 201): return None
                    return await r.json()
        except: return None

    async def get_last_sale_price(self, slug, collection):
        body = {"page": 0, "pageSize": 20, "sortBy": "date"}
        data = await self.api_post(f"/history/{collection}", body)
        if not data or "content" not in data: return None
        for sale in data["content"]:
            if sale.get("slug") == slug:
                price = float(sale.get("normalizedPrice") or 0)
                market = sale.get("market", "")
                return (price, market)
        return None

    async def ask_sell_price(self, chat_id, slug, price_ton, force_manual=False):
        if force_manual:
            await self.bot.send_message(chat_id, f"💰 NFT <code>{slug}</code> продалась на Fragment.\nВведи сумму продажи в TON:")
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Да, {price_ton:.2f} TON", callback_data=f"sell_yes:{slug}:{price_ton}")],
            [InlineKeyboardButton(text="✏️ Другая сумма", callback_data=f"sell_custom:{slug}")]
        ])
        await self.bot.send_message(chat_id, f"💰 NFT <code>{slug}</code> продалась за <b>{price_ton:.2f} TON</b>?\nЗафиксировать?", reply_markup=kb)

    async def poll_sales(self):
        while True:
            try:
                conn = await self.get_db()
                cur = await conn.execute("SELECT DISTINCT slug FROM tracking WHERE state='bought'")
                slugs = [row["slug"] for row in await cur.fetchall()]
                collections = {s.rsplit("-", 1)[0] for s in slugs if "-" in s}

                for coll in collections:
                    data = await self.api_post(f"/history/{coll}", {"page": 0, "pageSize": 20, "sortBy": "date"})
                    if not data or "content" not in data: continue
                    for sale in data["content"]:
                        slug = sale.get("slug")
                        if slug not in slugs: continue
                        price = float(sale.get("normalizedPrice") or 0)
                        market = sale.get("market", "")
                        cur2 = await conn.execute("SELECT id, user_id FROM tracking WHERE slug=? AND state='bought'", (slug,))
                        for row in await cur2.fetchall():
                            if market == "telegram":
                                await self.ask_sell_price(row["user_id"], slug, 0, force_manual=True)
                                await conn.execute("UPDATE tracking SET state='awaiting_manual' WHERE id=?", (row["id"],))
                            else:
                                await self.ask_sell_price(row["user_id"], slug, price)
                    await conn.commit()
            except Exception as e:
                logger.error(f"poll_sales: {e}")
            await asyncio.sleep(120)

    def register(self, dp: Dispatcher):
        get_db = self.get_db

        @dp.callback_query(F.data.startswith("sell_yes:"))
        async def sell_yes(callback: CallbackQuery):
            parts = callback.data.split(":")
            slug, price = parts[1], float(parts[2])
            conn = await get_db()
            cur = await conn.execute("SELECT id, sale_id FROM tracking WHERE user_id=? AND slug=? AND state='bought'", (callback.from_user.id, slug))
            row = await cur.fetchone()
            if not row:
                await callback.answer("Запись не найдена", show_alert=True)
                return
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
            try: price = float(message.text.replace(",", "."))
            except: return await message.answer("Введи число.")
            data = await state.get_data()
            slug = data.get("custom_sell_slug")
            conn = await get_db()
            cur = await conn.execute("SELECT id, sale_id FROM tracking WHERE user_id=? AND slug=? AND state='bought'", (message.from_user.id, slug))
            row = await cur.fetchone()
            if row:
                await conn.execute("UPDATE sales SET sell_amount=? WHERE id=?", (price, row["sale_id"]))
                await conn.execute("UPDATE tracking SET state='sold' WHERE id=?", (row["id"],))
                await conn.commit()
                await message.answer(f"✅ Зафиксировано: {price:.2f} TON")
            else:
                await message.answer("Запись не найдена.")
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
            try: price = float(message.text.replace(",", "."))
            except: return
            await conn.execute("UPDATE sales SET sell_amount=? WHERE id=?", (price, row["sale_id"]))
            await conn.execute("UPDATE tracking SET state='sold' WHERE id=?", (row["id"],))
            await conn.commit()
            await message.answer(f"✅ Зафиксировано: {price:.2f} TON")

def init_gift_sat(dp: Dispatcher, bot, get_db, get_user_lang, ADMIN_IDS, AddProfit=None):
    module = GiftSatModule(bot, get_db, get_user_lang, ADMIN_IDS, AddProfit)
    module.register(dp)
    return module
