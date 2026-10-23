import asyncio
import aiohttp
import logging
from datetime import datetime
from aiogram import Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

GIFT_SAT_API = "https://gift-satellite.dev/api"
GIFT_SAT_TOKEN = "ВСТАВЬ_СВОЙ_ТОКЕН_GIFTSAT"

STARS_TO_TON_RATE = 0.013


def stars_to_ton(stars: float) -> float:
    return round(stars * STARS_TO_TON_RATE, 4)


class GiftSatStates(StatesGroup):
    waiting_custom_sell = State()


class GiftSatModule:
    def __init__(self, bot, get_db, get_user_lang, ADMIN_IDS, AddProfit=None):
        self.bot = bot
        self.get_db = get_db
        self.get_user_lang = get_user_lang
        self.ADMIN_IDS = ADMIN_IDS
        self.AddProfit = AddProfit

    # =========================================================
    # API
    # =========================================================
    async def api_get(self, path, params=None):
        headers = {"Authorization": f"Token {GIFT_SAT_TOKEN}"}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{GIFT_SAT_API}{path}", headers=headers, params=params or {}) as r:
                    if r.status != 200:
                        logger.warning(f"GiftSat {path}: HTTP {r.status}")
                        return None
                    return await r.json()
        except Exception as e:
            logger.warning(f"GiftSat {path}: {e}")
            return None

    async def api_post(self, path, body=None):
        headers = {"Authorization": f"Token {GIFT_SAT_TOKEN}"}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(f"{GIFT_SAT_API}{path}", headers=headers, json=body or {}) as r:
                    if r.status not in (200, 201):
                        logger.warning(f"GiftSat {path}: HTTP {r.status}")
                        return None
                    return await r.json()
        except Exception as e:
            logger.warning(f"GiftSat {path}: {e}")
            return None

    # =========================================================
    # Получение цен
    # =========================================================
    async def get_last_purchase_price(self, slug):
        data = await self.api_get("/user/purchases", {"page": 0})
        if not data:
            return None
        for p in data.get("purchases", []):
            if p.get("slug") == slug:
                price = float(p.get("price") or 0)
                currency = p.get("currency", "ton")
                if currency == "stars":
                    return stars_to_ton(price)
                return price
        return None

    async def get_last_sale_price(self, slug, collection):
        data = await self.api_post(f"/history/{collection}", {"page": 0, "pageSize": 20, "sortBy": "date"})
        if not data:
            return None
        for sale in data.get("content", []):
            if sale.get("slug") == slug:
                return float(sale.get("normalizedPrice") or 0), sale.get("market", "")
        return None

    # =========================================================
    # Уведомления с кнопками
    # =========================================================
    async def ask_buy_price(self, chat_id, slug, price_ton):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Да, {price_ton:.2f} TON", callback_data=f"buy_auto:{price_ton}")],
            [InlineKeyboardButton(text="✏️ Введу вручную", callback_data="buy_manual")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_deal")]
        ])
        await self.bot.send_message(
            chat_id,
            f"🛒 NFT <code>{slug}</code> куплена за <b>{price_ton:.2f} TON</b>?",
            reply_markup=kb
        )

    async def ask_sell_price(self, chat_id, slug, price_ton, force_manual=False):
        if force_manual:
            await self.bot.send_message(
                chat_id,
                f"💰 NFT <code>{slug}</code> продалась на Fragment.\n"
                f"Введи сумму продажи в TON:"
            )
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Да, {price_ton:.2f} TON", callback_data=f"sell_yes:{slug}:{price_ton}")],
            [InlineKeyboardButton(text="✏️ Другая сумма", callback_data=f"sell_custom:{slug}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"sell_cancel:{slug}")]
        ])
        await self.bot.send_message(
            chat_id,
            f"💰 NFT <code>{slug}</code> продалась за <b>{price_ton:.2f} TON</b>?\n"
            f"Зафиксировать?",
            reply_markup=kb
        )

    # =========================================================
    # Polling продаж
    # =========================================================
    async def poll_sales(self):
        while True:
            try:
                conn = await self.get_db()
                cur = await conn.execute("SELECT DISTINCT slug FROM tracking WHERE state='bought'")
                slugs = [row["slug"] for row in await cur.fetchall()]
                collections = {s.rsplit("-", 1)[0] for s in slugs if "-" in s}

                for coll in collections:
                    data = await self.api_post(f"/history/{coll}", {"page": 0, "pageSize": 20, "sortBy": "date"})
                    if not data:
                        continue
                    for sale in data.get("content", []):
                        slug = sale["slug"]
                        price = float(sale.get("normalizedPrice") or 0)
                        market = sale.get("market", "")

                        cur2 = await conn.execute(
                            "SELECT id, user_id FROM tracking WHERE slug=? AND state='bought'",
                            (slug,)
                        )
                        for row in await cur2.fetchall():
                            if market == "telegram":
                                await self.ask_sell_price(row["user_id"], slug, 0, force_manual=True)
                                await conn.execute(
                                    "UPDATE tracking SET state='awaiting_manual' WHERE id=?",
                                    (row["id"],)
                                )
                            else:
                                await self.ask_sell_price(row["user_id"], slug, price)
                    await conn.commit()
            except Exception as e:
                logger.error(f"poll_sales: {e}")
            await asyncio.sleep(120)

    # =========================================================
    # Регистрация хендлеров
    # =========================================================
    def register(self, dp: Dispatcher):
        bot = self.bot
        get_db = self.get_db
        get_user_lang = self.get_user_lang
        AddProfit = self.AddProfit

        @dp.callback_query(F.data.startswith("buy_auto:"))
        async def buy_auto(callback: CallbackQuery, state: FSMContext):
            price = float(callback.data.split(":")[1])
            await state.update_data(buy_amount=price)
            await callback.message.edit_text(f"✅ Покупка зафиксирована: {price:.2f} TON")
            await callback.answer()
            lang = await get_user_lang(callback.from_user.id)
            from messages import MESSAGES
            if AddProfit is not None:
                await state.set_state(AddProfit.waiting_for_category)
            await callback.message.answer(MESSAGES[lang]["enter_collection"])

        @dp.callback_query(F.data == "buy_manual")
        async def buy_manual(callback: CallbackQuery):
            await callback.answer()
            await callback.message.edit_text("Введи сумму покупки в TON:")

        @dp.callback_query(F.data.startswith("sell_yes:"))
        async def sell_yes(callback: CallbackQuery):
            parts = callback.data.split(":")
            slug = parts[1]
            price = float(parts[2])
            uid = callback.from_user.id

            conn = await get_db()
            cur = await conn.execute(
                "SELECT id, sale_id FROM tracking WHERE user_id=? AND slug=? AND state='bought'",
                (uid, slug)
            )
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
            try:
                price = float(message.text.replace(",", "."))
            except:
                await message.answer("Введи число.")
                return

            data = await state.get_data()
            slug = data.get("custom_sell_slug")
            uid = message.from_user.id

            conn = await get_db()
            cur = await conn.execute(
                "SELECT id, sale_id FROM tracking WHERE user_id=? AND slug=? AND state='bought'",
                (uid, slug)
            )
            row = await cur.fetchone()
            if not row:
                await message.answer("Запись не найдена.")
                await state.clear()
                return

            await conn.execute("UPDATE sales SET sell_amount=? WHERE id=?", (price, row["sale_id"]))
            await conn.execute("UPDATE tracking SET state='sold' WHERE id=?", (row["id"],))
            await conn.commit()

            await message.answer(f"✅ Зафиксировано: {price:.2f} TON")
            await state.clear()

        @dp.callback_query(F.data.startswith("sell_cancel:"))
        async def sell_cancel(callback: CallbackQuery):
            slug = callback.data.split(":")[1]
            uid = callback.from_user.id

            conn = await get_db()
            await conn.execute(
                "UPDATE tracking SET state='sold' WHERE user_id=? AND slug=? AND state IN ('bought','awaiting_manual')",
                (uid, slug)
            )
            await conn.commit()

            await callback.message.edit_text("❌ Отменено. Запись закрыта без обновления цены.")
            await callback.answer()

        @dp.message(F.text.regexp(r"^\d+(?:[.,]\d+)?$"))
        async def catch_manual_sell(message: Message, state: FSMContext):
            if await state.get_state() is not None:
                return

            conn = await get_db()
            cur = await conn.execute(
                "SELECT id, slug, sale_id FROM tracking WHERE user_id=? AND state='awaiting_manual' LIMIT 1",
                (message.from_user.id,)
            )
            row = await cur.fetchone()
            if not row:
                return

            try:
                price = float(message.text.replace(",", "."))
            except:
                return

            await conn.execute("UPDATE sales SET sell_amount=? WHERE id=?", (price, row["sale_id"]))
            await conn.execute("UPDATE tracking SET state='sold' WHERE id=?", (row["id"],))
            await conn.commit()

            await message.answer(f"✅ Зафиксировано: {price:.2f} TON")


# =========================================================
# Точка входа модуля
# =========================================================
def init_gift_sat(dp: Dispatcher, bot, get_db, get_user_lang, ADMIN_IDS, AddProfit=None):
    module = GiftSatModule(bot, get_db, get_user_lang, ADMIN_IDS, AddProfit)
    module.register(dp)
    return module
