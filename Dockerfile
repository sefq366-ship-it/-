# ... ваши зависимости ...

# Создаём папку для данных и даём полные права ВСЕМ (для теста)
RUN mkdir -p /app/data && chmod -R 777 /app/data

# Копируем код
COPY . .

# Создаём пользователя и даём ему права на /app
RUN useradd -m botuser && chown -R botuser:botuser /app

# Переменная окружения, чтобы бот знал, куда писать
ENV DB_PATH=/app/data/sales.db

# Переключаемся на пользователя (папка data уже с правами 777)
USER botuser

CMD ["python", "bot.py"]
