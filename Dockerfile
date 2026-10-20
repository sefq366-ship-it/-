FROM python:3.11-slim

# 1. Устанавливаем ffmpeg, Chromium и все библиотеки для его работы
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    pkg-config \
    libssl-dev \
    ffmpeg \
    chromium \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libgbm1 \
    && rm -rf /var/lib/apt/lists/*

# 2. Указываем Puppeteer использовать системный Chromium
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
