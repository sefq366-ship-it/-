FROM python:3.11-slim

# 1. Системные зависимости: сборка Rust/gifski + ffmpeg
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    pkg-config \
    libssl-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 2. Rust (Cargo) для сборки gifski
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# 3. Собираем gifski и кладём в /usr/local/bin
RUN cargo install gifski --root /usr/local

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
