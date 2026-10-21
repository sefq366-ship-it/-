# messages.py

MESSAGES = {
    "ru": {
        # ========== СТАРТ И ГЛАВНОЕ МЕНЮ ==========
        "start": (
            "👋 <b>Добро пожаловать, {name}!</b>\n\n"
            "💎 <b>Gram2Profit</b> — профессиональный учёт прибыли от NFT‑сделок.\n\n"
            "✅ Все операции в GRAM\n"
            "✅ Калькулятор Stars↔GRAM с вашим курсом\n"
            "✅ Отложенные покупки и завершение сделок\n"
            "✅ Уведомления о курсе GRAM\n"
            "✅ Расширенная статистика по коллекциям и месяцам\n"
            "✅ Возможность делиться сделками в чатах (@Stars2ProfitBot)\n"
            "✅ Реферальная программа\n\n"
            "Автор: @sefq1337\n\n"
            "Используйте кнопки меню."
        ),
        "main_add_deal": "📊 Добавить сделку",
        "main_pending_buy": "📥 Отложенная покупка",
        "main_complete_deal": "📤 Завершить сделку",
        "main_history": "📋 История",
        "main_stats": "📊 Статистика",
        "main_calculator": "🔄 Калькулятор",
        "main_settings": "⚙️ Настройки",
        "main_timers": "⏰ Таймеры",
        "main_donate": "💎 Поддержать",
        "main_referrals": "👥 Рефералы",
        "lang_btn": "🌐 🇷🇺 Русский",
        "lang_changed": "✅ Язык изменён на Русский",

        # ========== ДОБАВЛЕНИЕ СДЕЛКИ ==========
        "enter_buy_amount": "💎 Введите сумму покупки в GRAM:",
        "enter_collection": "Введите название коллекции:",
        "enter_nft_link": "🔗 <b>Введите ссылку на NFT (обязательно):</b>\nПример: https://t.me/nft/DurovsCap-4074",
        "link_required": "❌ Ссылка обязательна. Введите ссылку на NFT.",
        "enter_sell_amount": "💎 Введите сумму продажи в GRAM:",
        "select_commission": "⚙️ Комиссия на вывод. Ваша ставка: {royalty} GRAM\nВыберите:",
        "commission_custom": "✏️ Другая сумма",
        "commission_zero": "🚫 Без комиссии",
        "cancel": "❌ Отмена",
        "cancelled": "❌ Отменено",
        "sale_saved": (
            "✅ <b>Сделка сохранена!</b>\n"
            "📁 {category}\n"
            "💎 {buy} → {sell} GRAM\n"
            "⚙️ Комиссия: {royalty} GRAM\n"
            "💰 Прибыль: {profit} GRAM (${usd})"
        ),
        "nft_found": "🎁 <b>{gift}</b>\n{attrs}",
        "nft_not_found": "🎁 <b>{gift}</b>\n<i>Характеристики не найдены</i>",

        # ========== ОТЛОЖЕННАЯ ПОКУПКА ==========
        "pending_saved": "✅ Отложенная покупка сохранена!\n📁 {category}\n💎 {amount} GRAM",
        "no_pending": "📤 Нет незавершённых сделок.",
        "select_pending": "📤 <b>Выберите сделку для завершения:</b>\n\n",
        "confirm_complete": (
            "📤 <b>Завершить сделку?</b>\n\n"
            "🆔 #{id} | 📁 {category}\n"
            "💎 Куплено за: {buy} GRAM\n"
            "🔗 {link}\n"
            "⚙️ Роялти: {royalty} GRAM\n"
            "📅 {date}\n\n"
            "<i>После подтверждения потребуется ввести сумму продажи и комиссию.</i>"
        ),
        "complete_yes": "✅ Да, завершить",
        "deal_completed": (
            "✅ <b>Сделка завершена!</b>\n"
            "📁 {category}\n"
            "💎 {buy} → {sell} GRAM\n"
            "💰 Прибыль: {profit} GRAM\n"
            "🔗 {link}"
        ),
        "delete_pending_confirm": "Удалить эту отложенную покупку?",
        "delete_yes": "✅ Да, удалить",

        # ========== ИСТОРИЯ ==========
        "history_empty": "📋 История пуста.",
        "history_title": "📋 <b>История сделок</b> (стр. {page}/{total}):\n\n",
        "history_prev": "⬅️ Назад",
        "history_next": "➡️ Далее",
        "edit_btn": "✏️ #{id}",
        "delete_btn": "🗑 #{id}",
        "delete_confirm": "Уверены, что хотите удалить эту сделку?",
        "deleted": "✅ Сделка удалена.",
        "updated": "✅ Сделка обновлена!",

        # ========== РЕДАКТИРОВАНИЕ ==========
        "edit_buy_amount": "Введите новую сумму покупки (было {old} GRAM):",
        "edit_category": "Введите новое название коллекции:",
        "edit_nft_link": "Введите новую ссылку на NFT:",
        "edit_sell_amount": "Введите новую сумму продажи:",
        "edit_commission": "Новая комиссия:",

        # ========== СТАТИСТИКА ==========
        "stats_no_deals": "📊 Сделок пока нет.",
        "stats_title": "💎 <b>СТАТИСТИКА NFT</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n",
        "stats_total": "💰 <b>Общая прибыль:</b> {total} GRAM (${usd})",
        "stats_deals": "📊 <b>Сделок:</b> {deals}",
        "stats_avg": "📈 <b>Средняя прибыль:</b> {avg} GRAM",
        "stats_max": "🟢 <b>Максимальная:</b> {max} GRAM",
        "stats_min": "🔴 <b>Минимальная:</b> {min} GRAM",
        "stats_volume": "💵 <b>Объём покупок:</b> {buy} GRAM\n💵 <b>Объём продаж:</b> {sell} GRAM",
        "stats_star_rate": "⭐ <b>Курс Stars:</b> ${rate}",
        "stats_royalty": "⚙️ <b>Роялти по умолчанию:</b> {royalty} GRAM",
        "stats_goal": "🎯 <b>Цель:</b> {goal} GRAM\n{bar}",
        "stats_gram_price": "💎 Курс GRAM: ${price}",
        "stats_collections_btn": "📁 По коллекциям",
        "stats_months_btn": "📅 По месяцам",
        "stats_top_btn": "🏆 Топ сделок",
        "stats_cumulative_btn": "📈 Накопительная",
        "stats_chart_btn": "📉 График прибыли",
        "stats_close_btn": "⬅️ Закрыть",
        "stats_back_btn": "⬅️ Назад",
        "collections_title": "📁 <b>Прибыль по коллекциям:</b>\n\n",
        "months_title": "📅 <b>Прибыль по месяцам</b>",
        "top_title": "🏆 <b>Топ-10 сделок по прибыли:</b>\n\n",
        "cumulative_title": "📈 <b>Накопительная прибыль</b>",
        "chart_title": "📉 <b>График прибыли по последним сделкам</b>",

        # ========== КАЛЬКУЛЯТОР ==========
        "calc_title": "Выберите направление конвертации:",
        "calc_stars_to_gram": "⭐ STARS → 💎 GRAM",
        "calc_gram_to_stars": "💎 GRAM → ⭐ STARS",
        "calc_result_stars": "⭐ {amount} STARS → 💎 <b>{gram} GRAM</b> (${usd})",
        "calc_result_gram": "💎 {amount} GRAM → ⭐ <b>{stars} STARS</b> (для выставления)",

        # ========== НАСТРОЙКИ ==========
        "settings_title": "⚙️ <b>Настройки</b>\n\n",
        "settings_commission": "• Комиссия на вывод: <b>{royalty} GRAM</b>",
        "settings_goal": "• Цель по прибыли: <b>{goal} GRAM</b>",
        "settings_star_rate": "• Курс обмена Stars: <b>${rate}</b>",
        "settings_change_alert": "• Уведомление о скачках курса: <b>{status}</b> (порог {percent}%)",
        "settings_change_commission": "✏️ Изменить комиссию",
        "settings_set_goal": "🎯 Установить цель",
        "settings_star_rate_btn": "⭐ Мой курс Stars",
        "settings_change_alert_btn": "📉 Резкие скачки курса",
        "settings_alert_btn": "🔔 Уведомление о цене",
        "settings_reports_btn": "📊 Уведомления о заработке",
        "settings_close": "❌ Закрыть",
        "enter_royalty": "Введите новую комиссию на вывод в GRAM:",
        "enter_goal": "Введите цель по прибыли в GRAM:",
        "enter_star_rate": "Введите ваш курс обмена Stars (например, 0.012):",
        "enter_change_percent": "Введите порог изменения курса в процентах (например, 5):",
        "enter_alert_price": "Введите целевую цену GRAM в USD:",

        # ========== ЦЕЛЬ ==========
        "goal_achieved": (
            "🎉 <b>Поздравляем!</b>\n\n"
            "Вы достигли цели по прибыли в <b>{goal} GRAM</b>!\n"
            "Текущая прибыль: <b>{total} GRAM</b>\n\n"
            "Хотите установить новую цель?"
        ),
        "goal_set_new": "🎯 Установить новую цель",
        "goal_later": "⏳ Позже",

        # ========== УВЕДОМЛЕНИЯ ==========
        "alert_set": "🔔 Уведомление установлено на цену ${price}",
        "alert_triggered": "🔔 Курс GRAM достиг ${price}! Ваша цель: ${target}",
        "price_change": (
            "📉 Курс GRAM резко изменился: {direction} на {pct}% за сутки!\n"
            "Текущая цена: ${price}, было ${old_price}"
        ),
        "change_alert_on": "✅ Уведомления о скачках включены (порог {percent}%)",
        "change_alert_off": "Уведомления о скачках отключены",

        # ========== ДОНАТЫ ==========
        "donate_menu": (
            "💎 <b>Поддержать развитие бота</b>\n\n"
            "Вы можете поддержать автора двумя способами:\n\n"
            "⭐ <b>Звёздами</b> — введите любую сумму, и бот отправит счёт\n"
            "🏆 <b>Топ донатеров</b> — рейтинг самых щедрых\n"
            "💎 <b>TON-кошелёк</b> — прямая отправка GRAM"
        ),
        "donate_stars": "⭐ Поддержать звёздами",
        "donate_top": "🏆 Топ-10 донатеров",
        "donate_wallet": "💎 Кошелёк TON",
        "donate_enter_amount": "⭐ Введите сумму в звёздах (например, 100):",
        "donate_thanks": "❤️ <b>Спасибо за поддержку!</b>\n\nВы отправили {amount} ⭐",
        "donate_top_empty": "🏆 Пока нет донатов. Будьте первым!",
        "donate_top_title": "🏆 <b>Топ-10 донатеров:</b>\n",
        "donate_text": (
            "💎 <b>Поддержите развитие бота!</b>\n\n"
            "Отправьте любую сумму GRAM на кошелёк:\n\n"
            "<code>onlysefq1337.ton</code>\n\n"
            "📱 Если у вас Tonkeeper:\n"
            "<code>ton://transfer/onlysefq1337.ton</code>\n\n"
            "Нажмите на адрес, чтобы скопировать его.\n\n"
            "Спасибо за поддержку! ❤️"
        ),
        "donate_admin_notify": (
            "💎 <b>Новый донат!</b>\n\n"
            "👤 От: {user}\n"
            "⭐ Сумма: {amount} звёзд\n"
            "📅 {date}"
        ),

        # ========== ТАЙМЕРЫ ==========
        "timers_title": "⏰ <b>Мои таймеры</b>",
        "timers_empty": "У вас нет активных таймеров.\nДобавьте напоминание о минте NFT, разлоке звёзд или перевыставлении.",
        "timer_add_mint": "🎁 Напомнить о минте NFT",
        "timer_add_unlock": "⭐ Напомнить о разлоке звёзд",
        "timer_add_relist": "🔄 Напомнить о перевыставлении",
        "timer_enter_nft": "🔗 Введите ссылку на NFT (например, https://t.me/nft/DurovsCap-4074):",
        "timer_enter_days": "📅 Через сколько дней напомнить? (введите число):",
        "timer_invalid_link": "❌ Неверная ссылка. Пример: https://t.me/nft/DurovsCap-4074",
        "timer_saved": "✅ Таймер установлен! Бот напомнит через {days} дн.",
        "timer_mint_notify": (
            "⏰ <b>Напоминание о минте!</b>\n\n"
            "🎁 {link}\n\n"
            "🕐 Время минта наступило!\n"
            "Успейте заминтить NFT."
        ),
        "timer_unlock_notify": (
            "⏰ <b>Напоминание о разлоке звёзд!</b>\n\n"
            "⭐ Время разлока наступило!\n"
            "Вы можете вывести звёзды."
        ),
        "timer_relist_notify": (
            "⏰ <b>Напоминание о перевыставлении!</b>\n\n"
            "🔄 {link}\n\n"
            "🕐 Срок перевыставления наступил!\n"
            "Не забудьте перевыставить NFT."
        ),
        "timer_mint_item": "🎁 Минт: {link} — осталось {days} дн.",
        "timer_unlock_item": "⭐ Разлок звёзд — осталось {days} дн.",
        "timer_relist_item": "🔄 Перевыставить: {link} — осталось {days} дн.",

        # ========== ОТЧЁТЫ О ЗАРАБОТКЕ ==========
        "reports_title": "📊 <b>Уведомления о заработке</b>\n\nВыберите, какие отчёты хотите получать:",
        "reports_weekly": "📅 Еженедельный отчёт",
        "reports_monthly": "📆 Ежемесячный отчёт",
        "reports_yearly": "📈 Годовой отчёт",
        "earnings_report": (
            "📊 <b>Отчёт о заработке</b>\n\n"
            "За период ({period}) вы заработали:\n"
            "💰 <b>{total} GRAM</b>\n\n"
            "Продолжайте в том же духе!"
        ),

        # ========== РЕФЕРАЛЫ ==========
        "referrals_title": "👥 <b>Реферальная программа</b>\n\n",
        "referrals_link": "🔗 Ваша ссылка:\n<code>{link}</code>\n\n",
        "referrals_stats": (
            "📊 <b>Статистика:</b>\n"
            "• Приглашено: {invited}\n"
            "• Активных: {active}\n"
            "• Очки репутации: {points}\n\n"
        ),
        "referrals_level": "🏆 Ваш уровень: {level}\n{next_level}",
        "referrals_top_title": "\n🏆 <b>Топ-10 рефереров:</b>\n",
        "referrals_share": "📤 Поделиться ссылкой",
        "referrals_empty": "У вас пока нет приглашённых.\nПоделитесь ссылкой с друзьями!",
        "referrals_points_per": "За каждого активного реферала — 10 очков.",
        "referrals_level_bronze": "🥉 Бронза",
        "referrals_level_silver": "🥈 Серебро",
        "referrals_level_gold": "🥇 Золото",
        "referrals_level_platinum": "💎 Платина",
        "referrals_next_level": "До следующего уровня: {points} очков",

        # ========== ОШИБКИ И СИСТЕМА ==========
        "error_generic": "❌ Внутренняя ошибка. Попробуйте позже.",
        "error_positive_number": "❌ Введите положительное число",
        "error_not_found": "Сделка не найдена",
        "error_invalid_number": "❌ Введите корректное число",

        # ========== АДМИН-ПАНЕЛЬ ==========
        "admin_no_access": "⛔ Доступ запрещён",
        "admin_title": (
            "⚙️ <b>Админ-панель Gram2Profit</b>\n\n"
            "👥 Пользователей: {users}\n"
            "📊 Всего сделок: {deals}\n"
            "📅 Сделок сегодня: {today}\n"
            "💰 Общая прибыль: {profit} GRAM (${usd})\n"
            "👑 Администраторов: {admins}\n"
        ),
        "admin_stats_btn": "📊 Статистика",
        "admin_users_btn": "👥 Пользователи",
        "admin_inline_stats_btn": "📈 Инлайн-статистика",
        "admin_logs_btn": "📋 Логи действий",
        "admin_errors_btn": "🚨 Проверить ошибки",
        "admin_broadcast_btn": "📢 Рассылка",
        "admin_add_admin_btn": "➕ Добавить админа",
        "admin_remove_admin_btn": "➖ Удалить админа",
        "admin_list_admins_btn": "📋 Список админов",
        "admin_backup_btn": "💾 Бэкап БД",
        "admin_close_btn": "⬅️ Закрыть",
        "broadcast_enter": "📢 Введите текст для рассылки:",
        "broadcast_sent": "✅ Рассылка завершена: {success}/{total}",
        "admin_add_prompt": "Введите Telegram ID нового администратора:",
        "admin_remove_prompt": "Введите Telegram ID для удаления:",
        "admin_added": "✅ Администратор {id} добавлен.",
        "admin_removed": "✅ Администратор {id} удалён.",
        "admin_list_title": "👑 <b>Администраторы:</b>\n",
        "admin_users_title": "👥 <b>Последние пользователи:</b>\n\n",
        "admin_no_admins": "Список пуст.",

        # ========== РАСШИРЕННАЯ СТАТИСТИКА АДМИНА ==========
        "adm_stats_title": "📊 <b>Расширенная статистика</b>\n\n",
        "adm_stats_users": "━━━ 👥 ПОЛЬЗОВАТЕЛИ ━━━\n",
        "adm_stats_deals": "━━━ 📈 СДЕЛКИ ━━━\n",
        "adm_stats_profit": "━━━ 💰 ПРИБЫЛЬ ━━━\n",
        "adm_stats_collections": "━━━ 📁 ТОП-5 КОЛЛЕКЦИЙ ━━━\n",
        "adm_stats_top_users": "━━━ 👑 ТОП-5 ЮЗЕРОВ ━━━\n",
        "adm_stats_inline": "━━━ 📱 ИНЛАЙН-РЕЖИМ ━━━\n",
        "adm_stats_by_days_btn": "📅 По дням",
        "adm_stats_by_hours_btn": "📈 По часам",
        "adm_stats_back_btn": "⬅️ Назад",

        # ========== ИНЛАЙН-СТАТИСТИКА ==========
        "inline_stats_title": "📈 <b>Инлайн-статистика</b>\n\n",
        "inline_stats_users": "👥 Уникальных пользователей: {users}",
        "inline_stats_total": "📤 Всего отправок: {total}",
        "inline_stats_top": "\n🏆 <b>Топ-10 активных:</b>\n",
        "inline_stats_recent": "\n📅 <b>Последние 10 отправок:</b>\n",
        "inline_stats_empty": "Инлайн-режимом пока никто не пользовался.",
        "inline_stats_item_top": "{i}. {name} — {count} отправок",
        "inline_stats_item_recent": "• {name} — сделка #{deal} — {date}",

        # ========== ЛОГИ ДЕЙСТВИЙ ==========
        "logs_title": "📋 <b>Логи действий</b> (последние 20)\n\n",
        "logs_empty": "Логов пока нет.",
        "logs_clear_btn": "🗑 Очистить лог",
        "logs_back_btn": "⬅️ Назад",
        "logs_filter_btn": "📅 Фильтр по дате",
        "logs_filter_24h": "За 24 часа",
        "logs_filter_7d": "За 7 дней",
        "logs_filter_all": "За всё время",

        # ========== ОШИБКИ (админ) ==========
        "errors_title": "🚨 <b>Лог ошибок</b>\n\n",
        "errors_stats": (
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 Всего ошибок: {total}\n"
            "🆕 Новых: {new}\n"
            "📅 За последние 24ч: {last24}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
        ),
        "errors_empty": "✅ Ошибок нет. Всё работает стабильно.",
        "errors_copy_btn": "📋 Скопировать логи",
        "errors_download_btn": "📤 Скачать файл",
        "errors_clear_btn": "🗑 Очистить лог",
        "errors_filter_btn": "📅 Фильтр по дате",
        "errors_back_btn": "⬅️ Назад",
        "errors_copy_message": "📋 <b>Логи для копирования</b>\n\nНажмите на текст ниже — он скопируется.\n\n<code>{logs}</code>",
        "errors_cleared": "✅ Лог ошибок очищен.",
        "errors_startup_title": "🚨 <b>Ошибки при прошлом запуске</b>\n\nНайдено: {count} ошибок за последние 24 часа.\n\n",
        "errors_startup_hint": "Откройте админ-панель → «🚨 Проверить ошибки» для подробностей.",

        # ========== БЭКАП ==========
        "backup_title": "💾 <b>Бэкап БД</b>\n\n",
        "backup_info": "📅 Дата: {date}\n📁 Файл: {file}\n📊 Размер: {size}\n\n",
        "backup_contents": (
            "📈 <b>Содержимое:</b>\n"
            "• Пользователей: {users}\n"
            "• Сделок: {deals}\n"
            "• Донатов: {donations}\n"
        ),
        "backup_created": "✅ Бэкап создан и отправлен.",
        "backup_error": "❌ Ошибка создания бэкапа.",

        # ========== ИНЛАЙН-РЕЖИМ ==========
        "inline_title": "🎁 {gift} · Сделка #{id}",
        "inline_loading": "⏳ {gift} · Сделка #{id}\nПодсчёт данных...",
        "inline_open_bot": "Открыть бота",
        "inline_open_nft": "Открыть NFT",
        "inline_no_deals": "🔍 Нет сделок",
        "inline_not_found": "Ничего не найдено",
    },

    "en": {
        # ========== START AND MAIN MENU ==========
        "start": (
            "👋 <b>Welcome, {name}!</b>\n\n"
            "💎 <b>Gram2Profit</b> — professional NFT profit tracker.\n\n"
            "✅ All operations in GRAM\n"
            "✅ Stars↔GRAM calculator with your rate\n"
            "✅ Pending buys and deal completion\n"
            "✅ GRAM price alerts\n"
            "✅ Advanced statistics by collections and months\n"
            "✅ Share deals in chats (@Stars2ProfitBot)\n"
            "✅ Referral program\n\n"
            "Author: @sefq1337\n\n"
            "Use the menu buttons."
        ),
        "main_add_deal": "📊 Add Deal",
        "main_pending_buy": "📥 Pending Buy",
        "main_complete_deal": "📤 Complete Deal",
        "main_history": "📋 History",
        "main_stats": "📊 Statistics",
        "main_calculator": "🔄 Calculator",
        "main_settings": "⚙️ Settings",
        "main_timers": "⏰ Timers",
        "main_donate": "💎 Donate",
        "main_referrals": "👥 Referrals",
        "lang_btn": "🌐 🇬🇧 English",
        "lang_changed": "✅ Language changed to English",

        # ========== ADD DEAL ==========
        "enter_buy_amount": "💎 Enter buy amount in GRAM:",
        "enter_collection": "Enter collection name:",
        "enter_nft_link": "🔗 <b>Enter NFT link (required):</b>\nExample: https://t.me/nft/DurovsCap-4074",
        "link_required": "❌ Link is required. Enter NFT link.",
        "enter_sell_amount": "💎 Enter sell amount in GRAM:",
        "select_commission": "⚙️ Withdrawal commission. Your rate: {royalty} GRAM\nChoose:",
        "commission_custom": "✏️ Custom amount",
        "commission_zero": "🚫 No commission",
        "cancel": "❌ Cancel",
        "cancelled": "❌ Cancelled",
        "sale_saved": (
            "✅ <b>Deal saved!</b>\n"
            "📁 {category}\n"
            "💎 {buy} → {sell} GRAM\n"
            "⚙️ Commission: {royalty} GRAM\n"
            "💰 Profit: {profit} GRAM (${usd})"
        ),
        "nft_found": "🎁 <b>{gift}</b>\n{attrs}",
        "nft_not_found": "🎁 <b>{gift}</b>\n<i>Attributes not found</i>",

        # ========== PENDING BUY ==========
        "pending_saved": "✅ Pending buy saved!\n📁 {category}\n💎 {amount} GRAM",
        "no_pending": "📤 No pending deals.",
        "select_pending": "📤 <b>Select a deal to complete:</b>\n\n",
        "confirm_complete": (
            "📤 <b>Complete this deal?</b>\n\n"
            "🆔 #{id} | 📁 {category}\n"
            "💎 Bought for: {buy} GRAM\n"
            "🔗 {link}\n"
            "⚙️ Royalty: {royalty} GRAM\n"
            "📅 {date}\n\n"
            "<i>After confirmation, you will need to enter the sell amount and commission.</i>"
        ),
        "complete_yes": "✅ Yes, complete",
        "deal_completed": (
            "✅ <b>Deal completed!</b>\n"
            "📁 {category}\n"
            "💎 {buy} → {sell} GRAM\n"
            "💰 Profit: {profit} GRAM\n"
            "🔗 {link}"
        ),
        "delete_pending_confirm": "Delete this pending buy?",
        "delete_yes": "✅ Yes, delete",

        # ========== HISTORY ==========
        "history_empty": "📋 History is empty.",
        "history_title": "📋 <b>Deal History</b> (page {page}/{total}):\n\n",
        "history_prev": "⬅️ Previous",
        "history_next": "➡️ Next",
        "edit_btn": "✏️ #{id}",
        "delete_btn": "🗑 #{id}",
        "delete_confirm": "Are you sure you want to delete this deal?",
        "deleted": "✅ Deal deleted.",
        "updated": "✅ Deal updated!",

        # ========== EDIT ==========
        "edit_buy_amount": "Enter new buy amount (was {old} GRAM):",
        "edit_category": "Enter new collection name:",
        "edit_nft_link": "Enter new NFT link:",
        "edit_sell_amount": "Enter new sell amount:",
        "edit_commission": "New commission:",

        # ========== STATS ==========
        "stats_no_deals": "📊 No deals yet.",
        "stats_title": "💎 <b>NFT STATISTICS</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n",
        "stats_total": "💰 <b>Total Profit:</b> {total} GRAM (${usd})",
        "stats_deals": "📊 <b>Deals:</b> {deals}",
        "stats_avg": "📈 <b>Average Profit:</b> {avg} GRAM",
        "stats_max": "🟢 <b>Maximum:</b> {max} GRAM",
        "stats_min": "🔴 <b>Minimum:</b> {min} GRAM",
        "stats_volume": "💵 <b>Buy Volume:</b> {buy} GRAM\n💵 <b>Sell Volume:</b> {sell} GRAM",
        "stats_star_rate": "⭐ <b>Stars Rate:</b> ${rate}",
        "stats_royalty": "⚙️ <b>Default Royalty:</b> {royalty} GRAM",
        "stats_goal": "🎯 <b>Goal:</b> {goal} GRAM\n{bar}",
        "stats_gram_price": "💎 GRAM Price: ${price}",
        "stats_collections_btn": "📁 By Collections",
        "stats_months_btn": "📅 By Months",
        "stats_top_btn": "🏆 Top Deals",
        "stats_cumulative_btn": "📈 Cumulative",
        "stats_chart_btn": "📉 Profit Chart",
        "stats_close_btn": "⬅️ Close",
        "stats_back_btn": "⬅️ Back",
        "collections_title": "📁 <b>Profit by Collections:</b>\n\n",
        "months_title": "📅 <b>Profit by Months</b>",
        "top_title": "🏆 <b>Top-10 Deals by Profit:</b>\n\n",
        "cumulative_title": "📈 <b>Cumulative Profit</b>",
        "chart_title": "📉 <b>Profit Chart (Last 20 Deals)</b>",

        # ========== CALCULATOR ==========
        "calc_title": "Choose conversion direction:",
        "calc_stars_to_gram": "⭐ STARS → 💎 GRAM",
        "calc_gram_to_stars": "💎 GRAM → ⭐ STARS",
        "calc_result_stars": "⭐ {amount} STARS → 💎 <b>{gram} GRAM</b> (${usd})",
        "calc_result_gram": "💎 {amount} GRAM → ⭐ <b>{stars} STARS</b> (to list)",

        # ========== SETTINGS ==========
        "settings_title": "⚙️ <b>Settings</b>\n\n",
        "settings_commission": "• Withdrawal Commission: <b>{royalty} GRAM</b>",
        "settings_goal": "• Profit Goal: <b>{goal} GRAM</b>",
        "settings_star_rate": "• Stars Exchange Rate: <b>${rate}</b>",
        "settings_change_alert": "• Price Change Alert: <b>{status}</b> (threshold {percent}%)",
        "settings_change_commission": "✏️ Change Commission",
        "settings_set_goal": "🎯 Set Goal",
        "settings_star_rate_btn": "⭐ My Stars Rate",
        "settings_change_alert_btn": "📉 Price Change Alerts",
        "settings_alert_btn": "🔔 Price Alert",
        "settings_reports_btn": "📊 Earnings Notifications",
        "settings_close": "❌ Close",
        "enter_royalty": "Enter new withdrawal commission in GRAM:",
        "enter_goal": "Enter profit goal in GRAM:",
        "enter_star_rate": "Enter your Stars rate (e.g., 0.012):",
        "enter_change_percent": "Enter price change threshold in percent (e.g., 5):",
        "enter_alert_price": "Enter target GRAM price in USD:",

        # ========== GOAL ==========
        "goal_achieved": (
            "🎉 <b>Congratulations!</b>\n\n"
            "You have reached your profit goal of <b>{goal} GRAM</b>!\n"
            "Current profit: <b>{total} GRAM</b>\n\n"
            "Want to set a new goal?"
        ),
        "goal_set_new": "🎯 Set New Goal",
        "goal_later": "⏳ Later",

        # ========== ALERTS ==========
        "alert_set": "🔔 Alert set for price ${price}",
        "alert_triggered": "🔔 GRAM price reached ${price}! Your target: ${target}",
        "price_change": (
            "📉 GRAM price changed sharply: {direction} by {pct}% in 24h!\n"
            "Current price: ${price}, was ${old_price}"
        ),
        "change_alert_on": "✅ Price change alerts enabled (threshold {percent}%)",
        "change_alert_off": "Price change alerts disabled",

        # ========== DONATIONS ==========
        "donate_menu": (
            "💎 <b>Support the bot</b>\n\n"
            "You can support the author in two ways:\n\n"
            "⭐ <b>Stars</b> — enter any amount and the bot will send an invoice\n"
            "🏆 <b>Top Donators</b> — the most generous users\n"
            "💎 <b>TON wallet</b> — direct GRAM transfer"
        ),
        "donate_stars": "⭐ Donate Stars",
        "donate_top": "🏆 Top-10 Donators",
        "donate_wallet": "💎 TON Wallet",
        "donate_enter_amount": "⭐ Enter amount in Stars (e.g., 100):",
        "donate_thanks": "❤️ <b>Thank you for your support!</b>\n\nYou sent {amount} ⭐",
        "donate_top_empty": "🏆 No donations yet. Be the first!",
        "donate_top_title": "🏆 <b>Top-10 Donators:</b>\n",
        "donate_text": (
            "💎 <b>Support the bot!</b>\n\n"
            "Send any amount of GRAM to the wallet:\n\n"
            "<code>onlysefq1337.ton</code>\n\n"
            "📱 If you have Tonkeeper:\n"
            "<code>ton://transfer/onlysefq1337.ton</code>\n\n"
            "Tap the address to copy it.\n\n"
            "Thank you for your support! ❤️"
        ),
        "donate_admin_notify": (
            "💎 <b>New donation!</b>\n\n"
            "👤 From: {user}\n"
            "⭐ Amount: {amount} stars\n"
            "📅 {date}"
        ),

        # ========== TIMERS ==========
        "timers_title": "⏰ <b>My Timers</b>",
        "timers_empty": "You have no active timers.\nAdd a reminder for NFT mint, Stars unlock, or relisting.",
        "timer_add_mint": "🎁 Remind about NFT mint",
        "timer_add_unlock": "⭐ Remind about Stars unlock",
        "timer_add_relist": "🔄 Remind about relisting",
        "timer_enter_nft": "🔗 Enter NFT link (e.g., https://t.me/nft/DurovsCap-4074):",
        "timer_enter_days": "📅 In how many days to remind? (enter number):",
        "timer_invalid_link": "❌ Invalid link. Example: https://t.me/nft/DurovsCap-4074",
        "timer_saved": "✅ Timer set! Bot will remind in {days} days.",
        "timer_mint_notify": (
            "⏰ <b>Mint reminder!</b>\n\n"
            "🎁 {link}\n\n"
            "🕐 Mint time has come!\n"
            "Hurry up to mint the NFT."
        ),
        "timer_unlock_notify": (
            "⏰ <b>Stars unlock reminder!</b>\n\n"
            "⭐ Unlock time has come!\n"
            "You can withdraw your Stars."
        ),
        "timer_relist_notify": (
            "⏰ <b>Relisting reminder!</b>\n\n"
            "🔄 {link}\n\n"
            "🕐 Relisting time has come!\n"
            "Don't forget to relist the NFT."
        ),
        "timer_mint_item": "🎁 Mint: {link} — {days} days left",
        "timer_unlock_item": "⭐ Stars unlock — {days} days left",
        "timer_relist_item": "🔄 Relist: {link} — {days} days left",

        # ========== EARNINGS REPORTS ==========
        "reports_title": "📊 <b>Earnings Notifications</b>\n\nChoose which reports you want to receive:",
        "reports_weekly": "📅 Weekly report",
        "reports_monthly": "📆 Monthly report",
        "reports_yearly": "📈 Yearly report",
        "earnings_report": (
            "📊 <b>Earnings Report</b>\n\n"
            "For the period ({period}) you earned:\n"
            "💰 <b>{total} GRAM</b>\n\n"
            "Keep it up!"
        ),

        # ========== REFERRALS ==========
        "referrals_title": "👥 <b>Referral Program</b>\n\n",
        "referrals_link": "🔗 Your link:\n<code>{link}</code>\n\n",
        "referrals_stats": (
            "📊 <b>Statistics:</b>\n"
            "• Invited: {invited}\n"
            "• Active: {active}\n"
            "• Reputation points: {points}\n\n"
        ),
        "referrals_level": "🏆 Your level: {level}\n{next_level}",
        "referrals_top_title": "\n🏆 <b>Top-10 Referrers:</b>\n",
        "referrals_share": "📤 Share link",
        "referrals_empty": "You have no invited users yet.\nShare the link with friends!",
        "referrals_points_per": "For each active referral — 10 points.",
        "referrals_level_bronze": "🥉 Bronze",
        "referrals_level_silver": "🥈 Silver",
        "referrals_level_gold": "🥇 Gold",
        "referrals_level_platinum": "💎 Platinum",
        "referrals_next_level": "To next level: {points} points",

        # ========== ERRORS ==========
        "error_generic": "❌ Internal error. Please try again later.",
        "error_positive_number": "❌ Enter a positive number",
        "error_not_found": "Deal not found",
        "error_invalid_number": "❌ Enter a valid number",

        # ========== ADMIN PANEL ==========
        "admin_no_access": "⛔ Access denied",
        "admin_title": (
            "⚙️ <b>Admin Panel Gram2Profit</b>\n\n"
            "👥 Users: {users}\n"
            "📊 Total deals: {deals}\n"
            "📅 Deals today: {today}\n"
            "💰 Total profit: {profit} GRAM (${usd})\n"
            "👑 Admins: {admins}\n"
        ),
        "admin_stats_btn": "📊 Statistics",
        "admin_users_btn": "👥 Users",
        "admin_inline_stats_btn": "📈 Inline Stats",
        "admin_logs_btn": "📋 Action Logs",
        "admin_errors_btn": "🚨 Check Errors",
        "admin_broadcast_btn": "📢 Broadcast",
        "admin_add_admin_btn": "➕ Add Admin",
        "admin_remove_admin_btn": "➖ Remove Admin",
        "admin_list_admins_btn": "📋 Admin List",
        "admin_backup_btn": "💾 Backup DB",
        "admin_close_btn": "⬅️ Close",
        "broadcast_enter": "📢 Enter text for broadcast:",
        "broadcast_sent": "✅ Broadcast completed: {success}/{total}",
        "admin_add_prompt": "Enter new admin Telegram ID:",
        "admin_remove_prompt": "Enter Telegram ID to remove:",
        "admin_added": "✅ Admin {id} added.",
        "admin_removed": "✅ Admin {id} removed.",
        "admin_list_title": "👑 <b>Admins:</b>\n",
        "admin_users_title": "👥 <b>Recent users:</b>\n\n",
        "admin_no_admins": "List is empty.",

        # ========== ADMIN EXTENDED STATS ==========
        "adm_stats_title": "📊 <b>Extended Statistics</b>\n\n",
        "adm_stats_users": "━━━ 👥 USERS ━━━\n",
        "adm_stats_deals": "━━━ 📈 DEALS ━━━\n",
        "adm_stats_profit": "━━━ 💰 PROFIT ━━━\n",
        "adm_stats_collections": "━━━ 📁 TOP-5 COLLECTIONS ━━━\n",
        "adm_stats_top_users": "━━━ 👑 TOP-5 USERS ━━━\n",
        "adm_stats_inline": "━━━ 📱 INLINE MODE ━━━\n",
        "adm_stats_by_days_btn": "📅 By Days",
        "adm_stats_by_hours_btn": "📈 By Hours",
        "adm_stats_back_btn": "⬅️ Back",

        # ========== INLINE STATS ==========
        "inline_stats_title": "📈 <b>Inline Statistics</b>\n\n",
        "inline_stats_users": "👥 Unique users: {users}",
        "inline_stats_total": "📤 Total sends: {total}",
        "inline_stats_top": "\n🏆 <b>Top-10 Active:</b>\n",
        "inline_stats_recent": "\n📅 <b>Last 10 sends:</b>\n",
        "inline_stats_empty": "Nobody has used inline mode yet.",
        "inline_stats_item_top": "{i}. {name} — {count} sends",
        "inline_stats_item_recent": "• {name} — deal #{deal} — {date}",

        # ========== ACTION LOGS ==========
        "logs_title": "📋 <b>Action Logs</b> (last 20)\n\n",
        "logs_empty": "No logs yet.",
        "logs_clear_btn": "🗑 Clear log",
        "logs_back_btn": "⬅️ Back",
        "logs_filter_btn": "📅 Filter by date",
        "logs_filter_24h": "Last 24h",
        "logs_filter_7d": "Last 7 days",
        "logs_filter_all": "All time",

        # ========== ERRORS (admin) ==========
        "errors_title": "🚨 <b>Error Log</b>\n\n",
        "errors_stats": (
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 Total errors: {total}\n"
            "🆕 New: {new}\n"
            "📅 Last 24h: {last24}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
        ),
        "errors_empty": "✅ No errors. Everything is stable.",
        "errors_copy_btn": "📋 Copy logs",
        "errors_download_btn": "📤 Download file",
        "errors_clear_btn": "🗑 Clear log",
        "errors_filter_btn": "📅 Filter by date",
        "errors_back_btn": "⬅️ Back",
        "errors_copy_message": "📋 <b>Logs to copy</b>\n\nTap the text below — it will be copied.\n\n<code>{logs}</code>",
        "errors_cleared": "✅ Error log cleared.",
        "errors_startup_title": "🚨 <b>Errors from previous run</b>\n\nFound: {count} errors in the last 24 hours.\n\n",
        "errors_startup_hint": "Open admin panel → «🚨 Check Errors» for details.",

        # ========== BACKUP ==========
        "backup_title": "💾 <b>DB Backup</b>\n\n",
        "backup_info": "📅 Date: {date}\n📁 File: {file}\n📊 Size: {size}\n\n",
        "backup_contents": (
            "📈 <b>Contents:</b>\n"
            "• Users: {users}\n"
            "• Deals: {deals}\n"
            "• Donations: {donations}\n"
        ),
        "backup_created": "✅ Backup created and sent.",
        "backup_error": "❌ Backup creation error.",

        # ========== INLINE MODE ==========
        "inline_title": "🎁 {gift} · Deal #{id}",
        "inline_loading": "⏳ {gift} · Deal #{id}\nCalculating...",
        "inline_open_bot": "Open bot",
        "inline_open_nft": "Open NFT",
        "inline_no_deals": "🔍 No deals",
        "inline_not_found": "Nothing found",
    }
}