import json
import logging
import aiohttp
import asyncio

from aiogram import Dispatcher
from aiogram.types import Message, LabeledPrice, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


# ============================================================
# ОБЩИЕ СТИЛИ
# ============================================================

COMMON_STYLE = """
* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
html { width: 100%; background: #11131b; }
body { width: 100%; padding: 10px; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: radial-gradient(circle at top left, #242b45 0%, transparent 55%), linear-gradient(145deg, #11131b, #191d2b); }
button { font-family: inherit; border: none; outline: none; cursor: pointer; user-select: none; -webkit-user-select: none; }
button:active { transform: scale(0.97); filter: brightness(1.2); }
.container { width: 100%; max-width: 420px; margin: 0 auto; }
.header { display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 10px; }
.header-icon { font-size: 21px; }
.header-title { font-size: 17px; font-weight: 800; letter-spacing: .2px; }
.subtitle { color: #858da5; font-size: 11px; text-align: center; margin-top: -5px; margin-bottom: 10px; }
.card { background: rgba(255,255,255,.055); border: 1px solid rgba(255,255,255,.08); border-radius: 13px; padding: 10px; margin-bottom: 10px; }
.display { min-height: 53px; display: flex; justify-content: flex-end; align-items: center; overflow: hidden; padding: 8px 12px; margin-bottom: 5px; border-radius: 11px; background: rgba(0,0,0,.28); border: 1px solid rgba(255,255,255,.07); font-size: 25px; font-weight: 800; letter-spacing: .5px; overflow-wrap: anywhere; }
.placeholder { color: #656d83; font-size: 14px; font-weight: 500; }
.hint { color: #858da5; font-size: 10px; text-align: right; margin-bottom: 9px; padding-right: 5px; }
.row { display: flex; gap: 6px; margin-bottom: 6px; }
.btn { flex: 1; min-width: 0; height: 39px; display: flex; align-items: center; justify-content: center; border-radius: 9px; color: #ffffff; background: rgba(255,255,255,.09); font-size: 17px; font-weight: 700; }
.btn.secondary { background: rgba(255,255,255,.06); color: #aab2c8; }
.btn.primary { background: linear-gradient(135deg, #3987ff, #6659ed); color: white; font-size: 13px; }
.result { display: none; margin-top: 8px; padding: 10px; border-radius: 10px; background: rgba(56,130,255,.12); border: 1px solid rgba(56,130,255,.2); text-align: center; overflow-wrap: anywhere; }
.result.show { display: block; }
.result-label { color: #9ca9c7; font-size: 11px; margin-bottom: 4px; }
.result-value { color: #ffffff; font-size: 17px; font-weight: 800; }
.footer { margin-top: 8px; color: #626b80; text-align: center; font-size: 10px; }
"""


# ============================================================
# 1. КАЛЬКУЛЯТОР
# ============================================================

