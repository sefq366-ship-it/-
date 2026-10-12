
import asyncio
import logging
import random
import time
from collections import defaultdict

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineQuery, InlineQueryResultArticle,
    InputTextMessageContent, BotCommand,
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from data import (
    OTCHESTVA, RAZGOVORNYE, TRANSLIT, UDARENIYA, NAME_ORIGIN,
    CELEBRITIES, SAINTS, FACTS, CHARACTER, PREDICTIONS, TOASTS,
    THEMES,
)

# ===================== КОНФИГ =====================
BOT_TOKEN = "8910348962:AAHnP_GYZasuMY_HcmRwbjj2NfmQdpIf_S0"
ADMIN_IDS = {1012040843}          # <-- впишите свой telegram id
ANTIFLOOD_LIMIT = 6
ANTIFLOOD_WINDOW = 5.0

REF_BONUS = 5                    # очков пригласившему за друга

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bot")

dp = Dispatcher()
_user_hits = defaultdict(list)
QUIZ_STATE: dict[int, dict] = {}

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
    if female:
        return [
            otch, otch[:-1] + "у", otch[:-1] + "е",
            otch, otch[:-1] + "ой", otch[:-1] + "е",
        ]
    return [otch, otch + "а", otch + "у", otch + "а", otch + "ем", "о " + otch + "е"]

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
MENU_TEXTS = {
    "📊 Профиль", "🏆 Топ", "🎯 Викторина", "⭐ Избранное",
    "📜 История", "💡 Факт", "🔮 Предсказание", "ℹ️ Помощь",
}

def bottom_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Профиль"), KeyboardButton(text="🏆 Топ")],
            [KeyboardButton(text="🎯 Викторина"), KeyboardButton(text="⭐ Избранное")],
            [KeyboardButton(text="📜 История"), KeyboardButton(text="💡 Факт")],
            [KeyboardButton(text="🔮 Предсказание"), KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши отчество (например, Иванович)",
    )

