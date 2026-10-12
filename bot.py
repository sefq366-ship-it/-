import asyncio
import logging
import random
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

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
    THEMES, LEVELS, level_for, TITLES, FRAMES, REF_FRAMES,
    PRAISE, SAD, NIGHT_OWL, EARLY_BIRD, WEATHER_OTCH, SLOGANS,
    REMINDERS, SEASON_LEN_DAYS,
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
DUEL_WAIT: dict[int, list] = {}
DUEL_SCORES: dict[int, dict] = {}
SPRINT_STATE: dict[int, dict] = {}
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

def similar_otchestva(word: str, limit=3):
    """Похожие отчества (если есть опечатка)."""
    word = normalize(word)
    if not word:
        return []
    def dist(a, b):
        # Левенштейн простой
        m, n = len(a), len(b)
        dp = list(range(n + 1))
        for i in range(1, m + 1):
            prev = dp[:]
            dp[0] = i
            for j in range(1, n + 1):
                cost = 0 if a[i-1] == b[j-1] else 1
                dp[j] = min(prev[j] + 1, dp[j-1] + 1, prev[j-1] + cost)
        return dp[n]
    scored = []
    for m_name, (f_name, _) in OTCHESTVA.items():
        scored.append((dist(word, m_name), m_name))
        scored.append((dist(word, f_name), f_name))
    scored.sort()
    return [name.capitalize() for d, name in scored[:limit] if d <= 3]

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
    if u and (u["points"] or 0) >= 100 and db.grant_achievement(uid, "hundred"):
        unlocked.append("💯 Сотка очков")
    if u and (u["referrals"] or 0) >= 5 and db.grant_achievement(uid, "ref_5"):
        unlocked.append("🤝 Пригласил 5 друзей")
    if u and (u["daily_streak"] or 0) >= 7 and db.grant_achievement(uid, "daily_7"):
        unlocked.append("📅 Дейли 7 дней")
    if u and (u["unique_otch"] or 0) >= 20 and db.grant_achievement(uid, "collector20"):
        unlocked.append("📚 Коллекционер")
    return unlocked

def check_titles(uid: int):
    """Проверяем условия титулов. Возвращаем список новых."""
    u = db.get_user(uid)
    if not u:
        return []
    new = []
    wins = (u["duel_wins"] or 0)
    if wins >= TITLES["duelist"][1] and db.grant_title(uid, "duelist"):
        new.append(TITLES["duelist"][0])
    if (u["unique_otch"] or 0) >= TITLES["collector"][1] and db.grant_title(uid, "collector"):
        new.append(TITLES["collector"][0])
    if (u["visit_streak"] or 0) >= TITLES["streaker"][1] and db.grant_title(uid, "streaker"):
        new.append(TITLES["streaker"][0])
    if (u["sprint_best"] or 0) >= TITLES["sprinter"][1] and db.grant_title(uid, "sprinter"):
        new.append(TITLES["sprinter"][0])
    if (u["referrals"] or 0) >= TITLES["refmaster"][1] and db.grant_title(uid, "refmaster"):
        new.append(TITLES["refmaster"][0])
    if (u["daily_streak"] or 0) >= TITLES["dailyhero"][1] and db.grant_title(uid, "dailyhero"):
        new.append(TITLES["dailyhero"][0])
    return new

def today_otchestvo():
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

def greeting_by_time():
    h = datetime.now().hour
    if h < 6:
        return random.choice(NIGHT_OWL)
    if h < 10:
        return random.choice(EARLY_BIRD)
    return ""

def frame_for(user):
    if not user:
        return "⬜"
    _, idx, _ = level_for(user["points"] or 0)
    return FRAMES.get(idx, "⬜")

def title_for(user):
    if not user:
        return ""
    t = user["title"] if "title" in user.keys() else None
    if t and t in TITLES:
        return " " + TITLES[t][0]
    return ""

# ===================== КЛАВИАТУРЫ =====================
MENU_TEXTS = {
    "📊 Профиль", "🏆 Топ", "🎯 Викторина", "📅 Дейли",
    "⭐ Избранное", "📜 История", "💡 Факт", "🔮 Предсказание",
    "🛂 Паспорт", "ℹ️ Помощь", "💨 Спринт", "💀 Хардкор",
}

def bottom_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Профиль"), KeyboardButton(text="🏆 Топ")],
            [KeyboardButton(text="🎯 Викторина"), KeyboardButton(text="📅 Дейли")],
            [KeyboardButton(text="💨 Спринт"), KeyboardButton(text="💀 Хардкор")],
            [KeyboardButton(text="⭐ Избранное"), KeyboardButton(text="📜 История")],
            [KeyboardButton(text="💡 Факт"), KeyboardButton(text="🔮 Предсказание")],
            [KeyboardButton(text="🛂 Паспорт"), KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши отчество (например, Иванович)",
    )

def inline_main():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 Викторина", callback_data="quiz")
    kb.button(text="📅 Дейли", callback_data="daily")
    kb.button(text="💨 Спринт 60с", callback_data="sprint")
    kb.button(text="💀 Хардкор", callback_data="hardcore")
    kb.button(text="🏃 Марафон 50", callback_data="marathon")
    kb.button(text="⚔️ Дуэль", callback_data="duel")
    kb.button(text="📊 Профиль", callback_data="profile")
    kb.button(text="🏆 Топ", callback_data="topmenu")
    kb.button(text="🤝 Рефереры", callback_data="reftop")
    kb.button(text="📈 Сезон", callback_data="season")
    kb.button(text="🎯 Цель", callback_data="goal")
    kb.button(text="⚙️ Квесты", callback_data="quests")
    kb.button(text="🎨 Тема", callback_data="theme")
    kb.button(text="🎭 Стиль", callback_data="style")
    kb.button(text="🔕 Тихий режим", callback_data="silent")
    kb.button(text="💎 Premium", callback_data="premium")
    kb.button(text="ℹ️ Помощь", callback_data="help")
    kb.adjust(2, 2, 2, 2, 2, 2, 2, 1)
    return kb.as_markup()

def quiz_kb(options):
    kb = InlineKeyboardBuilder()
    for opt in options:
        kb.button(text=opt, callback_data=f"quizans:{opt}")
    kb.button(text="⏭ Пропустить", callback_data="quizskip")
    kb.button(text="🛑 Закончить", callback_data="quizstop")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()