CALC_WIDGET_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>""" + COMMON_STYLE + """
.directions { display: flex; gap: 6px; margin-bottom: 9px; }
.direction { flex: 1; height: 34px; border-radius: 9px; background: rgba(255,255,255,.07); color: #929bb2; font-size: 11px; font-weight: 800; }
.direction.active { background: linear-gradient(135deg, #3987ff, #6659ed); color: white; }
</style>
</head>
<body>
<div class="container">
    <div class="header"><span class="header-icon">💎</span><span class="header-title">GRAM Calculator</span></div>
    <div class="subtitle">Быстрый расчёт стоимости</div>
    <div class="card">
        <div class="display" id="display"><span class="placeholder">Введите сумму</span></div>
        <div class="hint" id="hint">Введите сумму в Stars</div>
        <div class="directions">
            <button class="direction active" id="dir1" onclick="setDir('stars_to_gram')">⭐ STARS → 💎</button>
            <button class="direction" id="dir2" onclick="setDir('gram_to_stars')">💎 GRAM → ⭐</button>
        </div>
        <div class="row"><button class="btn" onclick="press('1')">1</button><button class="btn" onclick="press('2')">2</button><button class="btn" onclick="press('3')">3</button></div>
        <div class="row"><button class="btn" onclick="press('4')">4</button><button class="btn" onclick="press('5')">5</button><button class="btn" onclick="press('6')">6</button></div>
        <div class="row"><button class="btn" onclick="press('7')">7</button><button class="btn" onclick="press('8')">8</button><button class="btn" onclick="press('9')">9</button></div>
        <div class="row"><button class="btn secondary" onclick="backspace()">⌫</button><button class="btn" onclick="press('0')">0</button><button class="btn" onclick="press('.')">.</button></div>
        <div class="row"><button class="btn primary" onclick="calculate()" style="flex: 3;">РАССЧИТАТЬ</button></div>
        <div class="result" id="result"><div class="result-label" id="resultLabel">Результат</div><div class="result-value" id="resultValue"></div></div>
    </div>
</div>
<script>
var current = ""; var direction = "stars_to_gram"; var busy = false;
function updateDisplay() { var el = document.getElementById("display"); if (!current) { el.innerHTML = '<span class="placeholder">Введите сумму</span>'; } else { el.textContent = current; } }
function press(n) { if (current.length >= 12) return; if (n === '.') { if (current.includes('.')) return; if (current === "") { current = "0."; updateDisplay(); return; } } current += n; updateDisplay(); }
function backspace() { current = current.slice(0, -1); updateDisplay(); }
function setDir(d) { direction = d; document.getElementById("dir1").classList.toggle("active", d === "stars_to_gram"); document.getElementById("dir2").classList.toggle("active", d === "gram_to_stars"); document.getElementById("hint").innerText = d === "stars_to_gram" ? "Введите сумму в Stars" : "Введите сумму в GRAM"; document.getElementById("result").classList.remove("show"); }
function showResult(label, value, error) { document.getElementById("resultLabel").textContent = label; document.getElementById("resultValue").textContent = value; document.getElementById("resultValue").style.color = error ? "#ff7777" : "#ffffff"; document.getElementById("result").classList.add("show"); }
function calculate() {
    if (busy) return; var amount = Number(current);
    if (!Number.isFinite(amount) || amount <= 0) { showResult("Ошибка", "Введите сумму", true); return; }
    busy = true; showResult("Расчёт", "Подождите...", false);
    TelegramWidget.request(JSON.stringify({ action: "calc", amount: amount, dir: direction }))
    .then(function(answer) { var r = JSON.parse(answer.result); if (r.error) { showResult("Ошибка", r.error, true); } else { showResult(r.label, r.value, false); } })
    .catch(function() { showResult("Ошибка", "Сбой сети", true); })
    .finally(function() { busy = false; });
}
updateDisplay();
</script>
</body></html>
"""


# ============================================================
# 2. СТАТИСТИКА
# ============================================================

STATS_WIDGET_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>""" + COMMON_STYLE + """
.stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
.stat-item { background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.08); border-radius: 10px; padding: 10px; text-align: center; }
.stat-label { color: #858da5; font-size: 10px; margin-bottom: 4px; text-transform: uppercase; }
.stat-value { color: #ffffff; font-size: 16px; font-weight: 800; }
.profit-green { color: #7ee5a0; } .profit-red { color: #ff7777; }
.top-deal { background: rgba(46, 204, 113, 0.1); border: 1px solid rgba(46, 204, 113, 0.2); border-radius: 10px; padding: 10px; margin-bottom: 10px; position: relative; overflow: hidden; }
.top-deal-bg { position: absolute; right: -20px; top: -20px; font-size: 80px; opacity: 0.1; transform: rotate(15deg); }
.top-deal-title { font-size: 12px; color: #7ee5a0; font-weight: 700; margin-bottom: 4px; }
.top-deal-name { font-size: 15px; font-weight: 800; color: #fff; margin-bottom: 2px; }
.top-deal-profit { font-size: 18px; font-weight: 900; color: #fff; }
.css-chart { display: flex; align-items: flex-end; height: 60px; gap: 4px; margin-top: 10px; padding-bottom: 5px; border-bottom: 1px solid rgba(255,255,255,0.1); }
.chart-bar { flex: 1; background: linear-gradient(to top, #3987ff, #6659ed); border-radius: 3px 3px 0 0; min-height: 5px; }
.chart-label { text-align: center; color: #858da5; font-size: 9px; margin-top: 4px; }
.period-buttons { display: flex; gap: 6px; margin-bottom: 10px; }
.period-btn { flex: 1; height: 32px; border-radius: 8px; background: rgba(255,255,255,.07); color: #929bb2; font-size: 12px; font-weight: 700; }
.period-btn.active { background: linear-gradient(135deg, #3987ff, #6659ed); color: white; }
</style>
</head>
<body>
<div class="container">
    <div class="header"><span class="header-icon">📊</span><span class="header-title">Статистика</span></div>
    <div class="subtitle">Твои результаты и прогресс</div>
    <div class="stats-grid">
        <div class="stat-item"><div class="stat-label">Сделок</div><div class="stat-value">{{TOTAL_DEALS}}</div></div>
        <div class="stat-item"><div class="stat-label">Winrate</div><div class="stat-value">{{WINRATE}}</div></div>
        <div class="stat-item"><div class="stat-label">Прибыль GRAM</div><div class="stat-value {{PROFIT_CLASS}}">{{PROFIT_GRAM}}</div></div>
        <div class="stat-item"><div class="stat-label">Прибыль USD</div><div class="stat-value {{PROFIT_CLASS}}">{{PROFIT_USD}}</div></div>
    </div>
    <div class="period-buttons">
        <button class="period-btn {{PERIOD_7D}}" onclick="TelegramWidget.request(JSON.stringify({action:'stats_period', period:'7d'}))">7 дней</button>
        <button class="period-btn {{PERIOD_30D}}" onclick="TelegramWidget.request(JSON.stringify({action:'stats_period', period:'30d'}))">30 дней</button>
        <button class="period-btn {{PERIOD_ALL}}" onclick="TelegramWidget.request(JSON.stringify({action:'stats_period', period:'all'}))">Всё</button>
    </div>
    {{TOP_DEAL_HTML}}
    {{TOP_COLLECTIONS_HTML}}
    <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 5px;">
            <span style="font-size: 11px; color: #fff; font-weight: 700;">Прибыль за период</span>
            <span style="font-size: 11px; color: #7ee5a0;">{{CHART_TOTAL}}</span>
        </div>
        <div class="css-chart">{{CHART_BARS}}</div>
        <div class="chart-label">{{CHART_DATES}}</div>
    </div>
</div>
</body></html>
"""


# ============================================================
# 3. ДОНАТ
# ============================================================

DONATE_WIDGET_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>""" + COMMON_STYLE + """
.tab-buttons { display: flex; gap: 6px; margin-bottom: 10px; }
.tab-btn { flex: 1; height: 34px; border-radius: 9px; background: rgba(255,255,255,.07); color: #929bb2; font-size: 12px; font-weight: 800; }
.tab-btn.active { background: linear-gradient(135deg, #ff9d43, #ff5d72); color: white; }
.donate-button { width: 100%; height: 43px; border-radius: 10px; background: linear-gradient(135deg, #ff9d43, #ff5d72); color: white; font-size: 14px; font-weight: 900; margin-top: 10px; }
.result-box { display: none; margin-top: 10px; padding: 12px; border-radius: 10px; background: rgba(56,130,255,.12); border: 1px solid rgba(56,130,255,.2); text-align: center; }
.result-box.show { display: block; }
.pay-link { display: block; width: 100%; padding: 12px; margin-top: 8px; background: linear-gradient(135deg, #3987ff, #6659ed); color: white; text-decoration: none; border-radius: 8px; font-weight: 800; font-size: 14px; text-align: center; }
.back-btn { background: transparent; color: #858da5; font-size: 12px; margin-top: 10px; text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
    <div class="header"><span class="header-icon">❤️</span><span class="header-title">Поддержать проект</span></div>
    <div class="subtitle">Выбери способ оплаты</div>
    <div class="card">
        <div class="tab-buttons">
            <button class="tab-btn active" id="tab-stars" onclick="setType('stars')">⭐ Stars</button>
            <button class="tab-btn" id="tab-gram" onclick="setType('gram')">💎 GRAM</button>
        </div>
        <div class="display" id="display"><span class="placeholder">Введите сумму</span></div>
        <div id="keyboard">
            <div class="row"><button class="btn" onclick="press('1')">1</button><button class="btn" onclick="press('2')">2</button><button class="btn" onclick="press('3')">3</button><button class="btn secondary" onclick="backspace()">⌫</button></div>
            <div class="row"><button class="btn" onclick="press('4')">4</button><button class="btn" onclick="press('5')">5</button><button class="btn" onclick="press('6')">6</button><button class="btn secondary" onclick="clearAll()">C</button></div>
            <div class="row"><button class="btn" onclick="press('7')">7</button><button class="btn" onclick="press('8')">8</button><button class="btn" onclick="press('9')">9</button><button class="btn" onclick="press('.')">.</button></div>
            <div class="row"><button class="btn" onclick="press('0')" style="flex: 2;">0</button></div>
            <button class="donate-button" id="mainDonateBtn" onclick="donate()">❤️ ПОДДЕРЖАТЬ</button>
        </div>
        <div class="result-box" id="resultBox">
            <div id="resultText" style="font-size: 13px; margin-bottom: 10px; color: #ffffff; font-weight: 700;"></div>
            <div id="gramPayContainer"></div>
            <button class="back-btn" onclick="resetWidget()">⬅️ Назад к вводу</button>
        </div>
    </div>
    <div style="margin-top: 10px;">
        <button class="btn" style="width:100%; font-size:13px; height:34px;" onclick="TelegramWidget.request(JSON.stringify({action:'donate_top'}))">🏆 Топ донатеров</button>
    </div>
</div>
<script>
var current = ""; var type = "stars"; var busy = false;
function setType(t) { type = t; document.getElementById("tab-stars").classList.toggle("active", t === "stars"); document.getElementById("tab-gram").classList.toggle("active", t === "gram"); resetWidget(); }
function updateDisplay() { var el = document.getElementById("display"); if (!current) { el.innerHTML = '<span class="placeholder">Введите сумму</span>'; } else { el.textContent = current + (type === "stars" ? " ⭐" : " GRAM"); } }
function press(n) { 
    if (current.length >= 10) return; 
    if (n === '.') { 
        if (current.includes('.')) return; 
        if (current === "") { current = "0."; updateDisplay(); return; } 
    } 
    if (type === "stars" && n === '.') return; 
    current += n; updateDisplay(); 
}
function backspace() { current = current.slice(0, -1); updateDisplay(); }
function clearAll() { current = ""; updateDisplay(); document.getElementById("resultBox").classList.remove("show"); }
function resetWidget() { current = ""; updateDisplay(); document.getElementById("keyboard").style.display = "block"; document.getElementById("resultBox").classList.remove("show"); document.getElementById("gramPayContainer").innerHTML = ""; document.getElementById("mainDonateBtn").textContent = "❤️ ПОДДЕРЖАТЬ"; }
function donate() {
    if (busy) return; var amount = Number(current); if (!Number.isFinite(amount) || amount <= 0) { alert("Введите корректную сумму"); return; }
    if (type === "gram") {
        var amountStr = current;
        var url = "https://t.me/sendgrams?to=@sefq1337&amount=" + encodeURIComponent(amountStr);
        document.getElementById("keyboard").style.display = "none"; 
        document.getElementById("resultBox").classList.add("show"); 
        document.getElementById("resultText").innerHTML = "💎 К оплате: <b>" + amountStr + " GRAM</b>";
        document.getElementById("gramPayContainer").innerHTML = '<a href="' + url + '" target="_blank" class="pay-link">🚀 Перейти к оплате ' + amountStr + ' GRAM</a>';
    } else {
        busy = true; document.getElementById("mainDonateBtn").textContent = "ОТПРАВКА...";
        TelegramWidget.request(JSON.stringify({ action: "donate", type: "stars", amount: amount })).then(function(answer) {
            var r = JSON.parse(answer.result); document.getElementById("keyboard").style.display = "none"; document.getElementById("resultBox").classList.add("show"); document.getElementById("resultText").innerHTML = r.text || "✅ Счёт Stars отправлен в чат!";
        }).catch(function() { alert("Ошибка сети"); }).finally(function() { busy = false; document.getElementById("mainDonateBtn").textContent = "❤️ ПОДДЕРЖАТЬ"; });
    }
}
</script>
</body></html>
"""


# ============================================================
# 4. НАСТРОЙКИ
# ============================================================

SETTINGS_WIDGET_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>""" + COMMON_STYLE + """
.setting-item { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
.setting-label { font-size: 14px; font-weight: 700; color: #fff; }
.setting-desc { font-size: 11px; color: #858da5; margin-top: 2px; }
.setting-btn { padding: 6px 12px; border-radius: 8px; background: rgba(56,130,255,.15); color: #8cb4ff; font-size: 12px; font-weight: 700; }
.input-area { display: none; margin-top: 10px; }
.input-area.show { display: block; }
</style>
</head>
<body>
<div class="container">
    <div class="header"><span class="header-icon">⚙️</span><span class="header-title">Настройки</span></div>
    <div class="subtitle">Персонализация бота</div>
    <div class="card" id="mainSettings">
        <div class="setting-item">
            <div><div class="setting-label">Комиссия</div><div class="setting-desc">Текущая: {{ROYALTY}} GRAM</div></div>
            <button class="setting-btn" onclick="startEdit('royalty', '{{ROYALTY}}')">Изменить</button>
        </div>
        <div class="setting-item">
            <div><div class="setting-label">Цель по профиту</div><div class="setting-desc">Текущая: {{GOAL}} GRAM</div></div>
            <button class="setting-btn" onclick="startEdit('goal', '{{GOAL}}')">Изменить</button>
        </div>
        <div class="setting-item" style="border-bottom: none;">
            <div><div class="setting-label">Курс Stars</div><div class="setting-desc">Текущий: ${{STAR_RATE}}</div></div>
            <button class="setting-btn" onclick="startEdit('star_rate', '{{STAR_RATE}}')">Изменить</button>
        </div>
    </div>
    <div class="card input-area" id="editArea">
        <div style="font-size: 14px; margin-bottom: 8px; font-weight: 700;" id="editLabel">Введите значение</div>
        <div class="display" id="display"><span class="placeholder">0</span></div>
        <div class="row"><button class="btn" onclick="press('1')">1</button><button class="btn" onclick="press('2')">2</button><button class="btn" onclick="press('3')">3</button></div>
        <div class="row"><button class="btn" onclick="press('4')">4</button><button class="btn" onclick="press('5')">5</button><button class="btn" onclick="press('6')">6</button></div>
        <div class="row"><button class="btn" onclick="press('7')">7</button><button class="btn" onclick="press('8')">8</button><button class="btn" onclick="press('9')">9</button></div>
        <div class="row"><button class="btn secondary" onclick="backspace()">⌫</button><button class="btn" onclick="press('0')">0</button><button class="btn" onclick="press('.')">.</button><button class="btn secondary" onclick="clearAll()">C</button></div>
        <div class="row" style="margin-top: 10px;">
            <button class="btn" style="background: rgba(255,255,255,.1);" onclick="cancelEdit()">Отмена</button>
            <button class="btn primary" style="flex: 2;" onclick="saveEdit()">СОХРАНИТЬ</button>
        </div>
    </div>
</div>
<script>
var current = ""; var editKey = "";
function press(n) { if (current.length >= 12) return; if (n === '.') { if (current.includes('.')) return; if (current === "") { current = "0."; updateDisplay(); return; } } current += n; updateDisplay(); }
function backspace() { current = current.slice(0, -1); updateDisplay(); }
function clearAll() { current = ""; updateDisplay(); }
function updateDisplay() { var el = document.getElementById("display"); if (!current) { el.innerHTML = '<span class="placeholder">0</span>'; } else { el.textContent = current; } }
function startEdit(key, val) { 
    editKey = key; 
    current = ""; 
    document.getElementById("mainSettings").style.display = "none"; 
    document.getElementById("editArea").classList.add("show"); 
    document.getElementById("editLabel").innerText = "Изменить: " + key; 
    updateDisplay(); 
}
function cancelEdit() { document.getElementById("mainSettings").style.display = "block"; document.getElementById("editArea").classList.remove("show"); }
function saveEdit() {
    var val = Number(current);
    if (!Number.isFinite(val) || val < 0) { alert("Неверное значение"); return; }
    TelegramWidget.request(JSON.stringify({ action: "save_setting", key: editKey, value: val })).then(function(answer) {
        var r = JSON.parse(answer.result);
        if (r.error) { alert(r.error); } else { 
            alert("✅ Сохранено! Открой настройки заново."); 
            cancelEdit(); 
        }
    }).catch(function() { alert("Ошибка сети"); });
}
</script>
</body></html>
"""


# ============================================================
# ОТПРАВКА WIDGET
# ============================================================

async def send_widget_raw(bot_token: str, chat_id: int, html: str, allow_queries: bool = True):
    url = f"https://api.telegram.org/bot{bot_token}/sendWidget"
    payload = {"chat_id": chat_id, "html": html, "allow_queries": allow_queries}
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.error("sendWidget failed: %s", data)
                    return None
                return data.get("result")
    except Exception:
        logger.exception("Widget sending error")
        return None


# ============================================================
# ОТВЕТ НА WIDGET QUERY
# ============================================================

async def answer_widget_query_raw(bot_token: str, widget_query_id: str, data: str):
    url = f"https://api.telegram.org/bot{bot_token}/answerWidgetQuery"
    payload = {"widget_query_id": widget_query_id, "data": data}
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
    except Exception:
        return None


# ============================================================
# ОБРАБОТКА ЗАПРОСОВ
# ============================================================

async def handle_widget_query_raw(widget_query: dict, bot, bot_token: str, get_user_star_rate=None, get_gram_price=None, get_db=None):
    query_id = widget_query.get("id")
    user_id = widget_query.get("from", {}).get("id")
    if not query_id or not user_id: return

    async def respond(result):
        await answer_widget_query_raw(bot_token, query_id, json.dumps(result, ensure_ascii=False))

    try: data = json.loads(widget_query.get("data", "{}"))
    except: 
        await respond({"error": "Некорректный запрос"})
        return

    action = data.get("action")

    # --- КАЛЬКУЛЯТОР ---
    if action == "calc":
        if get_user_star_rate is None or get_gram_price is None:
            await respond({"error": "Сервис временно недоступен"}); return
        try:
            amount = float(data.get("amount", 0))
            direction = data.get("dir", "stars_to_gram")
            star_rate = float(await get_user_star_rate(user_id))
            gram_price = float(await get_gram_price())
            if direction == "gram_to_stars":
                stars = (amount * gram_price) / (star_rate * 0.8)
                await respond({"label": f"💎 {amount:.4f} GRAM ≈", "value": f"⭐ {stars:.0f} Stars"})
            else:
                gram = (amount * 0.8 * star_rate) / gram_price
                await respond({"label": f"⭐ {amount:.0f} Stars ≈", "value": f"💎 {gram:.4f} GRAM (${gram * gram_price:.2f})"})
        except: await respond({"error": "Ошибка расчёта"})
        return

    # --- ДОНАТ ---
    if action == "donate" and data.get("type") == "stars":
        amount = float(data.get("amount", 0))
        if amount <= 0: await respond({"error": "Неверная сумма"}); return
        try:
            stars = int(amount)
            await bot.send_invoice(chat_id=user_id, title="⭐ Поддержка", description=f"Донат {stars} звёзд", payload=f"donate_{user_id}_{stars}", currency="XTR", prices=[LabeledPrice(label="Донат", amount=stars)], provider_token="")
            await respond({"text": "✅ Счёт Stars отправлен в чат!"})
        except: await respond({"error": "Ошибка оплаты"})
        return

    # --- ТОП ДОНАТОВ ---
    if action == "donate_top":
        try:
            conn = await get_db()
            cur = await conn.execute("SELECT d.user_id, SUM(d.amount) as total, u.username, u.first_name FROM donations d LEFT JOIN users u ON u.user_id = d.user_id GROUP BY d.user_id ORDER BY total DESC LIMIT 10")
            rows = await cur.fetchall()
            text = "🏆 <b>Топ донатеров (Stars)</b>\n\n"
            if not rows: text += "Пока пусто. Стань первым!"
            else:
                for i, (uid, total, uname, fname) in enumerate(rows, 1):
                    emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                    name = f"@{uname}" if uname else (fname or f"ID {uid}")
                    text += f"{emoji} {name} — {total} ⭐\n"
            await bot.send_message(user_id, text)
            await respond({"text": "Топ отправлен"})
        except: await respond({"error": "Ошибка"})
        return

    # --- СОХРАНЕНИЕ НАСТРОЕК ---
    if action == "save_setting":
        key = data.get("key")
        value = float(data.get("value", 0))
        if get_db is None: await respond({"error": "Сервис недоступен"}); return
        try:
            from bot import save_user_royalty, save_user_star_rate, get_user_royalty, get_user_star_rate
            
            if key == "royalty": await save_user_royalty(user_id, value)
            elif key == "star_rate": await save_user_star_rate(user_id, value)
            elif key == "goal":
                conn = await get_db()
                await conn.execute("INSERT OR REPLACE INTO profit_goals (user_id, goal_gram, created_at, notified) VALUES (?,?,datetime('now'),0)", (user_id, value))
                await conn.commit()
            
            await respond({"text": "✅ Сохранено! Сейчас пришлю обновленный виджет..."})
            await asyncio.sleep(0.5)
            
            royalty = await get_user_royalty(user_id)
            star_rate = await get_user_star_rate(user_id)
            conn = await get_db()
            cur = await conn.execute("SELECT goal_gram FROM profit_goals WHERE user_id=?", (user_id,))
            goal_row = await cur.fetchone()
            goal = goal_row[0] if goal_row else 0
            
            html = SETTINGS_WIDGET_HTML
            html = html.replace("{{ROYALTY}}", f"{royalty:.2f}")
            html = html.replace("{{GOAL}}", f"{goal:.2f}" if goal else "Не задана")
            html = html.replace("{{STAR_RATE}}", f"{star_rate:.6f}")
            
            await send_widget_raw(bot_token, user_id, html)
            
        except Exception as e:
            logger.exception(f"Save setting error: {e}")
            await respond({"error": "Ошибка сохранения"})
        return

    await respond({"error": "Неизвестное действие"})