# ===================== /start с рефералкой =====================
@dp.message(CommandStart(deep_link=True))
async def cmd_start_ref(message: Message, command):
    referrer_id = None
    if command.args and command.args.isdigit():
        candidate = int(command.args)
        if candidate != message.from_user.id:
            referrer_id = candidate

    # 1. Создаём юзера
    db.create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    db.update_user_profile(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    # 2. Если пришёл по реф-ссылке и ещё не привязан — привязываем
    if referrer_id:
        ok = db.set_referred_by(message.from_user.id, referrer_id)
        if ok:
            db.add_referral(referrer_id)
            db.add_points(referrer_id, REF_BONUS)
            try:
                await message.bot.send_message(
                    referrer_id,
                    f"🎁 По твоей ссылке пришёл друг! +{REF_BONUS} очков",
                )
            except Exception as e:
                log.warning("Не удалось уведомить реферера %s: %s", referrer_id, e)

    await cmd_start(message)

@dp.message(CommandStart())
async def cmd_start(message: Message):
    db.create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    db.update_user_profile(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    me = await message.bot.me()
    ref_link = f"https://t.me/{me.username}?start={message.from_user.id}"
    text = (
        f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        "Я умею по <b>отчеству</b> определять имя твоего отца.\n"
        "А ещё: викторина, профиль, топ, избранное, история, факты.\n\n"
        "Просто напиши отчество: <code>Иванович</code> или <code>Петровна</code>.\n\n"
        "🔗 <b>Твоя реферальная ссылка</b>\n"
        f"<code>{ref_link}</code>\n"
        f"За каждого друга — <b>+{REF_BONUS} очков</b> 🎁"
    )
    await message.answer(text, reply_markup=bottom_kb())

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Что я умею</b>\n\n"
        "• Определяю имя отца по отчеству\n"
        "• Обратно: имя + м/ж → отчество\n"
        "• Склонения, транслит, ударение\n"
        "• Викторина, очки, достижения, топ\n"
        "• Профиль, история, избранное\n"
        "• Факты, происхождение имён, святые, знаменитости\n"
        "• Предсказания и тосты\n"
        "• Inline-режим: <code>@бот Иванович</code> в любом чате\n\n"
        "Команды: /start /help /profile /top /fav /history /quiz /random /fact /ref",
        reply_markup=bottom_kb(),
    )

@dp.message(Command("ref"))
async def cmd_ref(message: Message):
    me = await message.bot.me()
    u = db.get_user(message.from_user.id)
    refs = u["referrals"] if u and "referrals" in u.keys() else 0
    ref_link = f"https://t.me/{me.username}?start={message.from_user.id}"
    await message.answer(
        "🔗 <b>Реферальная программа</b>\n\n"
        f"Твоя ссылка:\n<code>{ref_link}</code>\n\n"
        f"Приглашено друзей: <b>{refs}</b>\n"
        f"За каждого — <b>+{REF_BONUS} очков</b> 🎁\n\n"
        "Отправь ссылку другу — очки придут автоматически, "
        "когда он запустит бота."
    )

# ===================== Reply-кнопки снизу =====================
@dp.message(F.text == "📊 Профиль")
async def kb_profile(message: Message):
    await send_profile(message, message.from_user.id)

@dp.message(F.text == "🏆 Топ")
async def kb_top(message: Message):
    await send_top(message)

@dp.message(F.text == "🎯 Викторина")
async def kb_quiz(message: Message):
    await start_quiz(message, message.from_user.id)

@dp.message(F.text == "⭐ Избранное")
async def kb_fav(message: Message):
    await send_fav(message, message.from_user.id)

@dp.message(F.text == "📜 История")
async def kb_history(message: Message):
    await send_history(message, message.from_user.id)

@dp.message(F.text == "💡 Факт")
async def kb_fact(message: Message):
    await message.answer("💡 " + random.choice(FACTS))

@dp.message(F.text == "🔮 Предсказание")
async def kb_predict(message: Message):
    await message.answer("🔮 " + random.choice(PREDICTIONS))

@dp.message(F.text == "ℹ️ Помощь")
async def kb_help(message: Message):
    await cmd_help(message)

# ===================== Команды =====================
@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    await send_profile(message, message.from_user.id)

@dp.message(Command("top"))
async def cmd_top(message: Message):
    await send_top(message)

@dp.message(Command("fav"))
async def cmd_fav(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) == 1:
        await send_fav(message, message.from_user.id)
        return
    otch = parts[1].strip()
    db.add_favorite(message.from_user.id, capitalize_otch(otch))
    await message.answer(f"⭐ Добавлено в избранное: <b>{capitalize_otch(otch)}</b>")

@dp.message(Command("history"))
async def cmd_history(message: Message):
    await send_history(message, message.from_user.id)

@dp.message(Command("quiz"))
async def cmd_quiz(message: Message):
    await start_quiz(message, message.from_user.id)

@dp.message(Command("fact"))
async def cmd_fact(message: Message):
    await message.answer("💡 " + random.choice(FACTS))

@dp.message(Command("random"))
async def cmd_random(message: Message):
    m, (f, name) = random.choice(list(OTCHESTVA.items()))
    await message.answer(f"🎲 <b>{random.choice([m, f]).capitalize()}</b> → отец <b>{name}</b>")

# ===================== Callback-кнопки =====================
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

@dp.callback_query(F.data.startswith("favadd:"))
async def cb_favadd(call: CallbackQuery):
    otch = call.data.split(":", 1)[1]
    db.add_favorite(call.from_user.id, otch)
    await call.answer("⭐ Добавлено", show_alert=False)

@dp.callback_query(F.data == "reftop")
async def cb_reftop(call: CallbackQuery):
    await send_reftop(call.message)
    await call.answer()

# ===================== ВИКТОРИНА =====================
QUIZ_LEN = 10
QUIZ_TIME = 15

def quiz_kb(options: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for opt in options:
        kb.button(text=opt, callback_data=f"quizans:{opt}")
    kb.button(text="⏭ Пропустить", callback_data="quizskip")
    kb.button(text="🛑 Закончить", callback_data="quizstop")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()

def _new_question():
    m, (f, name) = random.choice(list(OTCHESTVA.items()))
    otch = capitalize_otch(random.choice([m, f]))
    reverse = random.random() < 0.2

    if reverse:
        correct = otch
        pool = set()
        while len(pool) < 3:
            mm, (ff, _) = random.choice(list(OTCHESTVA.items()))
            cand = capitalize_otch(random.choice([mm, ff]))
            if cand != correct:
                pool.add(cand)
        options = list(pool | {correct})
        random.shuffle(options)
        text = f"Какое отчество у человека, если отца зовут <b>{name}</b>?"
    else:
        correct = name
        pool = set()
        while len(pool) < 3:
            _, (_, n) = random.choice(list(OTCHESTVA.items()))
            if n != correct:
                pool.add(n)
        options = list(pool | {correct})
        random.shuffle(options)
        text = f"Как зовут отца, если отчество: <b>{otch}</b>?"

    return text, correct, options, ("reverse" if reverse else "forward")

async def start_quiz(message: Message, uid: int | None = None):
    uid = uid or message.chat.id
    db.create_user(uid, None, None)

    text, correct, options, qtype = _new_question()
    sent = await message.answer(
        f"🎯 <b>Викторина</b> — вопрос 1/{QUIZ_LEN}\n\n{text}",
        reply_markup=quiz_kb(options),
    )
    QUIZ_STATE[sent.message_id] = {
        "uid": uid,
        "q_num": 1,
        "score": 0,
        "correct": correct,
        "qtype": qtype,
        "started_at": time.time(),
        "answered": False,
    }

async def _next_question(message: Message, state: dict):
    if state["q_num"] >= QUIZ_LEN:
        score = state["score"]
        db.add_points(state["uid"], score)
        bonus_text = ""
        if score >= 8:
            db.grant_achievement(state["uid"], "quiz_master")
            bonus_text = "\n🏅 Достижение: «Мастер викторины»"
        elif score >= 5:
            bonus_text = "\n👍 Неплохо!"
        else:
            bonus_text = "\n💪 Есть куда расти!"

        await message.answer(
            f"🏁 <b>Итог викторины</b>\n\n"
            f"Правильных: <b>{score}/{QUIZ_LEN}</b>\n"
            f"Начислено очков: <b>+{score}</b>{bonus_text}\n\n"
            f"Запустить снова — /quiz или кнопка «🎯 Викторина»."
        )
        return

    text, correct, options, qtype = _new_question()
    q_num = state["q_num"] + 1
    state.update({
        "q_num": q_num,
        "correct": correct,
        "qtype": qtype,
        "started_at": time.time(),
        "answered": False,
    })
    sent = await message.answer(
        f"🎯 <b>Вопрос {q_num}/{QUIZ_LEN}</b>  ·  очки: {state['score']}\n\n{text}",
        reply_markup=quiz_kb(options),
    )
    QUIZ_STATE[sent.message_id] = state

@dp.callback_query(F.data == "quiz")
async def cb_quiz(call: CallbackQuery):
    await start_quiz(call.message, call.from_user.id)
    await call.answer()

@dp.callback_query(F.data == "quizskip")
async def cb_quizskip(call: CallbackQuery):
    st = QUIZ_STATE.get(call.message.message_id)
    if not st or st.get("answered"):
        await call.answer("Уже отвечено")
        return
    st["answered"] = True
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    QUIZ_STATE.pop(call.message.message_id, None)
    db.inc_streak(st["uid"], False)
    await call.message.answer(f"⏭ Пропущено. Правильно: <b>{st['correct']}</b>")
    await call.answer("Пропуск")
    await _next_question(call.message, st)

@dp.callback_query(F.data == "quizstop")
async def cb_quizstop(call: CallbackQuery):
    st = QUIZ_STATE.get(call.message.message_id)
    if not st:
        await call.answer("Уже завершено")
        return
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    QUIZ_STATE.pop(call.message.message_id, None)
    db.add_points(st["uid"], st["score"])
    await call.message.answer(
        f"🛑 Остановлено. Правильных: {st['score']}/{st['q_num'] - 1}. "
        f"Начислено: +{st['score']}"
    )
    await call.answer("Остановлено")

@dp.callback_query(F.data.startswith("quizans:"))
async def cb_quizans(call: CallbackQuery):
    st = QUIZ_STATE.get(call.message.message_id)
    if not st:
        await call.answer("Сессия истекла, /quiz", show_alert=True)
        return
    if st.get("answered"):
        await call.answer("Уже отвечено")
        return

    st["answered"] = True
    answer = call.data.split(":", 1)[1]

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    QUIZ_STATE.pop(call.message.message_id, None)

    elapsed = time.time() - st["started_at"]
    speed_bonus = 0
    if elapsed < 3:
        speed_bonus = 2
    elif elapsed < 7:
        speed_bonus = 1

    if answer == st["correct"]:
        st["score"] += 1 + speed_bonus
        db.inc_streak(st["uid"], True)
        user = db.get_user(st["uid"])
        streak = user["streak"] if user else 1

        extra = []
        if speed_bonus:
            extra.append(f"⚡ бонус за скорость +{speed_bonus}")
        if streak >= 5:
            extra.append(f"🔥 серия {streak}")

        txt = f"✅ Верно! +{1 + speed_bonus} очк."
        if extra:
            txt += "\n" + "\n".join(extra)
        await call.message.answer(txt)
        await call.answer("Верно!")
    else:
        db.inc_streak(st["uid"], False)
        await call.message.answer(f"❌ Мимо. Правильно: <b>{st['correct']}</b>")
        await call.answer("Мимо")

    await _next_question(call.message, st)

# ===================== Рендеры =====================
async def send_profile(message: Message, uid=None):
    uid = uid or message.chat.id
    u = db.get_user(uid)
    if not u:
        db.create_user(uid, None, "Гость")
        u = db.get_user(uid)
    ach = db.get_achievements(uid)
    refs = u["referrals"] if "referrals" in u.keys() else 0
    text = (
        f"📊 <b>Профиль</b>\n\n"
        f"👤 {u['first_name'] or 'Гость'}"
        + (f" (@{u['username']})" if u['username'] else "") + "\n"
        f"⭐ Очки: <b>{u['points']}</b>\n"
        f"🔥 Текущая серия: <b>{u['streak']}</b>\n"
        f"🏆 Рекорд серии: <b>{u['best_streak']}</b>\n"
        f"👥 Приглашено друзей: <b>{refs}</b>\n"
        f"🏅 Достижений: <b>{len(ach)}</b>\n"
        f"🎨 Тема: {THEMES.get(u['theme'], u['theme'])}\n"
    )
    if ach:
        text += "\n" + "\n".join(f"• {a}" for a in ach[:10])
    await message.answer(text)

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

async def send_reftop(message: Message):
    rows = db.top_referrers(10)
    if not rows:
        await message.answer("Пока никого не приглашали 🤝")
        return
    lines = ["🤝 <b>Топ рефереров</b>\n"]
    for i, r in enumerate(rows, 1):
        name = r["first_name"] or (r["username"] or "Гость")
        lines.append(f"{i}. {name} — {r['referrals']} друзей")
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

# ===================== Основной текст =====================
@dp.message(F.text & ~F.text.startswith("/") & ~F.text.in_(MENU_TEXTS))
async def handle_text(message: Message):
    uid = message.from_user.id
    if is_flood(uid):
        await message.answer("⏳ Слишком быстро, подожди пару секунд")
        return
    text = message.text.strip()

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

@dp.message(~F.text)
async def handle_non_text(message: Message):
    await message.answer("Пришли, пожалуйста, текст с отчеством 🙂")

# ===================== Inline =====================
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

# ===================== Админка =====================
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
    lines.append("/reftop — топ рефереров")
    await message.answer("\n".join(lines))

@dp.message(Command("reftop"))
async def cmd_reftop(message: Message):
    await send_reftop(message)

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

# ===================== Запуск =====================
async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Старт"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="profile", description="Профиль"),
        BotCommand(command="quiz", description="Викторина"),
        BotCommand(command="top", description="Топ игроков"),
        BotCommand(command="ref", description="Реферальная ссылка"),
        BotCommand(command="reftop", description="Топ рефереров"),
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
