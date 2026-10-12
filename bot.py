
import asyncio
import logging
import os
import random
import time
from collections import defaultdict
from datetime import date, datetime
from io import BytesIO

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineQuery, InlineQueryResultArticle,
    InputTextMessageContent, BotCommand,
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
    BufferedInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
import cards
from data import (
    OTCHESTVA, RAZGOVORNYE, TRANSLIT, UDARENIYA, NAME_ORIGIN,
    CELEBRITIES, SAINTS, FACTS, CHARACTER, PREDICTIONS, TOASTS,
    THEMES, level_for,
)

# ===================== КОНФИГ =====================
BOT_TOKEN = "8910348962:AAHnP_GYZasuMY_HcmRwbjj2NfmQdpIf_S0"
ADMIN_IDS = {1012040843}
ANTIFLOOD_LIMIT = 6
ANTIFLOOD_WINDOW = 5.0
REF_BONUS = 5
REF_LEVELS = {5: 10, 10: 25, 25: 75}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("bot")

dp = Dispatcher()
_user_hits = defaultdict(list)
QUIZ_STATE: dict[int, dict] = {}
DUEL_WAIT: dict[int, list] = {}    # duel_id -> очередь ответов
DAILY_SEED_CACHE: dict[str, str] = {}

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
        return [otch, otch[:-1] + "у", otch[:-1] + "е",
                otch, otch[:-1] + "ой", otch[:-1] + "е"]
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

def check_achievements(uid: int, streak: int, score: int = 0):
    unlocked = []
    if db.grant_achievement(uid, "first_step"):
        unlocked.append("🐣 Первый шаг")
    if streak >= 10 and db.grant_achievement(uid, "streak_10"):
        unlocked.append("🔥 Серия 10")
    if streak >= 25 and db.grant_achievement(uid, "streak_25"):
        unlocked.append("⚡ Серия 25")
    if score >= 8 and db.grant_achievement(uid, "quiz_master"):
        unlocked.append("🎓 Мастер викторины")
    u = db.get_user(uid)
    if u and u["points"] >= 100 and db.grant_achievement(uid, "hundred"):
        unlocked.append("💯 Сотка очков")
    if u and (u["referrals"] or 0) >= 5 and db.grant_achievement(uid, "ref_5"):
        unlocked.append("🤝 Пригласил 5 друзей")
    return unlocked

def today_otchestvo() -> tuple[str, str]:
    """Стабильно одно и то же отчество в течение дня (seed = дата)."""
    key = date.today().isoformat()
    if key in DAILY_SEED_CACHE:
        otch = DAILY_SEED_CACHE[key]
    else:
        rnd = random.Random(key)
        m, (f, _) = rnd.choice(list(OTCHESTVA.items()))
        otch = capitalize_otch(rnd.choice([m, f]))
        DAILY_SEED_CACHE[key] = otch
    res = find_father(otch)
    return otch, (res[0] if res else "")

# ===================== КЛАВИАТУРЫ =====================
MENU_TEXTS = {
    "📊 Профиль", "🏆 Топ", "🎯 Викторина", "📅 Дейли",
    "⭐ Избранное", "📜 История", "💡 Факт", "🔮 Предсказание",
    "🎴 Карточка", "🛂 Паспорт", "ℹ️ Помощь",
}

def bottom_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Профиль"), KeyboardButton(text="🏆 Топ")],
            [KeyboardButton(text="🎯 Викторина"), KeyboardButton(text="📅 Дейли")],
            [KeyboardButton(text="⭐ Избранное"), KeyboardButton(text="📜 История")],
            [KeyboardButton(text="💡 Факт"), KeyboardButton(text="🔮 Предсказание")],
            [KeyboardButton(text="🎴 Карточка"), KeyboardButton(text="🛂 Паспорт")],
            [KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши отчество (например, Иванович)",
    )

def inline_main() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 Викторина", callback_data="quiz")
    kb.button(text="📅 Дейли", callback_data="daily")
    kb.button(text="⚔️ Дуэль", callback_data="duel")
    kb.button(text="📊 Профиль", callback_data="profile")
    kb.button(text="🏆 Топ", callback_data="top")
    kb.button(text="🤝 Рефереры", callback_data="reftop")
    kb.button(text="⭐ Избранное", callback_data="fav")
    kb.button(text="🎨 Тема", callback_data="theme")
    kb.button(text="🎭 Стиль ответа", callback_data="style")
    kb.button(text="⚙️ Квесты", callback_data="quests")
    kb.button(text="💎 Premium", callback_data="premium")
    kb.adjust(2, 2, 2, 2, 2, 1)
    return kb.as_markup()

