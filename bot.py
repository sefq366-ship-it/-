import asyncio
import logging
import random
import time
from collections import defaultdict
from datetime import date

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineQuery, InlineQueryResultArticle,
    InputTextMessageContent, BotCommand,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from data import (
    OTCHESTVA, RAZGOVORNYE, TRANSLIT, UDARENIYA, NAME_ORIGIN,
    CELEBRITIES, SAINTS, FACTS, CHARACTER, PREDICTIONS, TOASTS,
    THEMES, EXAMPLE_OTCH,
)

# ===================== КОНФИГ =====================
BOT_TOKEN = "8910348962:AAHnP_GYZasuMY_HcmRwbjj2NfmQdpIf_S0"
ADMIN_IDS = {1012040843}          # <-- впишите свой telegram id
ANTIFLOOD_LIMIT = 6
ANTIFLOOD_WINDOW = 5.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bot")

dp = Dispatcher()
_user_hits = defaultdict(list)

# ===================== УТИЛИТЫ =====================
def is_flood(uid: int) -> bool:
    now = time.time()
    hits = _user_hits[uid]
    hits[:] = [t for t in hits if now - t < ANTIFLOOD_WINDOW]
    hits.append(now)
    return len(hits) > ANTIFLOOD_LIMIT

def normalize(s: str) -> str:
    return s.strip().lower().replace("ё", "е")

def capitalize_otch(o: str) -> str:
    return o[:1].upper() + o[1:]

def translit(s: str) -> str:
    return "".join(TRANSLIT.get(ch.lower(), ch) for ch in s).capitalize()

def udarenie(o: str) -> str:
    return UDARENIYA.get(normalize(o), o)

def skloneniya(otch: str, female: bool):
    """Простые склонения по правилам."""
    base = otch[:-2] if otch.endswith("ич") else otch[:-2]  # грубо
    if female:
        return [
            otch,                                   # им.
            otch[:-1] + "у",                        # род. (Ивановны -> Ивановну? упрощённо)
            otch[:-1] + "е",                        # дат.
            otch,                                   # вин.
            otch[:-1] + "ой",                       # тв.
            otch[:-1] + "е",                        # пр.
        ]
    return [
        otch, otch + "а", otch + "у", otch + "а", otch + "ем", "о " + otch + "е"
    ]

def find_father(text: str):
    raw = text.strip().strip("?!.,;:")
    if not raw or len(raw) > 60:
        return None
    word = normalize(raw)
    if word in OTCHESTVA:
        m, (f, name) = word, OTCHESTVA[word]
        return name, capitalize_otch(word), word.endswith("овна") or word.endswith("евна") or word.endswith("ична")
    for m, (f, name) in OTCHESTVA.items():
        if word == f:
            return name, capitalize_otch(word), True
    if word in RAZGOVORNYE:
        return RAZGOVORNYE[word], capitalize_otch(word), False
    for m, (f, name) in OTCHESTVA.items():
        if m in word or f in word:
            return name, capitalize_otch(word), f in word
    return None

def find_otchestvo_by_name(father: str, female: bool):
    for m, (f, name) in OTCHESTVA.items():
        if normalize(name) == normalize(father):
            return capitalize_otch(f if female else m)
    return None

def check_achievements(uid: int, correct: bool, streak: int):
    unlocked = []
    if db.grant_achievement(uid, "first_step"):
        unlocked.append("🐣 Первый шаг — задал первый вопрос")
    if streak >= 10 and db.grant_achievement(uid, "streak_10"):
        unlocked.append("🔥 Серия 10 подряд")
    if streak >= 25 and db.grant_achievement(uid, "streak_25"):
        unlocked.append("⚡ Серия 25 подряд")
    if correct and db.grant_achievement(uid, "quiz_first"):
        unlocked.append("🎯 Первая победа в викторине")
    return unlocked