def result_kb(otch):
    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ В избранное", callback_data=f"favadd:{otch}")
    kb.button(text="🔗 Поделиться", callback_data=f"share:{otch}")
    kb.button(text="🔮 Предсказание", callback_data="predict")
    kb.button(text="🎯 Ещё вопрос", callback_data="quiz")
    kb.adjust(2, 2)
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
            DUEL_SCORES[duel_id] = {"c": 0, "o": 0, "c_uid": challenger_id, "o_uid": message.from_user.id}
            try:
                await message.bot.send_message(
                    challenger_id,
                    f"⚔️ Тебя вызвал на дуэль <b>{message.from_user.first_name}</b>!\nНачинаем...",
                )
            except Exception:
                pass
            await message.answer("⚔️ <b>Дуэль принята!</b>\n5 вопросов, 15 секунд на каждый.")
            asyncio.create_task(_duel_run(message.bot, duel_id))
            return
        await cmd_start(message)
        return

    # --- Публичный профиль ---
    if arg.startswith("u_"):
        try:
            target = int(arg.split("_", 1)[1])
        except Exception:
            target = None
        if target:
            await send_public_profile(message, target)
            await cmd_start(message)
            return

    # --- Реферал ---
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
            refs = (u["referrals"] or 0) if u and "referrals" in u.keys() else 0
            bonus = REF_LEVELS.get(refs)
            extra = f"\n🎁 Бонус за {refs} друзей: +{bonus} очков!" if bonus else ""
            if bonus:
                db.add_points(referrer_id, bonus)
            try:
                await message.bot.send_message(referrer_id, f"🎁 Пришёл друг по ссылке! +{REF_BONUS}{extra}")
            except Exception as e:
                log.warning("referrer notify: %s", e)

    await cmd_start(message)

@dp.message(CommandStart())
async def cmd_start(message: Message):
    uid = message.from_user.id
    db.create_user(uid, message.from_user.username, message.from_user.first_name)
    db.update_user_profile(uid, message.from_user.username, message.from_user.first_name)

    bonus, vstreak = db.register_visit(uid)
    visit_info = ""
    if bonus:
        visit_info = f"\n🎁 Ежедневный бонус: <b>+{bonus}</b> очк. (стрик {vstreak} дн.)"

    new_titles = check_titles(uid)
    title_info = ""
    if new_titles:
        title_info = "\n🏅 Новый титул: " + ", ".join(new_titles)

    me = await message.bot.me()
    ref_link = f"https://t.me/{me.username}?start={uid}"
    otch, father = today_otchestvo()
    weather = random.choice(WEATHER_OTCH)
    slogan = random.choice(SLOGANS)
    greet = greeting_by_time()

    text = (
        (f"{greet}\n\n" if greet else "")
        + f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        "Я определяю имя отца по отчеству.\n"
        "А ещё: викторина, спринт, хардкор, марафон, дуэли, дейли, квесты, топ.\n\n"
        f"🌟 <b>Отчество дня:</b> {otch} → {father}\n"
        f"   Погода дня: {weather}\n"
        f"   «{slogan}»\n"
        f"{visit_info}{title_info}\n\n"
        f"🔗 Реф-ссылка:\n<code>{ref_link}</code>"
    )
    await message.answer(text, reply_markup=bottom_kb())
    await message.answer("Меню:", reply_markup=inline_main())

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Возможности</b>\n\n"
        "• Отчество → имя отца (и наоборот)\n"
        "• Ударение, транслит, склонения\n"
        "• 🎯 Викторина · 💨 Спринт 60с · 💀 Хардкор · 🏃 Марафон 50\n"
        "• 📅 Дейли-задание и стрики\n"
        "• ⚔️ Дуэли 1×1 с реваншем\n"
        "• 🎯 Цели, ⚙️ Квесты, 🏅 Титулы, 🎖 Уровни\n"
        "• 📈 Сезонный топ (30 дней)\n"
        "• Топы: игроки, рефереры, стрики, дейли, сезон\n"
        "• 🔕 Тихий режим, 🎨 Темы, 🎭 Стили\n"
        "• 🔗 Шеринг и inline\n"
        "• 📊 /stats — личная статистика\n\n"
        "Команды: /start /help /profile /top /fav /history /quiz /daily /duel /sprint /hardcore /marathon /ref /reftop /season /goal /stats /random /fact /silent /delete_me",
        reply_markup=bottom_kb(),
    )

# ===================== Reply-кнопки снизу =====================
@dp.message(F.text == "📊 Профиль")
async def kb_profile(message: Message):
    await send_profile(message, message.from_user.id)

@dp.message(F.text == "🏆 Топ")
async def kb_top(message: Message):
    await send_top_menu(message)

@dp.message(F.text == "🎯 Викторина")
async def kb_quiz(message: Message):
    await start_quiz(message, message.from_user.id)

@dp.message(F.text == "📅 Дейли")
async def kb_daily(message: Message):
    await daily_quiz(message, message.from_user.id)

@dp.message(F.text == "💨 Спринт")
async def kb_sprint(message: Message):
    await start_sprint(message, message.from_user.id)

@dp.message(F.text == "💀 Хардкор")
async def kb_hardcore(message: Message):
    await start_hardcore(message, message.from_user.id)

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

@dp.message(F.text == "🛂 Паспорт")
async def kb_passport(message: Message):
    await send_passport(message, message.from_user.id)

@dp.message(F.text == "ℹ️ Помощь")
async def kb_help(message: Message):
    await cmd_help(message)
# ===================== Callback: главное меню =====================
@dp.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery):
    await send_profile(call.message, call.from_user.id); await call.answer()

@dp.callback_query(F.data == "topmenu")
async def cb_topmenu(call: CallbackQuery):
    await send_top_menu(call.message); await call.answer()

@dp.callback_query(F.data == "reftop")
async def cb_reftop(call: CallbackQuery):
    await send_reftop(call.message); await call.answer()

@dp.callback_query(F.data == "season")
async def cb_season(call: CallbackQuery):
    await send_season(call.message); await call.answer()

@dp.callback_query(F.data == "fav")
async def cb_fav(call: CallbackQuery):
    await send_fav(call.message, call.from_user.id); await call.answer()

@dp.callback_query(F.data == "fact")
async def cb_fact(call: CallbackQuery):
    await call.message.answer("💡 " + random.choice(FACTS)); await call.answer()

@dp.callback_query(F.data == "predict")
async def cb_predict(call: CallbackQuery):
    await call.message.answer("🔮 " + random.choice(PREDICTIONS)); await call.answer()

@dp.callback_query(F.data == "toast")
async def cb_toast(call: CallbackQuery):
    await call.message.answer("🥂 " + random.choice(TOASTS)); await call.answer()

@dp.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery):
    await cmd_help(call.message); await call.answer()

