FROM python:3.11-slim

# Устанавливаем curl для скачивания gifski
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Скачиваем официальный бинарник gifski (Linux x86_64)
RUN curl -L -o /usr/local/bin/gifski https://github.com/ImageOptim/gifski/releases/download/1.34.0/gifski-1.34.0-x86_64-unknown-linux-musl && \
    chmod +x /usr/local/bin/gifski

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