# ===================== КЛАВИАТУРЫ =====================
def main_menu(uid=None):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 Викторина", callback_data="quiz")
    kb.button(text="🎲 Пример", callback_data="example")
    kb.button(text="📊 Профиль", callback_data="profile")
    kb.button(text="🏆 Топ", callback_data="top")
    kb.button(text="⭐ Избранное", callback_data="fav")
    kb.button(text="📜 История", callback_data="history")
    kb.button(text="💡 Факт", callback_data="fact")
    kb.button(text="🔮 Предсказание", callback_data="predict")
    kb.button(text="🥂 Тост", callback_data="toast")
    kb.button(text="🎨 Тема", callback_data="theme")
    kb.button(text="ℹ️ Помощь", callback_data="help")
    kb.adjust(2, 2, 2, 2, 2, 1)
    return kb.as_markup()

def quiz_kb(correct_name: str):
    options = {correct_name}
    while len(options) < 4:
        options.add(random.choice(list(OTCHESTVA.values()))[1])
    options = list(options)
    random.shuffle(options)
    kb = InlineKeyboardBuilder()
    for opt in options:
        kb.button(text=opt, callback_data=f"quizans:{opt}")
    kb.adjust(2)
    return kb.as_markup()

# ===================== ХЭНДЛЕРЫ =====================
@dp.message(CommandStart(deep_link=True))
async def cmd_start_ref(message: Message, command):
    ref = command.args
    referred_by = int(ref) if ref and ref.isdigit() else None
    db.create_user(message.from_user.id, message.from_user.username, message.from_user.first_name, referred_by)
    if referred_by and referred_by != message.from_user.id:
        db.add_points(referred_by, 5)
        try:
            await message.bot.send_message(referred_by, "🎁 По твоей ссылке пришёл друг! +5 очков")
        except Exception:
            pass
    await cmd_start(message)

@dp.message(CommandStart())
async def cmd_start(message: Message):
    db.create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    text = (
        f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        "Я умею по <b>отчеству</b> определять имя твоего отца.\n"
        "А ещё: викторина, профиль, топ, избранное, история, факты.\n\n"
        "Просто напиши отчество: <code>Иванович</code> или <code>Петровна</code>.\n\n"
        f"🔗 Твоя реферальная ссылка:\n"
        f"<code>https://t.me/{(await message.bot.me()).username}?start={message.from_user.id}</code>"
    )
    await message.answer(text, reply_markup=main_menu())

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Что я умею</b>\n\n"
        "• Определяю имя отца по отчеству\n"
        "• Обратно: имя → отчество\n"
        "• Склонения, транслит, ударение\n"
        "• Викторина, очки, достижения, топ\n"
        "• Профиль, история, избранное\n"
        "• Факты, происхождение имён, святые, знаменитости\n"
        "• Предсказания и тосты\n"
        "• Inline-режим: <code>@бот Иванович</code> в любом чате\n\n"
        "Команды: /start /help /profile /top /fav /history /quiz /fact /random",
        reply_markup=main_menu(),
    )

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    await send_profile(message)

@dp.message(Command("top"))
async def cmd_top(message: Message):
    await send_top(message)

@dp.message(Command("fav"))
async def cmd_fav(message: Message):
    await send_fav(message)

@dp.message(Command("history"))
async def cmd_history(message: Message):
    await send_history(message)

@dp.message(Command("quiz"))
async def cmd_quiz(message: Message):
    await start_quiz(message)

@dp.message(Command("fact"))
async def cmd_fact(message: Message):
    await message.answer("💡 " + random.choice(FACTS))

@dp.message(Command("random"))
async def cmd_random(message: Message):
    m, (f, name) = random.choice(list(OTCHESTVA.items()))
    await message.answer(f"🎲 <b>{random.choice([m, f]).capitalize()}</b> → отец <b>{name}</b>")

# ---- callback-хэндлеры ----
@dp.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery):
    await send_profile(call.message, call.from_user.id)
    await call.answer()

