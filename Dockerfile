# 1. Берем базу Python
FROM python:3.11-slim

# 2. Устанавливаем системные пакеты (Chromium и FFmpeg)
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

# 3. Указываем pyppeteer использовать системный Chromium (а не качать свой)
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# 4. Рабочая папка
WORKDIR /app

# 5. Копируем и ставим Python-библиотеки
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Копируем код бота
COPY . .

# 7. Запуск
CMD ["python", "bot.py"]