def quiz_kb(options: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for opt in options:
        kb.button(text=opt, callback_data=f"quizans:{opt}")
    kb.button(text="⏭ Пропустить", callback_data="quizskip")
    kb.button(text="🛑 Закончить", callback_data="quizstop")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()

# ===================== /start =====================
@dp.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command):
    arg = command.args or ""

    # --- Дуэль ---
    if arg.startswith("duel_"):
        try:
            challenger_id = int(arg.split("_", 1)[1])
        except Exception:
            challenger_id = None
        if challenger_id and challenger_id != message.from_user.id:
            db.create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
            db.update_user_profile(message.from_user.id, message.from_user.username, message.from_user.first_name)
            duel_id = db.duel_create(challenger_id, message.from_user.id)
            DUEL_WAIT[duel_id] = []
            try:
                await message.bot.send_message(
                    challenger_id,
                    f"⚔️ Тебя вызвал на дуэль <b>{message.from_user.first_name}</b>!\n"
                    f"Начинаем через 5 секунд...",
                )
            except Exception:
                pass
            await message.answer(
                "⚔️ <b>Дуэль принята!</b>\n"
                "Сейчас будет 5 вопросов. Отвечаете оба — кто быстрее и точнее."
            )
            await _duel_run(message.bot, duel_id)
            return
        await cmd_start(message)
        return

    # --- Реферальная ссылка ---
    referrer_id = None
    if arg.isdigit():
        candidate = int(arg)
        if candidate != message.from_user.id:
            referrer_id = candidate

    db.create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    db.update_user_profile(message.from_user.id, message.from_user.username, message.from_user.first_name)

    if referrer_id:
        ok = db.set_referred_by(message.from_user.id, referrer_id)
        if ok:
            db.add_referral(referrer_id)
            db.add_points(referrer_id, REF_BONUS)
            u = db.get_user(referrer_id)
            refs = (u["referrals"] if u and "referrals" in u.keys() else 0) or 0
            bonus = REF_LEVELS.get(refs)
            extra = f"\n🎁 Бонус за {refs} друзей: +{bonus} очков!" if bonus else ""
            if bonus:
                db.add_points(referrer_id, bonus)
            try:
                await message.bot.send_message(
                    referrer_id,
                    f"🎁 По твоей ссылке пришёл друг! +{REF_BONUS} очков{extra}",
                )
            except Exception as e:
                log.warning("referrer notify failed: %s", e)

    await cmd_start(message)

@dp.message(CommandStart())
async def cmd_start(message: Message):
    db.create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    db.update_user_profile(message.from_user.id, message.from_user.username, message.from_user.first_name)
    me = await message.bot.me()
    ref_link = f"https://t.me/{me.username}?start={message.from_user.id}"
    otch, father = today_otchestvo()
    text = (
        f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        "Я умею по <b>отчеству</b> определять имя твоего отца.\n"
        "А ещё: викторина, дуэли, дейли, карточки, паспорт, рейтинг.\n\n"
        f"🌟 <b>Отчество дня:</b> {otch} → {father}\n\n"
        "Напиши любое отчество: <code>Иванович</code> или <code>Петровна</code>.\n\n"
        f"🔗 Твоя реф-ссылка:\n<code>{ref_link}</code>\n"
        f"За друга — <b>+{REF_BONUS} очков</b> 🎁"
    )
    await message.answer(text, reply_markup=bottom_kb())
    await message.answer("Меню:", reply_markup=inline_main())

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Что я умею</b>\n\n"
        "• Определяю имя отца по отчеству\n"
        "• Обратно: имя + м/ж → отчество\n"
        "• Склонения, транслит, ударение\n"
        "• Викторина, дуэли, дейли, квесты\n"
        "• Профиль, уровни, достижения, топ\n"
        "• Карточка и «паспорт» с картинкой\n"
        "• Темы и стиль ответов\n"
        "• Избранное, история, рефералка\n"
        "• Inline: <code>@бот Иванович</code>\n\n"
        "Команды: /start /help /profile /top /fav /history /quiz /daily /duel /ref /reftop /random /fact",
        reply_markup=bottom_kb(),
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