@dp.callback_query(F.data == "top")
async def cb_top(call: CallbackQuery):
    await send_top(call.message)
    await call.answer()

@dp.callback_query(F.data == "fav")
async def cb_fav(call: CallbackQuery):
    await send_fav(call.message, call.from_user.id)
    await call.answer()

@dp.callback_query(F.data == "history")
async def cb_history(call: CallbackQuery):
    await send_history(call.message, call.from_user.id)
    await call.answer()

@dp.callback_query(F.data == "example")
async def cb_example(call: CallbackQuery):
    m, (f, name) = random.choice(list(OTCHESTVA.items()))
    await call.message.answer(f"Например: <b>{m.capitalize()}</b> → отец <b>{name}</b>")
    await call.answer()

@dp.callback_query(F.data == "fact")
async def cb_fact(call: CallbackQuery):
    await call.message.answer("💡 " + random.choice(FACTS))
    await call.answer()

@dp.callback_query(F.data == "predict")
async def cb_predict(call: CallbackQuery):
    await call.message.answer("🔮 " + random.choice(PREDICTIONS))
    await call.answer()

@dp.callback_query(F.data == "toast")
async def cb_toast(call: CallbackQuery):
    await call.message.answer("🥂 " + random.choice(TOASTS))
    await call.answer()

@dp.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery):
    await cmd_help(call.message)
    await call.answer()

