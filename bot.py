import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    InlineQuery,
    ChosenInlineResult,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest


# =====================================
# НАСТРОЙКИ
# =====================================

BOT_TOKEN = "8539532805:AAF4MMpFlvMSqIFTxVmSW9NLW0sBekrAlR4"
BOT_USERNAME = "TestbotemociyamiBot"
ADMIN_ID = 1012040843

dp = Dispatcher()


# =====================================
# НАБОРЫ ПРЕМИУМ-ЭМОДЗИ
# =====================================

EMOJI_SETS = {
    "1": [
        ("5296742257146241213", "💎"),
        ("5424976816530014958", "👛"),
        ("5224692870790797620", "🔗"),
    ],
}


# =====================================
# ФОРМИРОВАНИЕ HTML
# =====================================

def make_emoji_text(emoji_set):
    return " ".join(
        f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
        for emoji_id, fallback in emoji_set
    )


# =====================================
# КНОПКА ПЕРЕХОДА В БОТА
# =====================================

def make_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Перейти в бота",
                    url=f"https://t.me/{BOT_USERNAME}?start=inline",
                )
            ]
        ]
    )


# =====================================
# КОМАНДА /START
# =====================================

@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Привет! 👋\n\n"
        "Я отправляю наборы премиум-эмодзи.\n\n"
        f"В любом чате введи:\n@{BOT_USERNAME} 1\n\n"
        "Выбери результат, чтобы отправить набор."
    )


# =====================================
# INLINE MODE
# =====================================

@dp.inline_query()
async def inline_handler(query: InlineQuery):
    search = query.query.strip()

    if search not in EMOJI_SETS:
        await query.answer(
            results=[],
            cache_time=0,
            is_personal=True,
        )
        return

    emoji_set = EMOJI_SETS[search]

    fallback_text = " ".join(
        fallback for _, fallback in emoji_set
    )

    result = InlineQueryResultArticle(
        id=f"emoji_set_{search}",
        title="💎 Премиум-эмодзи №1",
        description="Отправить набор премиум-эмодзи",
        input_message_content=InputTextMessageContent(
            message_text=fallback_text,
        ),
        reply_markup=make_keyboard(),
    )

    await query.answer(
        results=[result],
        cache_time=0,
        is_personal=True,
    )


# =====================================
# РЕДАКТИРОВАНИЕ ИНЛАЙН-СООБЩЕНИЯ
# =====================================

@dp.chosen_inline_result()
async def chosen_result_handler(
    chosen: ChosenInlineResult,
    bot: Bot,
):
    if chosen.result_id != "emoji_set_1":
        return

    inline_message_id = chosen.inline_message_id

    if not inline_message_id:
        logging.warning(
            "inline_message_id отсутствует. "
            "Проверь настройки Inline Feedback в BotFather."
        )
        return

    custom_text = make_emoji_text(EMOJI_SETS["1"])

    try:
        await bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=custom_text,
            parse_mode="HTML",
            reply_markup=make_keyboard(),
        )

        logging.info("Инлайн-сообщение успешно отредактировано.")

    except TelegramBadRequest as error:
        logging.error("Ошибка Telegram API: %s", error)


# =====================================
# ЗАПУСК
# =====================================

async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=BOT_TOKEN)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "inline_query",
                "chosen_inline_result",
            ],
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
