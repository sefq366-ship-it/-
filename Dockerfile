FROM python:3.11-slim

# Устанавливаем системные зависимости для Cairo (нужен для cairosvg) и ffmpeg
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    pkg-config \
    libssl-dev \
    ffmpeg \
    libcairo2-dev \
    libgirepository1.0-dev \
    gobject-introspection \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Устанавливаем Python-зависимости (включая lottie и cairosvg)
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["python", "bot.py"]