@dp.callback_query(F.data == "theme")
async def cb_theme(call: CallbackQuery):
    kb = InlineKeyboardBuilder()
    for code, label in THEMES.items():
        kb.button(text=label, callback_data=f"settheme:{code}")
    kb.adjust(3)
    await call.message.answer("Выбери тему оформления:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("settheme:"))
async def cb_settheme(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    db.set_theme(call.from_user.id, code)
    await call.message.answer(f"Тема сохранена: {THEMES.get(code, code)}")
    await call.answer("Готово")

@dp.callback_query(F.data == "quiz")
async def cb_quiz(call: CallbackQuery):
    await start_quiz(call.message, call.from_user.id)
    await call.answer()

@dp.callback_query(F.data.startswith("quizans:"))
async def cb_quizans(call: CallbackQuery):
    answer = call.data.split(":", 1)[1]
    correct_name = dp["quiz_correct"].get(call.from_user.id) if "quiz_correct" in dp else None
    # храним состояние в простом словаре
    correct_name = QUIZ_STATE.get(call.from_user.id)
    if correct_name is None:
        await call.answer("Викторина устарела, начни заново", show_alert=True)
        return
    if answer == correct_name:
        db.add_points(call.from_user.id, 1)
        db.inc_streak(call.from_user.id, True)
        user = db.get_user(call.from_user.id)
        streak = user["streak"] if user else 1
        unlocked = check_achievements(call.from_user.id, True, streak)
        text = f"✅ Верно! +1 очко. Серия: {streak}"
        if unlocked:
            text += "\n\n🏅 " + "\n🏅 ".join(unlocked)
        await call.message.answer(text)
        QUIZ_STATE.pop(call.from_user.id, None)
        await start_quiz(call.message, call.from_user.id)
    else:
        db.inc_streak(call.from_user.id, False)
        await call.message.answer(f"❌ Неверно. Правильно: <b>{correct_name}</b>")
        QUIZ_STATE.pop(call.from_user.id, None)
    await call.answer()

# ---- вспомогательные рендеры ----
async def send_profile(message: Message, uid=None):
    uid = uid or message.chat.id
    u = db.get_user(uid)
    if not u:
        db.create_user(uid, None, "Гость")
        u = db.get_user(uid)
    ach = db.get_achievements(uid)
    text = (
        f"📊 <b>Профиль</b>\n\n"
        f"👤 {u['first_name'] or 'Гость'}"
        + (f" (@{u['username']})" if u['username'] else "") + "\n"
        f"⭐ Очки: <b>{u['points']}</b>\n"
        f"🔥 Текущая серия: <b>{u['streak']}</b>\n"
        f"🏆 Рекорд серии: <b>{u['best_streak']}</b>\n"
        f"🏅 Достижений: <b>{len(ach)}</b>\n"
        f"🎨 Тема: {THEMES.get(u['theme'], u['theme'])}\n"
    )
    if ach:
        text += "\n" + "\n".join(f"• {a}" for a in ach[:10])
    await message.answer(text, reply_markup=main_menu())

async def send_top(message: Message):
    rows = db.top_users(10)
    if not rows:
        await message.answer("Пока пусто 🏆")
        return
    lines = ["🏆 <b>Топ игроков</b>\n"]
    for i, r in enumerate(rows, 1):
        name = r["first_name"] or (r["username"] or "Гость")
        lines.append(f"{i}. {name} — {r['points']} очк. (серия {r['best_streak']})")
    await message.answer("\n".join(lines))

async def send_fav(message: Message, uid=None):
    uid = uid or message.chat.id
    favs = db.get_favorites(uid)
    if not favs:
        await message.answer("⭐ Избранное пусто. Добавить: <code>/fav Иванович</code>")
        return
    lines = ["⭐ <b>Избранное</b>\n"]
    for f in favs:
        lines.append(f"• {f}")
    await message.answer("\n".join(lines))

async def send_history(message: Message, uid=None):
    uid = uid or message.chat.id
    rows = db.get_history(uid, 10)
    if not rows:
        await message.answer("📜 История пуста")
        return
    lines = ["📜 <b>Последние запросы</b>\n"]
    for r in rows:
        lines.append(f"• {r['otchestvo']} → {r['father']}")
    await message.answer("\n".join(lines))

QUIZ_STATE = {}

async def start_quiz(message: Message, uid=None):
    uid = uid or message.chat.id
    m, (f, name) = random.choice(list(OTCHESTVA.items()))
    otch = capitalize_otch(random.choice([m, f]))
    QUIZ_STATE[uid] = name
    await message.answer(
        f"🎯 <b>Викторина</b>\n\nКак зовут отца, если отчество: <b>{otch}</b>?",
        reply_markup=quiz_kb(name),
    )

# ===================== ОСНОВНОЙ ТЕКСТ =====================
@dp.message(Command("fav"))
async def cmd_fav_add(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) == 1:
        await send_fav(message)
        return
    otch = parts[1].strip()
    db.add_favorite(message.from_user.id, capitalize_otch(otch))
    await message.answer(f"⭐ Добавлено в избранное: <b>{capitalize_otch(otch)}</b>")

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message):
    uid = message.from_user.id
    if is_flood(uid):
        await message.answer("⏳ Слишком быстро, подожди пару секунд")
        return
    text = message.text.strip()

    # Обратное: "Иван м" или "Иван ж"
    parts = text.split()
    if len(parts) == 2 and parts[1].lower() in ("м", "ж", "m", "f"):
        female = parts[1].lower() in ("ж", "f")
        otch = find_otchestvo_by_name(parts[0], female)
        if otch:
            await message.answer(f"👨 Имя: <b>{parts[0]}</b> → отчество: <b>{otch}</b>")
            return
        await message.answer("Не знаю такого имени 🤔")
        return

    res = find_father(text)
    if not res:
        await message.answer(
            "🤔 Не знаю такого отчества.\n"
            "Попробуй: <b>Иванович</b> / <b>Ивановна</b>, или /random"
        )
        return

    name, otch, female = res
    db.add_history(uid, otch, name)
    unlocked = check_achievements(uid, True, 1)

    origin = NAME_ORIGIN.get(name, "")
    saint = SAINTS.get(name, "")
    celebs = CELEBRITIES.get(name, [])
    char = CHARACTER.get(name, "")
    udar = udarenie(otch.lower())
    tr = translit(otch)
    skl = skloneniya(otch, female)

    text_out = (
        f"🎯 <b>{otch}</b>\n\n"
        f"👨 Твоего отца зовут: <b>{name}</b>\n"
        f"🔤 Ударение: {udar}\n"
        f"🌍 Транслит: {tr}\n"
        f"📚 Склонения: {', '.join(skl)}\n"
    )
    if origin:
        text_out += f"📖 Происхождение имени: {origin}\n"
    if char:
        text_out += f"🧠 Характер: {char}\n"
    if saint:
        text_out += f"⛪ Святой покровитель: {saint}\n"
    if celebs:
        text_out += f"🌟 Знаменитости: {', '.join(celebs[:3])}\n"
    if unlocked:
        text_out += "\n🏅 " + "\n🏅 ".join(unlocked)

    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ В избранное", callback_data=f"favadd:{otch}")
    kb.button(text="🔮 Предсказание", callback_data="predict")
    kb.button(text="🥂 Тост", callback_data="toast")
    kb.button(text="🎯 Викторина", callback_data="quiz")
    kb.adjust(1, 3)

    await message.answer(text_out, reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("favadd:"))
async def cb_favadd(call: CallbackQuery):
    otch = call.data.split(":", 1)[1]
    db.add_favorite(call.from_user.id, otch)
    await call.answer("⭐ Добавлено", show_alert=False)

@dp.message(~F.text)
async def handle_non_text(message: Message):
    await message.answer("Пришли, пожалуйста, текст с отчеством 🙂")

# ===================== INLINE-РЕЖИМ =====================
@dp.inline_query()
async def inline_handler(query: InlineQuery):
    q = query.query.strip()
    results = []
    if q:
        res = find_father(q)
        if res:
            name, otch, female = res
            results.append(InlineQueryResultArticle(
                id="1",
                title=f"{otch} → {name}",
                description="Определить имя отца",
                input_message_content=InputTextMessageContent(
                    message_text=f"<b>{otch}</b> → отец <b>{name}</b>",
                    parse_mode=ParseMode.HTML,
                ),
            ))
    if not results:
        m, (f, name) = random.choice(list(OTCHESTVA.items()))
        results.append(InlineQueryResultArticle(
            id="2",
            title="Пример: как это работает",
            description=f"{m.capitalize()} → {name}",
            input_message_content=InputTextMessageContent(
                message_text=f"Например: <b>{m.capitalize()}</b> → отец <b>{name}</b>",
                parse_mode=ParseMode.HTML,
            ),
        ))
    await query.answer(results, cache_time=5, is_personal=True)

# ===================== АДМИНКА =====================
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    users, queries, top = db.global_stats()
    lines = [
        "🛠 <b>Админ-панель</b>\n",
        f"👥 Пользователей: <b>{users}</b>",
        f"🔎 Запросов: <b>{queries}</b>\n",
        "<b>Топ отчеств:</b>",
    ]
    for r in top:
        lines.append(f"• {r['otchestvo']} — {r['c']}")
    lines.append("\nКоманды:")
    lines.append("/broadcast текст — рассылка")
    lines.append("/ban — заглушка")
    await message.answer("\n".join(lines))

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /broadcast текст")
        return
    text = parts[1]
    sent, failed = 0, 0
    for uid in db.all_user_ids():
        try:
            await message.bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"✅ Отправлено: {sent}, ошибок: {failed}")

# ===================== ЗАПУСК =====================
async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Старт"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="profile", description="Профиль"),
        BotCommand(command="quiz", description="Викторина"),
        BotCommand(command="top", description="Топ игроков"),
        BotCommand(command="fav", description="Избранное"),
        BotCommand(command="history", description="История"),
        BotCommand(command="random", description="Случайное отчество"),
        BotCommand(command="fact", description="Факт"),
    ])

async def main():
    db.init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await set_commands(bot)
    log.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановлено")