@dp.callback_query(F.data == "theme")
async def cb_theme(call: CallbackQuery):
    kb = InlineKeyboardBuilder()
    for code, label in THEMES.items():
        kb.button(text=label, callback_data=f"settheme:{code}")
    kb.adjust(2, 2, 2)
    await call.message.answer("Выбери тему:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("settheme:"))
async def cb_settheme(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    db.set_theme(call.from_user.id, code)
    await call.answer("Ок")
    await call.message.answer(f"Тема: {THEMES.get(code, code)}")

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
    await call.answer("Ок")
    await call.message.answer(f"Стиль: {code}")

@dp.callback_query(F.data == "silent")
async def cb_silent(call: CallbackQuery):
    u = db.get_user(call.from_user.id)
    cur = (u["silent_mode"] if u and "silent_mode" in u.keys() else 0) or 0
    new = 0 if cur else 1
    db.set_silent(call.from_user.id, new)
    state = "включён 🔕" if new else "выключен 🔔"
    await call.answer("Ок")
    await call.message.answer(f"Тихий режим: {state}")

@dp.callback_query(F.data == "premium")
async def cb_premium(call: CallbackQuery):
    u = db.get_user(call.from_user.id)
    is_prem = bool(u and "premium" in u.keys() and u["premium"])
    st = "✅ активен" if is_prem else "❌ не активен"
    await call.message.answer(
        f"💎 <b>Premium</b> — {st}\n\n"
        "• Расширенная база\n• Без лимитов викторин\n"
        "• Эксклюзивные темы\n• Приоритетная поддержка\n\n"
        "Оплата через Stars — в разработке."
    )
    await call.answer()

@dp.callback_query(F.data == "quests")
async def cb_quests(call: CallbackQuery):
    uid = call.from_user.id
    u = db.get_user(uid)
    if not u:
        db.create_user(uid, None, None); u = db.get_user(uid)
    pts = (u["points"] or 0) if u else 0
    best = (u["best_streak"] or 0) if u else 0
    refs = (u["referrals"] or 0) if u else 0
    wins = (u["duel_wins"] or 0) if u else 0
    quests = [
        ("📚 Задай 5 отчеств", min(pts // 5, 5), 5),
        ("🎯 Победи в викторине", min(best, 1), 1),
        ("🤝 Пригласи 1 друга", min(refs, 1), 1),
        ("⚔️ Выиграй дуэль", min(wins, 1), 1),
        ("💨 Набери 30 в спринте", min((u["sprint_best"] or 0), 30), 30),
    ]
    lines = ["⚙️ <b>Квесты</b>\n"]
    for name, cur, need in quests:
        lines.append(f"• {name} — {'✅' if cur >= need else f'{cur}/{need}'}")
    await call.message.answer("\n".join(lines))
    await call.answer()

@dp.callback_query(F.data == "goal")
async def cb_goal(call: CallbackQuery):
    u = db.get_user(call.from_user.id)
    if not u:
        await call.answer("Сначала /start", show_alert=True); return
    t = u["goal_text"] if "goal_text" in u.keys() else None
    tg = (u["goal_target"] if "goal_target" in u.keys() else 0) or 0
    pg = (u["goal_progress"] if "goal_progress" in u.keys() else 0) or 0
    done = (u["goal_done"] if "goal_done" in u.keys() else 0) or 0
    if not t:
        await call.message.answer(
            "🎯 <b>Цель</b>\n\nЦели нет. Поставь:\n"
            "<code>/goal 200 Победить в топе</code>\n"
            "(200 — сколько очков набрать, дальше — текст)"
        )
    else:
        bar = "█" * min(pg, 10) + "░" * max(10 - pg, 0) if tg else ""
        status = "✅ достигнута" if done else f"{pg}/{tg}"
        await call.message.answer(f"🎯 <b>Цель:</b> {t}\nПрогресс: {status}\n{bar}")
    await call.answer()

@dp.callback_query(F.data.startswith("favadd:"))
async def cb_favadd(call: CallbackQuery):
    otch = call.data.split(":", 1)[1]
    db.add_favorite(call.from_user.id, otch)
    await call.answer("⭐ Добавлено")

@dp.callback_query(F.data.startswith("share:"))
async def cb_share(call: CallbackQuery):
    otch = call.data.split(":", 1)[1]
    await call.answer("Скопируй текст ниже и отправь другу")
    share_text = f"Я узнал: {otch} → отец! Попробуй: @{(await call.bot.me()).username}"
    await call.message.answer(f"🔗 <code>{share_text}</code>")

# ===================== ТОП-МЕНЮ =====================
@dp.callback_query(F.data.startswith("top:"))
async def cb_topswitch(call: CallbackQuery):
    mode = call.data.split(":", 1)[1]
    await send_top(call.message, mode)
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
        options = list(pool | {correct}); random.shuffle(options)
        text = f"Какое отчество, если отца зовут <b>{name}</b>?"
    else:
        correct = name
        pool = set()
        while len(pool) < 3:
            _, (_, n) = random.choice(list(OTCHESTVA.items()))
            if n != correct:
                pool.add(n)
        options = list(pool | {correct}); random.shuffle(options)
        text = f"Как зовут отца, если отчество <b>{otch}</b>?"
    return text, correct, options

async def start_quiz(message, uid=None, length=QUIZ_LEN, mode="quiz", mult=1):
    uid = uid or message.chat.id
    db.create_user(uid, None, None)
    text, correct, options = _new_question()
    sent = await message.answer(
        f"🎯 <b>Вопрос 1/{length}</b>\n\n{text}",
        reply_markup=quiz_kb(options),
    )
    QUIZ_STATE[sent.message_id] = {
        "uid": uid, "q_num": 1, "score": 0, "correct": correct,
        "started_at": time.time(), "answered": False,
        "length": length, "mode": mode, "mult": mult,
    }

async def _next_question(message, state):
    length = state.get("length", QUIZ_LEN)
    mult = state.get("mult", 1)
    if state["q_num"] >= length:
        score = state["score"] * mult
        db.add_points(state["uid"], score)
        u = db.get_user(state["uid"])
        unlocked = check_achievements(state["uid"], (u["streak"] if u else 0), state["score"])
        titles = check_titles(state["uid"])
        db.update_goal(state["uid"], 1)
        lines = [
            f"🏁 <b>Итог</b>",
            f"Правильных: <b>{state['score']}/{length}</b>",
            f"Начислено: <b>+{score}</b>",
        ]
        if mult > 1:
            lines.append(f"✨ Множитель x{mult}")
        if state["score"] >= length * 0.8:
            lines.append("🏅 Отличный результат!")
        if unlocked:
            lines.append("🏅 " + ", ".join(unlocked))
        if titles:
            lines.append("🏆 Новый титул: " + ", ".join(titles))
        await message.answer("\n".join(lines))
        return
    text, correct, options = _new_question()
    q_num = state["q_num"] + 1
    state.update({"q_num": q_num, "correct": correct,
                  "started_at": time.time(), "answered": False})
    sent = await message.answer(
        f"🎯 <b>Вопрос {q_num}/{length}</b> · очки: {state['score']}\n\n{text}",
        reply_markup=quiz_kb(options),
    )
    QUIZ_STATE[sent.message_id] = state

@dp.callback_query(F.data == "quiz")
async def cb_quiz(call: CallbackQuery):
    await start_quiz(call.message, call.from_user.id); await call.answer()

@dp.callback_query(F.data == "quizskip")
async def cb_quizskip(call: CallbackQuery):
    st = QUIZ_STATE.get(call.message.message_id)
    if not st or st.get("answered"):
        await call.answer("Уже отвечено"); return
    st["answered"] = True
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    QUIZ_STATE.pop(call.message.message_id, None)
    db.inc_streak(st["uid"], False)
    await call.answer("Пропуск")
    await call.message.answer(f"⏭ Пропущено. Правильно: <b>{st['correct']}</b>")
    await _next_question(call.message, st)

@dp.callback_query(F.data == "quizstop")
async def cb_quizstop(call: CallbackQuery):
    st = QUIZ_STATE.get(call.message.message_id)
    if not st:
        await call.answer("Уже завершено"); return
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    QUIZ_STATE.pop(call.message.message_id, None)
    score = st["score"] * st.get("mult", 1)
    db.add_points(st["uid"], score)
    await call.answer("Стоп")
    await call.message.answer(
        f"🛑 Остановлено. Правильных: {st['score']}/{st['q_num']-1}. +{score}"
    )

@dp.callback_query(F.data.startswith("quizans:"))
async def cb_quizans(call: CallbackQuery):
    st = QUIZ_STATE.get(call.message.message_id)
    if not st:
        await call.answer("Сессия истекла, /quiz", show_alert=True); return
    if st.get("answered"):
        await call.answer("Уже отвечено"); return
    st["answered"] = True
    answer = call.data.split(":", 1)[1]
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    QUIZ_STATE.pop(call.message.message_id, None)

    elapsed = time.time() - st["started_at"]
    speed = 2 if elapsed < 3 else (1 if elapsed < 7 else 0)

    if answer == st["correct"]:
        st["score"] += 1 + speed
        db.inc_streak(st["uid"], True)
        u = db.get_user(st["uid"])
        streak = u["streak"] if u else 1
        extra = [random.choice(PRAISE)]
        if speed: extra.append(f"⚡ +{speed}")
        if streak >= 5: extra.append(f"🔥 серия {streak}")
        await call.answer("Верно!")
        await call.message.answer("✅ +" + str(1 + speed) + " · " + " · ".join(extra))
    else:
        db.inc_streak(st["uid"], False)
        await call.answer("Мимо")
        await call.message.answer(f"❌ Мимо. Правильно: <b>{st['correct']}</b>\n{random.choice(SAD)}")

    await _next_question(call.message, st)

# ===================== СПРИНТ 60 СЕК =====================
SPRINT_SECONDS = 60

async def start_sprint(message, uid):
    db.create_user(uid, None, None)
    text, correct, options = _new_question()
    SPRINT_STATE[uid] = {
        "score": 0, "correct": correct, "answered": False,
        "until": time.time() + SPRINT_SECONDS, "msg_id": None,
    }
    sent = await message.answer(
        f"💨 <b>Спринт {SPRINT_SECONDS} сек</b>\n"
        f"Очки ×3, успей больше!\n\n{text}",
        reply_markup=quiz_kb(options),
    )
    SPRINT_STATE[uid]["msg_id"] = sent.message_id
    asyncio.create_task(_sprint_timer(message.bot, uid, message.chat.id))

async def _sprint_timer(bot, uid, chat_id):
    await asyncio.sleep(SPRINT_SECONDS + 1)
    st = SPRINT_STATE.pop(uid, None)
    if not st:
        return
    score = st["score"] * 3
    db.add_points(uid, score)
    db.update_mode_best(uid, "sprint", st["score"])
    titles = check_titles(uid)
    msg = f"💨 <b>Спринт завершён!</b>\nПравильных: {st['score']}\nНачислено: <b>+{score}</b>"
    if titles:
        msg += "\n🏆 Новый титул: " + ", ".join(titles)
    try:
        await bot.send_message(chat_id, msg)
    except Exception:
        pass

@dp.callback_query(F.data == "sprint")
async def cb_sprint(call: CallbackQuery):
    await start_sprint(call.message, call.from_user.id); await call.answer()

@dp.callback_query(F.data.startswith("sprintans:"))
async def cb_sprintans(call: CallbackQuery):
    uid = call.from_user.id
    st = SPRINT_STATE.get(uid)
    if not st or time.time() > st["until"]:
        await call.answer("Спринт закончился"); return
    answer = call.data.split(":", 1)[1]
    if answer == st["correct"]:
        st["score"] += 1
        await call.answer("✅")
    else:
        await call.answer(f"❌ Правильно: {st['correct']}")
    # новый вопрос
    text, correct, options = _new_question()
    st["correct"] = correct
    try:
        await call.message.edit_text(
            f"💨 <b>Спринт</b> · очки: {st['score']} · осталось: {int(st['until']-time.time())}с\n\n{text}",
            reply_markup=quiz_kb(options),
        )
    except Exception:
        pass

# ===================== ХАРДКОР =====================
async def start_hardcore(message, uid):
    db.create_user(uid, None, None)
    text, correct, options = _new_question()
    sent = await message.answer(
        "💀 <b>Хардкор</b>\n3 жизни, ошибёшься 3 раза — конец.\n\n" + text,
        reply_markup=quiz_kb(options),
    )
    QUIZ_STATE[sent.message_id] = {
        "uid": uid, "q_num": 1, "score": 0, "correct": correct,
        "started_at": time.time(), "answered": False,
        "length": 999, "mode": "hardcore", "mult": 1, "lives": 3,
    }

@dp.callback_query(F.data == "hardcore")
async def cb_hardcore(call: CallbackQuery):
    await start_hardcore(call.message, call.from_user.id); await call.answer()

# ===================== МАРАФОН =====================
async def start_marathon(message, uid):
    await start_quiz(message, uid, length=50, mode="marathon", mult=2)

@dp.callback_query(F.data == "marathon")
async def cb_marathon(call: CallbackQuery):
    await start_marathon(call.message, call.from_user.id); await call.answer()

# ===================== ДЕЙЛИ =====================
async def daily_quiz(message, uid):
    today = date.today().isoformat()
    u = db.get_user(uid) or {}
    if not u:
        db.create_user(uid, None, None); u = db.get_user(uid)
    if u and u["daily_done"] == today:
        await message.answer("📅 Дейли уже пройден. Завтра снова!"); return
    prev = u["last_daily"] if u else None
    d_streak = (u["daily_streak"] if u and u["daily_streak"] else 0)
    if prev:
        try:
            d1 = datetime.fromisoformat(prev).date()
            diff = (date.today() - d1).days
            d_streak = d_streak + 1 if diff == 1 else 1
        except Exception:
            d_streak = 1
    else:
        d_streak = 1
    db.set_daily(uid, today, d_streak)
    await message.answer(f"📅 <b>Дейли</b> · стрик {d_streak} дн. · множитель x2")
    await start_quiz(message, uid, length=3, mode="daily", mult=2)

@dp.callback_query(F.data == "daily")
async def cb_daily(call: CallbackQuery):
    await daily_quiz(call.message, call.from_user.id); await call.answer()

# ===================== ДУЭЛЬ =====================
@dp.callback_query(F.data == "duel")
async def cb_duel(call: CallbackQuery):
    me = await call.bot.me()
    link = f"https://t.me/{me.username}?start=duel_{call.from_user.id}"
    c_wins, c_losses = db.duel_stats(call.from_user.id)
    await call.message.answer(
        f"⚔️ <b>Дуэль</b>\n\nТвоя статистика: 🏆 {c_wins} / 💀 {c_losses}\n\n"
        "Отправь другу ссылку:\n"
        f"<code>{link}</code>"
    )
    await call.answer()

async def _duel_run(bot, duel_id):
    duel = db.duel_get(duel_id)
    if not duel:
        return
    challenger, opponent = duel["challenger"], duel["opponent"]
    questions = [_new_question() for _ in range(5)]
    c_score = o_score = 0

    for idx, (text, correct, options) in enumerate(questions, 1):
        kb = InlineKeyboardBuilder()
        for opt in options:
            kb.button(text=opt, callback_data=f"duelans:{duel_id}:{idx}:{opt}")
        kb.adjust(2)
        msg = f"⚔️ <b>Дуэль — вопрос {idx}/5</b>\n\n{text}"
        try: await bot.send_message(challenger, msg, reply_markup=kb.as_markup())
        except Exception: pass
        try: await bot.send_message(opponent, msg, reply_markup=kb.as_markup())
        except Exception: pass

        deadline = time.time() + 15
        DUEL_WAIT[duel_id] = []
        answered = {}
        while time.time() < deadline and len(answered) < 2:
            await asyncio.sleep(0.3)
            while DUEL_WAIT.get(duel_id):
                uid, ans = DUEL_WAIT[duel_id].pop(0)
                if uid in (challenger, opponent) and uid not in answered:
                    answered[uid] = ans
        for uid, ans in answered.items():
            if ans == correct:
                if uid == challenger: c_score += 1
                else: o_score += 1
        db.duel_update(duel_id, c_score, o_score, "running")

    db.duel_update(duel_id, c_score, o_score, "finished")
    if c_score > o_score:
        winner, result = challenger, "🏆 Победил вызывающий!"
    elif o_score > c_score:
        winner, result = opponent, "🏆 Победил соперник!"
    else:
        winner, result = None, "🤝 Ничья!"

    if winner:
        db.add_points(winner, 5)
        db.update_duel_result(winner, True)
        db.update_duel_result(opponent if winner == challenger else challenger, False)
    else:
        db.update_duel_result(challenger, False)
        db.update_duel_result(opponent, False)

    summary = (
        f"🏁 <b>Дуэль завершена</b>\n\n"
        f"Вызывающий: <b>{c_score}</b>\nСоперник: <b>{o_score}</b>\n\n{result}"
    )
    if winner:
        summary += "\nПобедитель: +5 очков."

    kb = InlineKeyboardBuilder()
    kb.button(text="🔁 Реванш", callback_data=f"rematch:{duel_id}")
    kb.button(text="📊 Профиль", callback_data="profile")
    kb.adjust(2)

    for uid in (challenger, opponent):
        try: await bot.send_message(uid, summary, reply_markup=kb.as_markup())
        except Exception: pass

@dp.callback_query(F.data.startswith("duelans:"))
async def cb_duelans(call: CallbackQuery):
    _, duel_id, idx, ans = call.data.split(":", 3)
    uid = call.from_user.id
    DUEL_WAIT.setdefault(int(duel_id), []).append((uid, ans))
    await call.answer("Принято")
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass

@dp.callback_query(F.data.startswith("rematch:"))
async def cb_rematch(call: CallbackQuery):
    duel_id = int(call.data.split(":", 1)[1])
    duel = db.duel_get(duel_id)
    if not duel:
        await call.answer("Дуэль не найдена", show_alert=True); return
    new_id = db.duel_create(duel["opponent"], duel["challenger"])
    DUEL_WAIT[new_id] = []
    DUEL_SCORES[new_id] = {"c": 0, "o": 0, "c_uid": duel["opponent"], "o_uid": duel["challenger"]}
    await call.answer("Реванш начался!")
    try:
        await call.bot.send_message(duel["opponent"], "🔁 Твой соперник требует реванш!")
        await call.bot.send_message(duel["challenger"], "🔁 Реванш принят!")
    except Exception:
        pass
    asyncio.create_task(_duel_run(call.bot, new_id))
# ===================== КОМАНДЫ =====================
@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    await send_profile(message, message.from_user.id)

@dp.message(Command("top"))
async def cmd_top(message: Message):
    await send_top_menu(message)

@dp.message(Command("fav"))
async def cmd_fav(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) == 1:
        await send_fav(message, message.from_user.id); return
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

@dp.message(Command("sprint"))
async def cmd_sprint(message: Message):
    await start_sprint(message, message.from_user.id)

@dp.message(Command("hardcore"))
async def cmd_hardcore(message: Message):
    await start_hardcore(message, message.from_user.id)

@dp.message(Command("marathon"))
async def cmd_marathon(message: Message):
    await start_marathon(message, message.from_user.id)

@dp.message(Command("duel"))
async def cmd_duel(message: Message):
    me = await message.bot.me()
    link = f"https://t.me/{me.username}?start=duel_{message.from_user.id}"
    c_wins, c_losses = db.duel_stats(message.from_user.id)
    await message.answer(
        f"⚔️ <b>Дуэль</b>\n\n🏆 {c_wins} / 💀 {c_losses}\n\n"
        f"Отправь ссылку другу:\n<code>{link}</code>"
    )

@dp.message(Command("ref"))
async def cmd_ref(message: Message):
    me = await message.bot.me()
    u = db.get_user(message.from_user.id)
    refs = (u["referrals"] or 0) if u and "referrals" in u.keys() else 0
    link = f"https://t.me/{me.username}?start={message.from_user.id}"
    next_bonus = ""
    for need, bonus in sorted(REF_LEVELS.items()):
        if refs < need:
            next_bonus = f"\nДо бонуса за {need}: ещё {need - refs} 🤝"; break
    await message.answer(
        f"🔗 <b>Реферальная программа</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"Приглашено: <b>{refs}</b> · +{REF_BONUS} за друга.{next_bonus}"
    )

@dp.message(Command("reftop"))
async def cmd_reftop(message: Message):
    await send_reftop(message)

@dp.message(Command("season"))
async def cmd_season(message: Message):
    await send_season(message)

@dp.message(Command("goal"))
async def cmd_goal(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: <code>/goal 200 Победить в топе</code>")
        return
    try:
        target = int(parts[1])
    except ValueError:
        await message.answer("Первое число — цель по очкам")
        return
    db.set_goal(message.from_user.id, parts[2], target)
    await message.answer(f"🎯 Цель: <b>{parts[2]}</b> ({target} очк.)")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    u = db.get_user(message.from_user.id)
    if not u:
        await message.answer("Сначала /start"); return
    hist = db.get_history(message.from_user.id, 1000)
    total = len(hist)
    unique = u["unique_otch"] or 0
    wins, losses = db.duel_stats(message.from_user.id)
    titles = db.get_titles(message.from_user.id)
    title_names = [TITLES[t][0] for t in titles if t in TITLES]
    await message.answer(
        f"📊 <b>Личная статистика</b>\n\n"
        f"Запросов: <b>{total}</b>\n"
        f"Уникальных отчеств: <b>{unique}</b>\n"
        f"Очки: <b>{u['points'] or 0}</b>\n"
        f"Рекорд серии: <b>{u['best_streak'] or 0}</b>\n"
        f"🔥 Визит-стрик: <b>{u['visit_streak'] or 0}</b> дн.\n"
        f"📅 Дейли-стрик: <b>{u['daily_streak'] or 0}</b> дн.\n"
        f"💨 Спринт-рекорд: <b>{u['sprint_best'] or 0}</b>\n"
        f"💀 Хардкор-рекорд: <b>{u['hardcore_best'] or 0}</b>\n"
        f"⚔️ Дуэли: 🏆 {wins} / 💀 {losses}\n"
        f"👥 Рефералы: <b>{u['referrals'] or 0}</b>\n"
        f"🏅 Титулы: {', '.join(title_names) if title_names else '—'}\n"
        f"📈 Сезон #{u['season_id'] or 1}: <b>{u['season_points'] or 0}</b> очк."
    )

@dp.message(Command("silent"))
async def cmd_silent(message: Message):
    u = db.get_user(message.from_user.id)
    cur = (u["silent_mode"] if u and "silent_mode" in u.keys() else 0) or 0
    new = 0 if cur else 1
    db.set_silent(message.from_user.id, new)
    await message.answer(f"🔕 Тихий режим: {'включён' if new else 'выключен'}")

@dp.message(Command("delete_me"))
async def cmd_delete_me(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Удалить мои данные", callback_data="delete_confirm")
    kb.button(text="Отмена", callback_data="delete_cancel")
    kb.adjust(1, 1)
    await message.answer(
        "⚠️ Удалить все твои данные (очки, историю, избранное)?\n"
        "Действие необратимо.",
        reply_markup=kb.as_markup(),
    )

@dp.callback_query(F.data == "delete_confirm")
async def cb_delete_confirm(call: CallbackQuery):
    uid = call.from_user.id
    import sqlite3
    with sqlite3.connect(db.DB_PATH) as con:
        cur = con.cursor()
        for t in ("users", "history", "favorites", "achievements", "quests", "titles"):
            try:
                cur.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
            except Exception:
                pass
        con.commit()
    await call.message.edit_text("🗑 Твои данные удалены. Напиши /start чтобы начать заново.")
    await call.answer("Удалено")

@dp.callback_query(F.data == "delete_cancel")
async def cb_delete_cancel(call: CallbackQuery):
    await call.message.edit_text("Отменено.")
    await call.answer()

@dp.message(Command("random"))
async def cmd_random(message: Message):
    m, (f, name) = random.choice(list(OTCHESTVA.items()))
    await message.answer(f"🎲 <b>{random.choice([m, f]).capitalize()}</b> → отец <b>{name}</b>")

@dp.message(Command("fact"))
async def cmd_fact(message: Message):
    await message.answer("💡 " + random.choice(FACTS))

# ===================== ОСНОВНОЙ ТЕКСТ =====================
@dp.message(F.text & ~F.text.startswith("/") & ~F.text.in_(MENU_TEXTS))
async def handle_text(message: Message):
    uid = message.from_user.id
    if is_flood(uid):
        await message.answer("⏳ Слишком быстро"); return
    text = message.text.strip()

    parts = text.split()
    if len(parts) == 2 and parts[1].lower() in ("м", "ж", "m", "f"):
        female = parts[1].lower() in ("ж", "f")
        otch = find_otchestvo_by_name(parts[0], female)
        if otch:
            await message.answer(f"👨 <b>{parts[0]}</b> → <b>{otch}</b>"); return
        await message.answer("Не знаю такого имени 🤔"); return

    res = find_father(text)
    if not res:
        # опечатка?
        similar = similar_otchestva(text)
        if similar:
            await message.answer(
                "🤔 Не нашёл точного совпадения. Возможно, ты имел в виду:\n"
                + "\n".join(f"• {s}" for s in similar)
            )
        else:
            db.register_unknown(normalize(text))
            await message.answer("🤔 Не знаю такого отчества. Попробуй <b>Иванович</b> или /random")
        return

    name, otch, female = res
    db.add_history(uid, otch, name)
    u = db.get_user(uid)
    style = (u["answer_style"] if u and "answer_style" in u.keys() else "normal") or "normal"
    unlocked = check_achievements(uid, (u["streak"] if u else 0) or 0)
    titles = check_titles(uid)
    db.update_goal(uid, 1)

    if style == "short":
        text_out = f"🎯 <b>{otch}</b> → отец <b>{name}</b>"
    elif style == "fun":
        text_out = (
            f"🎭 <b>{otch}</b> — мощное отчество!\n"
            f"👨 Отец: <b>{name}</b>\n"
            f"🔮 {random.choice(PREDICTIONS)}"
        )
    else:
        origin = NAME_ORIGIN.get(name, "")
        saint = SAINTS.get(name, "")
        celebs = CELEBRITIES.get(name, [])
        char = CHARACTER.get(name, "")
        text_out = (
            f"🎯 <b>{otch}</b>\n\n"
            f"👨 Отец: <b>{name}</b>\n"
            f"🔤 Ударение: {udarenie(otch.lower())}\n"
            f"🌍 Транслит: {translit(otch)}\n"
            f"📚 Склонения: {', '.join(skloneniya(otch, female))}\n"
        )
        if origin: text_out += f"📖 Происхождение: {origin}\n"
        if char:   text_out += f"🧠 Характер: {char}\n"
        if saint:  text_out += f"⛪ Святой: {saint}\n"
        if celebs: text_out += f"🌟 Знаменитости: {', '.join(celebs[:3])}\n"
    if unlocked:
        text_out += "\n🏅 " + ", ".join(unlocked)
    if titles:
        text_out += "\n🏆 Новый титул: " + ", ".join(titles)

    # реакция ✅ на сообщение
    try:
        await message.react([{"type": "emoji", "emoji": "🔥"}])
    except Exception:
        pass

    await message.answer(text_out, reply_markup=result_kb(otch))

@dp.message(~F.text)
async def handle_non_text(message: Message):
    await message.answer("Пришли текстом отчество 🙂")

# ===================== INLINE =====================
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
            id="2", title="Пример", description=f"{m.capitalize()} → {name}",
            input_message_content=InputTextMessageContent(
                message_text=f"Например: <b>{m.capitalize()}</b> → отец <b>{name}</b>",
                parse_mode=ParseMode.HTML,
            ),
        ))
    await query.answer(results, cache_time=5, is_personal=True)

# ===================== РЕНДЕРЫ =====================
async def send_profile(message: Message, uid=None):
    uid = uid or message.chat.id
    u = db.get_user(uid)
    if not u:
        db.create_user(uid, None, "Гость"); u = db.get_user(uid)
    ach = db.get_achievements(uid)
    titles = db.get_titles(uid)
    title_names = [TITLES[t][0] for t in titles if t in TITLES]
    points = u["points"] or 0
    level, lvl_idx, nxt = level_for(points)
    frame = FRAMES.get(lvl_idx, "⬜")
    progress = ""
    if nxt:
        progress = f"\n⬆️ До след.: {nxt[0] - points} очк."
    refs = u["referrals"] or 0
    ref_frame = ""
    for need, icon in sorted(REF_FRAMES.items()):
        if refs >= need:
            ref_frame = " " + icon
    wins, losses = db.duel_stats(uid)
    goal_text = u["goal_text"] if "goal_text" in u.keys() else None
    goal_tg = (u["goal_target"] if "goal_target" in u.keys() else 0) or 0
    goal_pg = (u["goal_progress"] if "goal_progress" in u.keys() else 0) or 0
    goal_done = (u["goal_done"] if "goal_done" in u.keys() else 0) or 0
    goal_line = ""
    if goal_text:
        if goal_done:
            goal_line = f"\n🎯 Цель: ✅ {goal_text}"
        else:
            goal_line = f"\n🎯 Цель: {goal_text} ({goal_pg}/{goal_tg})"

    text = (
        f"📊 <b>Профиль</b> {frame}{ref_frame}\n\n"
        f"👤 {u['first_name'] or 'Гость'}"
        + (f" (@{u['username']})" if u['username'] else "") + "\n"
        f"🎖 Уровень: <b>{level}</b>\n"
        f"⭐ Очки: <b>{points}</b>\n"
        f"📈 Сезон #{u['season_id'] or 1}: <b>{u['season_points'] or 0}</b>\n"
        f"🔥 Серия: <b>{u['streak'] or 0}</b> · 🏆 {u['best_streak'] or 0}\n"
        f"👋 Визит-стрик: <b>{u['visit_streak'] or 0}</b> дн.\n"
        f"📅 Дейли: <b>{u['daily_streak'] or 0}</b> дн.\n"
        f"⚔️ Дуэли: 🏆 {wins} / 💀 {losses}\n"
        f"👥 Рефералы: <b>{refs}</b>\n"
        f"🏅 Достижений: <b>{len(ach)}</b>\n"
        f"🏆 Титулы: {', '.join(title_names) if title_names else '—'}"
        f"{goal_line}{progress}"
    )
    await message.answer(text)

async def send_public_profile(message: Message, target_id: int):
    u = db.get_user(target_id)
    if not u:
        await message.answer("Профиль не найден 🤷"); return
    level, _, _ = level_for(u["points"] or 0)
    wins, losses = db.duel_stats(target_id)
    await message.answer(
        f"👤 <b>Публичный профиль</b>\n\n"
        f"Имя: {u['first_name'] or 'Гость'}\n"
        f"Уровень: <b>{level}</b>\n"
        f"⭐ Очки: <b>{u['points'] or 0}</b>\n"
        f"⚔️ Дуэли: 🏆 {wins} / 💀 {losses}"
    )

async def send_top_menu(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ Очки", callback_data="top:points")
    kb.button(text="🔥 Стрик", callback_data="top:streak")
    kb.button(text="📅 Дейли", callback_data="top:daily")
    kb.button(text="📈 Сезон", callback_data="top:season")
    kb.button(text="🤝 Рефералы", callback_data="top:refs")
    kb.adjust(2, 2, 1)
    await message.answer("🏆 <b>Топы</b>\nВыбери категорию:", reply_markup=kb.as_markup())

async def send_top(message: Message, mode="points"):
    if mode == "points":
        rows = db.top_users(10)
        header = "🏆 <b>Топ по очкам</b>\n"
        col = lambda r: f"{r['points']} очк."
    elif mode == "streak":
        rows = db.top_streak(10)
        header = "🔥 <b>Топ по стрику</b>\n"
        col = lambda r: f"{r['best_streak']} подряд"
    elif mode == "daily":
        rows = db.top_daily(10)
        header = "📅 <b>Топ по дейли</b>\n"
        col = lambda r: f"{r['daily_streak']} дн."
    elif mode == "season":
        rows = db.top_season(10)
        header = f"📈 <b>Сезон #{db.get_season_id()}</b>\n"
        col = lambda r: f"{r['season_points'] or 0} очк."
    elif mode == "refs":
        rows = db.top_referrers(10)
        header = "🤝 <b>Топ рефереров</b>\n"
        col = lambda r: f"{r['referrals']} друзей"
    else:
        rows = db.top_users(10)
        header = "🏆 <b>Топ</b>\n"
        col = lambda r: f"{r['points']} очк."

    if not rows:
        await message.answer("Пока пусто")
        return
    lines = [header]
    for i, r in enumerate(rows, 1):
        name = r["first_name"] or (r["username"] or "Гость")
        lines.append(f"{i}. {name} — {col(r)}")
    await message.answer("\n".join(lines))

async def send_reftop(message: Message):
    rows = db.top_referrers(10)
    if not rows:
        await message.answer("Пока никого 🤝"); return
    lines = ["🤝 <b>Топ рефереров</b>\n"]
    for i, r in enumerate(rows, 1):
        name = r["first_name"] or (r["username"] or "Гость")
        lines.append(f"{i}. {name} — {r['referrals']} друзей")
    await message.answer("\n".join(lines))

async def send_season(message: Message):
    rows = db.top_season(10)
    sid = db.get_season_id()
    lines = [f"📈 <b>Сезон #{sid}</b> (длится {SEASON_LEN_DAYS} дней)\n"]
    if rows:
        for i, r in enumerate(rows, 1):
            name = r["first_name"] or (r["username"] or "Гость")
            lines.append(f"{i}. {name} — {r['season_points'] or 0} очк.")
    else:
        lines.append("Пока пусто")
    await message.answer("\n".join(lines))

async def send_fav(message: Message, uid=None):
    uid = uid or message.chat.id
    favs = db.get_favorites(uid)
    if not favs:
        await message.answer("⭐ Пусто. Добавь: <code>/fav Иванович</code>"); return
    await message.answer("⭐ <b>Избранное</b>\n\n" + "\n".join(f"• {f}" for f in favs))

async def send_history(message: Message, uid=None):
    uid = uid or message.chat.id
    rows = db.get_history(uid, 10)
    if not rows:
        await message.answer("📜 История пуста"); return
    lines = ["📜 <b>Последние</b>\n"]
    for r in rows:
        lines.append(f"• {r['otchestvo']} → {r['father']}")
    await message.answer("\n".join(lines))

async def send_passport(message: Message, uid: int):
    u = db.get_user(uid)
    if not u:
        db.create_user(uid, None, "Гость"); u = db.get_user(uid)
    last_father = db.get_last_father(uid)
    if last_father:
        otch = find_otchestvo_by_name(last_father, False) or "Иванович"
        father = last_father
    else:
        otch, father = "Иванович", "Иван"
    first = u["first_name"] or "Гражданин"
    level, _, _ = level_for(u["points"] or 0)
    titles = db.get_titles(uid)
    title_names = [TITLES[t][0] for t in titles if t in TITLES]
    me = await message.bot.me()

    text = (
        "╔══════════════════════════╗\n"
        "║   🛂  ПАСПОРТ ГРАЖДАНИНА  ║\n"
        "╠══════════════════════════╣\n"
        f"║ 👤 {first:<22}║\n"
        f"║ 👨 Отец: {father:<16}║\n"
        f"║ 🎯 Отчество: {otch:<13}║\n"
        f"║ 🎖 Уровень: {level:<13}║\n"
        f"║ 📅 Выдан: {date.today().isoformat():<14}║\n"
        "╠══════════════════════════╣\n"
        "║  Действителен бессрочно 😎║\n"
        f"║  Выдан ботом @{me.username:<11}║\n"
        "╚══════════════════════════╝"
    )
    if title_names:
        text += "\n🏆 " + " · ".join(title_names)
    await message.answer(f"<code>{text}</code>")

# ===================== АДМИНКА =====================
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    users, queries, top = db.global_stats()
    unknown = db.get_unknown(10)
    lines = [
        "🛠 <b>Админ</b>\n",
        f"👥 Юзеров: <b>{users}</b>",
        f"🔎 Запросов: <b>{queries}</b>\n",
        "<b>Топ отчеств:</b>",
    ]
    for r in top:
        lines.append(f"• {r['otchestvo']} — {r['c']}")
    if unknown:
        lines.append("\n<b>Неизвестные отчества (кандидаты):</b>")
        for o, hits in unknown:
            lines.append(f"• {o} × {hits}")
    lines.append(
        "\n/broadcast текст\n/backup — бэкап БД\n"
        "/premium ID 0/1\n/season_reset — сброс сезона"
    )
    await message.answer("\n".join(lines))

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /broadcast текст"); return
    sent = failed = 0
    for uid in db.all_user_ids():
        try:
            await message.bot.send_message(uid, parts[1]); sent += 1
        except Exception:
            failed += 1
    await message.answer(f"✅ {sent}, ошибок: {failed}")

@dp.message(Command("backup"))
async def cmd_backup(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    db.backup_db()
    await message.answer("💾 Бэкап создан в backups/")

@dp.message(Command("premium"))
async def cmd_premium(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("/premium <user_id> <0|1>"); return
    try:
        uid, val = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("Числа, пожалуйста"); return
    db.set_premium(uid, val)
    await message.answer(f"✅ Premium {uid}: {val}")

@dp.message(Command("season_reset"))
async def cmd_season_reset(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    db.season_reset()
    await message.answer("📈 Сезон сброшен.")

# ===================== ФОНОВЫЕ ЗАДАЧИ =====================
async def reminder_task(bot: Bot):
    """Раз в сутки напоминает юзерам, которые не заходили 3+ дня."""
    while True:
        try:
            uids = db.users_to_remind(3)
            for uid in uids:
                try:
                    await bot.send_message(uid, "💤 " + random.choice(REMINDERS))
                except Exception:
                    pass
        except Exception as e:
            log.warning("reminder error: %s", e)
        await asyncio.sleep(86400)   # раз в сутки

async def backup_task():
    while True:
        await asyncio.sleep(86400)
        try:
            db.backup_db()
            log.info("Ежедневный бэкап создан")
        except Exception as e:
            log.warning("backup error: %s", e)

# ===================== ЗАПУСК =====================
async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Старт"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="profile", description="Профиль"),
        BotCommand(command="stats", description="Моя статистика"),
        BotCommand(command="quiz", description="Викторина"),
        BotCommand(command="daily", description="Дейли"),
        BotCommand(command="sprint", description="Спринт 60с"),
        BotCommand(command="hardcore", description="Хардкор"),
        BotCommand(command="marathon", description="Марафон 50"),
        BotCommand(command="duel", description="Дуэль"),
        BotCommand(command="top", description="Топы"),
        BotCommand(command="season", description="Сезон"),
        BotCommand(command="goal", description="Цель"),
        BotCommand(command="ref", description="Реф-ссылка"),
        BotCommand(command="reftop", description="Топ рефереров"),
        BotCommand(command="fav", description="Избранное"),
        BotCommand(command="history", description="История"),
        BotCommand(command="silent", description="Тихий режим"),
        BotCommand(command="random", description="Случайное отчество"),
        BotCommand(command="fact", description="Факт"),
    ])

async def main():
    db.init_db()
    db.backup_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await set_commands(bot)
    asyncio.create_task(reminder_task(bot))
    asyncio.create_task(backup_task())
    log.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановлено")
