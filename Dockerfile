# Берем официальный образ Python (slim версия, чтобы не тащить лишнего)
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# 1. Устанавливаем системные зависимости для Chromium и FFmpeg
# Без этих пакетов Chromium не запустится (ошибка libnss3, libatk и т.д.)
RUN apt-get update && apt-get install -y \
    chromium \
    ffmpeg \
    libnss3 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm1 \
    libasound2 \
    fonts-liberation \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# 2. Говорим pyppeteer не скачивать свой Chromium, а использовать системный
ENV PUPPETEER_SKIP_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# 3. Копируем и устанавливаем Python-зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Копируем весь код бота
COPY . .

# 5. Запускаем бота
CMD ["python", "bot.py"]
