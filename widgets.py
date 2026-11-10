# widgets.py
import json
import logging
from aiogram import Dispatcher
from aiogram.types import WidgetQuery

logger = logging.getLogger(__name__)

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


def setup_widgets(dp: Dispatcher, bot):
    """Регистрирует обработчик запросов от виджетов."""

    @dp.widget_query()
    async def handle_widget_query(query: WidgetQuery):
        from bot import get_user_star_rate, get_gram_price
        from aiogram.types import LabeledPrice

        try:
            data = json.loads(query.data or "{}")
        except Exception:
            await query.answer(data=json.dumps({"error": "Некорректный запрос"}))
            return

        action = data.get("action")
        user_id = query.from_user.id

        if action == "calc":
            try:
                amount = float(data.get("amount", 0))
                direction = data.get("dir", "gram_to_stars")
                if amount <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                await query.answer(data=json.dumps({"error": "Введите число > 0"}))
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

            await query.answer(data=json.dumps({"text": text}))
            return

        if action == "donate":
            try:
                stars = int(data.get("stars", 0))
                if stars < 1:
                    raise ValueError
            except (ValueError, TypeError):
                await query.answer(data=json.dumps({"error": "Введите число ≥ 1"}))
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
                await query.answer(data=json.dumps({"text": "✅ Счёт отправлен в чат!"}))
            except Exception as e:
                logger.error(f"donate invoice: {e}")
                await query.answer(data=json.dumps({"error": "Не удалось создать счёт"}))
            return

        await query.answer(data=json.dumps({"error": "Неизвестное действие"}))
