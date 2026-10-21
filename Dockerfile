# ============================================================
# Dockerfile для Bothost (гифки в инлайне)
# python:3.11-slim + chromium + ffmpeg + шрифты
# ============================================================
FROM python:3.11-slim

# --- Системные зависимости ---
# chromium          — headless-браузер для pyppeteer (рендер Lottie)
# ffmpeg            — склейка PNG-кадров в MP4
# fonts-liberation  — шрифты для корректного рендера текста
# libnss3, libatk... — библиотеки, без которых chromium не стартует
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    chromium \
    chromium-driver \
    fonts-liberation \
    libnss3 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libasound2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Python-зависимости ---
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Код ---
COPY . .

# --- Папка для временных файлов рендера ---
RUN mkdir -p /app/data /app/temp && chmod 777 /app/data /app/temp

# --- Переменные окружения для pyppeteer ---
# PYPPETEER_HOME — куда pyppeteer скачает свой Chromium (если не найдёт системный)
# CHROME_BIN    — путь к системному chromium
ENV PYPPETEER_HOME=/app/.pyppeteer
ENV CHROME_BIN=/usr/bin/chromium

# --- Запуск ---
CMD ["python", "bot.py"]