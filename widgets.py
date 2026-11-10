# widgets.py
import json
import logging
import aiohttp
import asyncio
from aiogram import Dispatcher
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)

# HTML-шаблоны остаются без изменений
CALC_WIDGET_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: -apple-system, sans-serif; padding: 12px; margin: 0; background: transparent; color: var(--tg-theme-text-color, #fff); }
  input[type="number"] { width: 100%; padding: 8px; border-radius: 8px; border: 1px solid #444; background: #2a2a2a; color: #fff; font-size: 16px; box-sizing: border-box; margin-bottom: 8px; }
  .radio { display: flex; gap: 16px; margin: 8px 0; }
  button { width: 100%; padding: 10px; border-radius: 8px; border: none; background: #2481cc; color: white; font-size: 16px; font-weight: 600; cursor: pointer; }
  #result { margin-top: 10px; font-size: 14px; line-height: 1.4; }
  .error { color: #e74c3c; }
</style>
</head>
<body>
  <input type="number" id="amount" placeholder="Введите сумму" step="any">
  <div class="radio">
    <label><input type="radio" name="dir" value="gram_to_stars" checked> GRAM → Stars</label>
    <label><input type="radio" name="dir" value="stars_to_gram"> Stars → GRAM</label>
  </div>
  <button onclick="calc()">Рассчитать</button>
  <div id="result"></div>
  <script>
    function calc() {
      const amount = parseFloat(document.getElementById('amount').value);
      const dir = document.querySelector('input[name="dir"]:checked').value;
      if (!amount || amount <= 0) {
        document.getElementById('result').innerHTML = '<span class="error">Введите число > 0</span>';
        return;
      }
      TelegramWidget.request(JSON.stringify({ action: 'calc', amount: amount, dir: dir }));
    }
    TelegramWidget.onResult = function(data) {
      try {
        const res = JSON.parse(data.result);
        document.getElementById('result').innerHTML = res.error 
          ? '<span class="error">' + res.error + '</span>' 
          : '<b>' + res.text + '</b>';
      } catch(e) {
        document.getElementById('result').innerHTML = '<span class="error">Ошибка</span>';
      }
    };
  </script>
</body>
</html>
"""

DONATE_WIDGET_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: -apple-system, sans-serif; padding: 12px; margin: 0; background: transparent; color: var(--tg-theme-text-color, #fff); }
  .quick { display: flex; gap: 8px; margin-bottom: 10px; }
  .quick button { flex: 1; padding: 8px; border-radius: 8px; border: 1px solid #444; background: #2a2a2a; color: #fff; font-size: 14px; cursor: pointer; }
  input[type="number"] { width: 100%; padding: 8px; border-radius: 8px; border: 1px solid #444; background: #2a2a2a; color: #fff; font-size: 16px; box-sizing: border-box; margin-bottom: 8px; }
  button.main { width: 100%; padding: 10px; border-radius: 8px; border: none; background: #e74c3c; color: white; font-size: 16px; font-weight: 600; cursor: pointer; }
  #status { margin-top: 10px; font-size: 14px; color: #2ecc71; }
  .error { color: #e74c3c; }
</style>
</head>
<body>
  <div class="quick">
    <button onclick="setAmt(50)">50 ⭐</button>
    <button onclick="setAmt(100)">100 ⭐</button>
    <button onclick="setAmt(250)">250 ⭐</button>
    <button onclick="setAmt(500)">500 ⭐</button>
  </div>
  <input type="number" id="stars" placeholder="Своя сумма (⭐)" step="1" min="1">
  <button class="main" onclick="donate()">Поддержать ❤️</button>
  <div id="status"></div>
  <script>
    function setAmt(v) { document.getElementById('stars').value = v; }
    function donate() {
      const stars = parseInt(document.getElementById('stars').value);
      if (!stars || stars < 1) {
        document.getElementById('status').innerHTML = '<span class="error">Введите число ≥ 1</span>';
        return;
      }
      TelegramWidget.request(JSON.stringify({ action: 'donate', stars: stars }));
      document.getElementById('status').innerHTML = 'Счёт отправлен в чат…';
    }
    TelegramWidget.onResult = function(data) {
      try {
        const res = JSON.parse(data.result);
        document.getElementById('status').innerHTML = res.error 
          ? '<span class="error">' + res.error + '</span>' 
          : res.text;
      } catch(e) {}
    };
  </script>
</body>
</html>
"""

# --- Прямые HTTP-запросы к Telegram ---

async def send_widget_raw(bot_token: str, chat_id: int, html: str, allow_queries: bool = True, width: int = 320, height: int = 260):
    """Отправляет виджет через прямой запрос к api.telegram.org (Bot API 10.4)."""
    url = f"https://api.telegram.org/bot{bot_token}/sendWidget"
    payload = {
        "chat_id": chat_id,
        "html": html,
        "allow_queries": allow_queries,
        "width": width,
        "height": height
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            data = await resp.json()
            if not data.get("ok"):
                logger.error(f"sendWidget failed: {data}")
                return None
            return data.get("result")

async def answer_widget_query_raw(bot_token: str, widget_query_id: str, data: str):
    """Отвечает на запрос от виджета через прямой запрос."""
    url = f"https://api.telegram.org/bot{bot_token}/answerWidgetQuery"
    payload = {
        "widget_query_id": widget_query_id,
        "data": data
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            result = await resp.json()
            if not result.get("ok"):
                logger.error(f"answerWidgetQuery failed: {result}")
            return result

# --- Регистрация хендлеров для виджетов ---

def setup_widgets(dp: Dispatcher, bot, bot_token: str):
    """Регистрирует команды для отправки виджетов и обработчик ответов."""

    @dp.message(lambda m: m.text in ["🔄 Калькулятор", "🔄 Calculator"])
    async def calc_widget_handler(message: Message):
        from bot import logger as bot_logger
        bot_logger.info(f"calc_widget_handler triggered for user {message.from_user.id}")
        result = await send_widget_raw(bot_token, message.chat.id, CALC_WIDGET_HTML, width=320, height=260)
        if result is None:
            await message.answer("❌ Не удалось открыть калькулятор. Попробуйте позже.")

    @dp.message(lambda m: m.text in ["💎 Поддержать", "💎 Donate"])
    async def donate_widget_handler(message: Message):
        from bot import logger as bot_logger
        bot_logger.info(f"donate_widget_handler triggered for user {message.from_user.id}")
        result = await send_widget_raw(bot_token, message.chat.id, DONATE_WIDGET_HTML, width=320, height=240)
        if result is None:
            await message.answer("❌ Не удалось открыть донат-виджет. Попробуйте позже.")

    # Обработчик для widget_query (если используется polling, нужно ловить updates вручную)
    # В aiogram 3.31 нет widget_query, поэтому мы будем ловить его через сырые updates.
    # Это делается в main() через bot.get_updates() или webhook.
    # Здесь мы просто регистрируем функцию, которую вызовет ваш цикл polling.
    
    async def handle_widget_query(widget_query: dict):
        """Обрабатывает widget_query, пришедший в update."""
        from bot import get_user_star_rate, get_gram_price
        from aiogram.types import LabeledPrice
        
        query_id = widget_query.get("id")
        user_id = widget_query.get("from", {}).get("id")
        raw_data = widget_query.get("data", "{}")
        
        try:
            data = json.loads(raw_data)
        except Exception:
            await answer_widget_query_raw(bot_token, query_id, json.dumps({"error": "Некорректный запрос"}))
            return
        
        action = data.get("action")
        
        if action == "calc":
            try:
                amount = float(data.get("amount", 0))
                direction = data.get("dir", "gram_to_stars")
                if amount <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                await answer_widget_query_raw(bot_token, query_id, json.dumps({"error": "Введите число > 0"}))
                return
            
            star_rate = await get_user_star_rate(user_id)
            gram_price = await get_gram_price()
            
            if direction == "gram_to_stars":
                stars = (amount * gram_price) / (star_rate * 0.8)
                text = f"💎 {amount:.2f} GRAM ≈ ⭐ {stars:.0f} Stars\n📊 Ваш курс: 1⭐ = ${star_rate:.6f}"
            else:
                gram = (amount * 0.8 * star_rate) / gram_price
                usd = gram * gram_price
                text = f"⭐ {amount:.0f} Stars ≈ 💎 {gram:.4f} GRAM\n🪙 ${usd:.2f}"
            
            await answer_widget_query_raw(bot_token, query_id, json.dumps({"text": text}))
            return
        
        if action == "donate":
            try:
                stars = int(data.get("stars", 0))
                if stars < 1:
                    raise ValueError
            except (ValueError, TypeError):
                await answer_widget_query_raw(bot_token, query_id, json.dumps({"error": "Введите число ≥ 1"}))
                return
            
            try:
                await bot.send_invoice(
                    chat_id=user_id,
                    title="Поддержка бота",
                    description=f"Донат {stars} звёзд",
                    payload=f"donate_{user_id}_{stars}",
                    currency="XTR",
                    prices=[LabeledPrice(label="Донат", amount=stars)],
                    provider_token=""
                )
                await answer_widget_query_raw(bot_token, query_id, json.dumps({"text": "✅ Счёт отправлен в чат!"}))
            except Exception as e:
                logger.error(f"donate invoice: {e}")
                await answer_widget_query_raw(bot_token, query_id, json.dumps({"error": "Не удалось создать счёт"}))
            return
        
        await answer_widget_query_raw(bot_token, query_id, json.dumps({"error": "Неизвестное действие"}))
    
    # Возвращаем функцию, чтобы её можно было вызывать из polling-цикла в main()
    return handle_widget_query
