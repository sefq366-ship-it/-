FROM python:3.11-slim

# 1. Устанавливаем зависимости для сборки Rust и работы gifski
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Устанавливаем Rust (Cargo)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# 3. Собираем gifski и копируем бинарник в /usr/local/bin
# Это может занять несколько минут при сборке
RUN cargo install gifski --root /usr/local

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
