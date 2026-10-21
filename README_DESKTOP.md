# Запуск бота на десктопе (Windows / macOS / Linux)

## 1. Python
Нужен Python **3.11+**. Скачай с https://python.org
При установке на Windows отметь галочку **Add Python to PATH**.

## 2. FFmpeg (обязательно для гифок)
Без ffmpeg гифки не соберутся из PNG-кадров.

### Windows
1. Скачай https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
2. Распакуй в `C:\ffmpeg`
3. Добавь `C:\ffmpeg\bin` в PATH:
   - Win+R → `sysdm.cpl` → Дополнительно → Переменные среды
   - В `Path` добавь `C:\ffmpeg\bin`
4. Проверь: `ffmpeg -version`

### macOS
```bash
brew install ffmpeg