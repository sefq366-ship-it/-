FROM python:3.11-slim

WORKDIR /app

# Системные зависимости для pyppeteer (Chromium) и ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    ffmpeg \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Переменная для pyppeteer, чтобы он не качал свой Chromium
ENV PYPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Не запускаем от root
RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

CMD ["python", "bot.py"]