@dp.message(F.text == "📅 Дейли")
async def kb_daily(message: Message):
    await daily_quiz(message, message.from_user.id)

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

@dp.message(F.text == "🎴 Карточка")
async def kb_card(message: Message):
    await message.answer("Напиши отчество — пришлю карточку. Например: <b>Иванович</b>")

@dp.message(F.text == "🛂 Паспорт")
async def kb_passport(message: Message):
    await send_passport(message, message.from_user.id)

@dp.message(F.text == "ℹ️ Помощь")
async def kb_help(message: Message):
    await cmd_help(message)
# ===================== Callback-кнопки меню =====================
@dp.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery):
    await send_profile(call.message, call.from_user.id)
    await call.answer()

@dp.callback_query(F.data == "top")
async def cb_top(call: CallbackQuery):
    await send_top(call.message)
    await call.answer()

@dp.callback_query(F.data == "reftop")
async def cb_reftop(call: CallbackQuery):
    await send_reftop(call.message)
    await call.answer()

@dp.callback_query(F.data == "fav")
async def cb_fav(call: CallbackQuery):
    await send_fav(call.message, call.from_user.id)
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
    await call.message.answer("Выбери тему:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("settheme:"))
async def cb_settheme(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    db.set_theme(call.from_user.id, code)
    await call.message.answer(f"Тема: {THEMES.get(code, code)}")
    await call.answer("Ок")

@dp.callback_query(F.data == "style")
async def cb_style(call: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Короткий", callback_data="setstyle:short")
    kb.button(text="⚪ Обычный", callback_data="setstyle:normal")
    kb.button(text="🎭 Шутливый", callback_data="setstyle:fun")
    kb.adjust(3)
    await call.message.answer("Стиль ответа:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("setstyle:"))
async def cb_setstyle(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    db.set_answer_style(call.from_user.id, code)
    await call.message.answer(f"Стиль: {code}")
    await call.answer("Ок")

@dp.callback_query(F.data == "quests")
async def cb_quests(call: CallbackQuery):
    uid = call.from_user.id
    u = db.get_user(uid)
    if not u:
        db.create_user(uid, None, None)
        u = db.get_user(uid)
    refs = (u["referrals"] or 0) if u else 0
    best = (u["best_streak"] or 0) if u else 0
    pts = (u["points"] or 0) if u else 0

    quests = [
        ("ask5",  "📚 Задай 5 отчеств", min(pts // 5, 5), 5),
        ("quiz1", "🎯 Победи в викторине", min(best, 1), 1),
        ("ref1",  "🤝 Пригласи 1 друга", min(refs, 1), 1),
    ]
    lines = ["⚙️ <b>Квесты</b>\n"]
    for code, name, cur, need in quests:
        done = "✅" if cur >= need else f"{cur}/{need}"
        lines.append(f"• {name} — {done}")

    await call.message.answer("\n".join(lines))
    await call.answer()

@dp.callback_query(F.data == "premium")
async def cb_premium(call: CallbackQuery):
    u = db.get_user(call.from_user.id)
    is_prem = bool(u and "premium" in u.keys() and u["premium"])
    status = "✅ активен" if is_prem else "❌ не активен"
    await call.message.answer(
        f"💎 <b>Premium</b> — {status}\n\n"
        "Что даёт:\n"
        "• Расширенная база отчеств\n"
        "• Без лимитов викторин\n"
        "• Эксклюзивные темы\n"
        "• Приоритетная поддержка\n\n"
        "Оплата через Telegram Stars — в разработке."
    )
    await call.answer()

@dp.callback_query(F.data.startswith("favadd:"))
async def cb_favadd(call: CallbackQuery):
    otch = call.data.split(":", 1)[1]
    db.add_favorite(call.from_user.id, otch)
    await call.answer("⭐ Добавлено")

@dp.callback_query(F.data.startswith("card:"))
async def cb_card(call: CallbackQuery):
    otch = call.data.split(":", 1)[1]
    res = find_father(otch)
    if not res:
        await call.answer("Не нашёл", show_alert=True)
        return
    name, otch2, female = res
    img = cards.build_card(otch2, name)
    await call.message.answer_photo(
        BufferedInputFile(img.getvalue(), filename="card.png"),
        caption=f"🎴 <b>{otch2}</b> → <b>{name}</b>",
    )
    await call.answer()

# ===================== ВИКТОРИНА =====================
QUIZ_LEN = 10

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
    return text, correct, options

async def start_quiz(message: Message, uid: int | None = None, length=QUIZ_LEN, mode="quiz", mult=1):
    uid = uid or message.chat.id
    db.create_user(uid, None, None)
    text, correct, options = _new_question()
    sent = await message.answer(
        f"🎯 <b>Викторина</b> — вопрос 1/{length}\n\n{text}",
        reply_markup=quiz_kb(options),
    )
    QUIZ_STATE[sent.message_id] = {
        "uid": uid, "q_num": 1, "score": 0, "correct": correct,
        "started_at": time.time(), "answered": False,
        "length": length, "mode": mode, "mult": mult,
    }

async def _next_question(message: Message, state: dict):
    length = state.get("length", QUIZ_LEN)
    mult = state.get("mult", 1)
    if state["q_num"] >= length:
        score = state["score"]
        if mult > 1:
            score = score * mult
        db.add_points(state["uid"], score)
        user = db.get_user(state["uid"])
        streak = user["streak"] if user else 0
        unlocked = check_achievements(state["uid"], streak, state["score"])
        bonus = ""
        if state["score"] >= length * 0.8:
            bonus = "\n🏅 Отличный результат!"
        elif state["score"] >= length * 0.5:
            bonus = "\n👍 Неплохо!"
        else:
            bonus = "\n💪 Тренируйся!"
        if mult > 1:
            bonus += f"\n✨ Множитель x{mult} применён!"
        if unlocked:
            bonus += "\n🏅 " + "\n🏅 ".join(unlocked)
        await message.answer(
            f"🏁 <b>Итог</b>\n\nПравильных: <b>{state['score']}/{length}</b>\n"
            f"Начислено: <b>+{score}</b>{bonus}"
        )
        return

    text, correct, options = _new_question()
    q_num = state["q_num"] + 1
    state.update({"q_num": q_num, "correct": correct, "started_at": time.time(), "answered": False})
    sent = await message.answer(
        f"🎯 <b>Вопрос {q_num}/{length}</b>  ·  очки: {state['score']}\n\n{text}",
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
    score = st["score"] * st.get("mult", 1)
    db.add_points(st["uid"], score)
    await call.message.answer(
        f"🛑 Остановлено. Правильных: {st['score']}/{st['q_num']-1}. +{score}"
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
    speed_bonus = 2 if elapsed < 3 else (1 if elapsed < 7 else 0)

    if answer == st["correct"]:
        st["score"] += 1 + speed_bonus
        db.inc_streak(st["uid"], True)
        u = db.get_user(st["uid"])
        streak = u["streak"] if u else 1
        extra = []
        if speed_bonus:
            extra.append(f"⚡ +{speed_bonus}")
        if streak >= 5:
            extra.append(f"🔥 серия {streak}")
        txt = f"✅ Верно! +{1+speed_bonus} очк."
        if extra:
            txt += "\n" + "\n".join(extra)
        await call.message.answer(txt)
        await call.answer("Верно!")
    else:
        db.inc_streak(st["uid"], False)
        await call.message.answer(f"❌ Мимо. Правильно: <b>{st['correct']}</b>")
        await call.answer("Мимо")

    await _next_question(call.message, st)

# ===================== ДЕЙЛИ =====================
async def daily_quiz(message: Message, uid: int):
    today = date.today().isoformat()
    u = db.get_user(uid)
    if not u:
        db.create_user(uid, None, None)
        u = db.get_user(uid)
    if u and u["daily_done"] == today:
        await message.answer("📅 Дейли уже пройден. Возвращайся завтра!")
        return

    prev = u["last_daily"] if u else None
    d_streak = (u["daily_streak"] if u and u["daily_streak"] else 0)
    if prev:
        try:
            d1 = datetime.fromisoformat(prev).date()
            diff = (date.today() - d1).days
            if diff == 1:
                d_streak += 1
            elif diff > 1:
                d_streak = 1
        except Exception:
            d_streak = 1
    else:
        d_streak = 1

    db.set_daily(uid, today, d_streak)
    await message.answer(
        f"📅 <b>Дейли-викторина</b>\n"
        f"🔥 Стрик дней: <b>{d_streak}</b>\n"
        "Множитель очков: <b>x2</b>!"
    )
    await start_quiz(message, uid, length=3, mode="daily", mult=2)

@dp.callback_query(F.data == "daily")
async def cb_daily(call: CallbackQuery):
    await daily_quiz(call.message, call.from_user.id)
    await call.answer()

# ===================== ДУЭЛЬ =====================
@dp.callback_query(F.data == "duel")
async def cb_duel(call: CallbackQuery):
    me = await call.bot.me()
    link = f"https://t.me/{me.username}?start=duel_{call.from_user.id}"
    await call.message.answer(
        "⚔️ <b>Дуэль</b>\n\n"
        "Отправь другу ссылку — он откроет, и вы сразитесь за 5 вопросов:\n\n"
        f"<code>{link}</code>"
    )
    await call.answer()

async def _duel_run(bot: Bot, duel_id: int):
    duel = db.duel_get(duel_id)
    if not duel:
        return
    challenger = duel["challenger"]
    opponent = duel["opponent"]

    questions = [_new_question() for _ in range(5)]
    c_score = 0
    o_score = 0

    for idx, (text, correct, options) in enumerate(questions, 1):
        # шлём обоим
        kb = InlineKeyboardBuilder()
        for opt in options:
            kb.button(text=opt, callback_data=f"duelans:{duel_id}:{idx}:{opt}")
        kb.adjust(2)
        msg = (
            f"⚔️ <b>Дуэль — вопрос {idx}/5</b>\n\n{text}"
        )
        try:
            await bot.send_message(challenger, msg, reply_markup=kb.as_markup())
        except Exception:
            pass
        try:
            await bot.send_message(opponent, msg, reply_markup=kb.as_markup())
        except Exception:
            pass

        # ждём 15 сек или пока оба ответят
        deadline = time.time() + 15
        answers = {}
        DUEL_WAIT[duel_id] = []
        while time.time() < deadline and len(answers) < 2:
            await asyncio.sleep(0.5)
            while DUEL_WAIT[duel_id]:
                uid, ans = DUEL_WAIT[duel_id].pop(0)
                if uid in (challenger, opponent) and uid not in answers:
                    answers[uid] = ans

        for uid, ans in answers.items():
            if ans == correct:
                if uid == challenger:
                    c_score += 1
                else:
                    o_score += 1
        db.duel_update(duel_id, c_score, o_score, "running")

    db.duel_update(duel_id, c_score, o_score, "finished")

    # результат обоим
    if c_score > o_score:
        winner = challenger
        result_text = "🏆 Победил вызывающий!"
    elif o_score > c_score:
        winner = opponent
        result_text = "🏆 Победил соперник!"
    else:
        winner = None
        result_text = "🤝 Ничья!"

    summary = (
        f"🏁 <b>Дуэль завершена</b>\n\n"
        f"Вызывающий: <b>{c_score}</b>\n"
        f"Соперник: <b>{o_score}</b>\n\n"
        f"{result_text}"
    )

    for uid in (challenger, opponent):
        try:
            await bot.send_message(uid, summary)
        except Exception:
            pass

    if winner:
        db.add_points(winner, 5)

@dp.callback_query(F.data.startswith("duelans:"))
async def cb_duelans(call: CallbackQuery):
    _, duel_id, idx, ans = call.data.split(":", 3)
    duel_id = int(duel_id)
    uid = call.from_user.id
    DUEL_WAIT.setdefault(duel_id, []).append((uid, ans))
    await call.answer("Принято")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

# ===================== РЕНДЕРЫ =====================
async def send_profile(message: Message, uid=None):
    uid = uid or message.chat.id
    u = db.get_user(uid)
    if not u:
        db.create_user(uid, None, "Гость")
        u = db.get_user(uid)
    ach = db.get_achievements(uid)
    points = u["points"] or 0
    level, lvl_idx, nxt = level_for(points)
    progress = ""
    if nxt:
        need, _ = nxt
        progress = f"\n⬆️ До следующего: {need - points} очк."

    refs = (u["referrals"] or 0) if "referrals" in u.keys() else 0
    prem = "💎 да" if ("premium" in u.keys() and u["premium"]) else "—"
    daily_streak = (u["daily_streak"] or 0) if "daily_streak" in u.keys() else 0
    style = (u["answer_style"] or "normal") if "answer_style" in u.keys() else "normal"

    text = (
        f"📊 <b>Профиль</b>\n\n"
        f"👤 {u['first_name'] or 'Гость'}"
        + (f" (@{u['username']})" if u['username'] else "") + "\n"
        f"🎖 Уровень: <b>{level}</b>\n"
        f"⭐ Очки: <b>{points}</b>\n"
        f"🔥 Серия: <b>{u['streak'] or 0}</b> · 🏆 Рекорд: <b>{u['best_streak'] or 0}</b>\n"
        f"📅 Дейли-стрик: <b>{daily_streak}</b> дн.\n"
        f"👥 Приглашено: <b>{refs}</b>\n"
        f"🏅 Достижений: <b>{len(ach)}</b>\n"
        f"🎨 Тема: {THEMES.get(u['theme'], u['theme'])}\n"
        f"🎭 Стиль: {style}\n"
        f"💎 Premium: {prem}{progress}"
    )
    if ach:
        text += "\n\n" + "\n".join(f"• {a}" for a in ach[:10])
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
        await message.answer("Пока никого 🤝")
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
        await message.answer("⭐ Пусто. Добавь: <code>/fav Иванович</code>")
        return
    await message.answer("⭐ <b>Избранное</b>\n\n" + "\n".join(f"• {f}" for f in favs))

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

async def send_passport(message: Message, uid: int):
    u = db.get_user(uid)
    if not u:
        db.create_user(uid, None, "Гость")
        u = db.get_user(uid)

    last_father = db.get_last_father(uid)
    if last_father:
        res = find_otchestvo_by_name(last_father, False)
        otch = res if res else "Иванович"
        father = last_father
    else:
        otch = "Иванович"
        father = "Иван"

    first = u["first_name"] or "Гражданин"
    points = u["points"] or 0
    level, _, _ = level_for(points)

    img = cards.build_passport(first, father, otch, level)
    await message.answer_photo(
        BufferedInputFile(img.getvalue(), filename="passport.png"),
        caption=f"🛂 Паспорт гражданина <b>{first}</b>\nУровень: {level}",
    )
    
# ===================== ОСНОВНОЙ ТЕКСТОВЫЙ ХЭНДЛЕР =====================
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
    await message.answer(f"⭐ Добавлено: <b>{capitalize_otch(otch)}</b>")

@dp.message(Command("history"))
async def cmd_history(message: Message):
    await send_history(message, message.from_user.id)

@dp.message(Command("quiz"))
async def cmd_quiz(message: Message):
    await start_quiz(message, message.from_user.id)

@dp.message(Command("daily"))
async def cmd_daily(message: Message):
    await daily_quiz(message, message.from_user.id)

@dp.message(Command("duel"))
async def cmd_duel(message: Message):
    me = await message.bot.me()
    link = f"https://t.me/{me.username}?start=duel_{message.from_user.id}"
    await message.answer(
        "⚔️ <b>Дуэль</b>\n\n"
        "Отправь другу ссылку:\n\n"
        f"<code>{link}</code>\n\n"
        "5 вопросов, кто точнее и быстрее."
    )

@dp.message(Command("fact"))
async def cmd_fact(message: Message):
    await message.answer("💡 " + random.choice(FACTS))

@dp.message(Command("random"))
async def cmd_random(message: Message):
    m, (f, name) = random.choice(list(OTCHESTVA.items()))
    await message.answer(f"🎲 <b>{random.choice([m, f]).capitalize()}</b> → отец <b>{name}</b>")

@dp.message(Command("ref"))
async def cmd_ref(message: Message):
    me = await message.bot.me()
    u = db.get_user(message.from_user.id)
    refs = (u["referrals"] or 0) if u and "referrals" in u.keys() else 0
    link = f"https://t.me/{me.username}?start={message.from_user.id}"
    next_bonus = ""
    for need, bonus in sorted(REF_LEVELS.items()):
        if refs < need:
            next_bonus = f"\nДо бонуса за {need} друзей: ещё {need - refs} 🤝"
            break
    await message.answer(
        "🔗 <b>Реферальная программа</b>\n\n"
        f"Ссылка:\n<code>{link}</code>\n\n"
        f"Приглашено: <b>{refs}</b>\n"
        f"За каждого — <b>+{REF_BONUS}</b> очков.{next_bonus}"
    )

@dp.message(Command("reftop"))
async def cmd_reftop(message: Message):
    await send_reftop(message)

@dp.message(F.text & ~F.text.startswith("/") & ~F.text.in_(MENU_TEXTS))
async def handle_text(message: Message):
    uid = message.from_user.id
    if is_flood(uid):
        await message.answer("⏳ Слишком быстро")
        return
    text = message.text.strip()

    # Обратное: "Иван м" / "Иван ж"
    parts = text.split()
    if len(parts) == 2 and parts[1].lower() in ("м", "ж", "m", "f"):
        female = parts[1].lower() in ("ж", "f")
        otch = find_otchestvo_by_name(parts[0], female)
        if otch:
            await message.answer(f"👨 <b>{parts[0]}</b> → <b>{otch}</b>")
            return
        await message.answer("Не знаю такого имени 🤔")
        return

    res = find_father(text)
    if not res:
        await message.answer(
            "🤔 Не знаю такого отчества.\n"
            "Попробуй <b>Иванович</b> или /random"
        )
        return

    name, otch, female = res
    db.add_history(uid, otch, name)
    u = db.get_user(uid)
    style = (u["answer_style"] if u and "answer_style" in u.keys() else "normal") or "normal"

    unlocked = check_achievements(uid, (u["streak"] if u else 0) or 0)

    if style == "short":
        text_out = f"🎯 <b>{otch}</b> → отец <b>{name}</b>"
    elif style == "fun":
        pred = random.choice(PREDICTIONS)
        text_out = (
            f"🎭 <b>{otch}</b> — мощное отчество!\n"
            f"👨 Отец: <b>{name}</b>\n"
            f"🔮 {pred}"
        )
    else:
        origin = NAME_ORIGIN.get(name, "")
        saint = SAINTS.get(name, "")
        celebs = CELEBRITIES.get(name, [])
        char = CHARACTER.get(name, "")
        udar = udarenie(otch.lower())
        tr = translit(otch)
        skl = skloneniya(otch, female)
        text_out = (
            f"🎯 <b>{otch}</b>\n\n"
            f"👨 Отец: <b>{name}</b>\n"
            f"🔤 Ударение: {udar}\n"
            f"🌍 Транслит: {tr}\n"
            f"📚 Склонения: {', '.join(skl)}\n"
        )
        if origin:
            text_out += f"📖 Происхождение: {origin}\n"
        if char:
            text_out += f"🧠 Характер: {char}\n"
        if saint:
            text_out += f"⛪ Святой: {saint}\n"
        if celebs:
            text_out += f"🌟 Знаменитости: {', '.join(celebs[:3])}\n"
    if unlocked:
        text_out += "\n🏅 " + "\n🏅 ".join(unlocked)

    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ В избранное", callback_data=f"favadd:{otch}")
    kb.button(text="🎴 Карточка", callback_data=f"card:{otch}")
    kb.button(text="🔮 Предсказание", callback_data="predict")
    kb.button(text="🎯 Викторина", callback_data="quiz")
    kb.adjust(2, 2)

    await message.answer(text_out, reply_markup=kb.as_markup())

@dp.message(~F.text)
async def handle_non_text(message: Message):
    await message.answer("Пришли текстом отчество 🙂")

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
            title="Пример",
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
        "🛠 <b>Админ</b>\n",
        f"👥 Юзеров: <b>{users}</b>",
        f"🔎 Запросов: <b>{queries}</b>\n",
        "<b>Топ отчеств:</b>",
    ]
    for r in top:
        lines.append(f"• {r['otchestvo']} — {r['c']}")
    lines.append(
        "\n/broadcast текст\n"
        "/backup — бэкап БД\n"
        "/premium ID 0/1"
    )
    await message.answer("\n".join(lines))

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /broadcast текст")
        return
    sent, failed = 0, 0
    for uid in db.all_user_ids():
        try:
            await message.bot.send_message(uid, parts[1])
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"✅ {sent}, ошибок: {failed}")

@dp.message(Command("backup"))
async def cmd_backup(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    db.backup_db()
    await message.answer("💾 Бэкап создан в папке backups/")

@dp.message(Command("premium"))
async def cmd_premium(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("/premium <user_id> <0|1>")
        return
    try:
        uid, val = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("ID и значение должны быть числами")
        return
    db.set_premium(uid, val)
    await message.answer(f"✅ Premium для {uid}: {val}")

# ===================== ЗАПУСК =====================
async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Старт"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="profile", description="Профиль"),
        BotCommand(command="quiz", description="Викторина"),
        BotCommand(command="daily", description="Дейли-задание"),
        BotCommand(command="duel", description="Дуэль"),
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
    db.backup_db()
    cards.load_fonts()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await set_commands(bot)
    log.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановлено")
