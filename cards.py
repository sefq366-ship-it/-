import os
from io import BytesIO
from datetime import date

from PIL import Image, ImageDraw, ImageFont

# ---------- Поиск шрифтов ----------
_FONT_REG = None
_FONT_BOLD = None

def _find_font(bold=False):
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            "/usr/local/share/fonts/DejaVuSans-Bold.ttf",
            "DejaVuSans-Bold.ttf",
            "fonts/DejaVuSans-Bold.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/local/share/fonts/DejaVuSans.ttf",
            "DejaVuSans.ttf",
            "fonts/DejaVuSans.ttf",
        ]
    )
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

def load_fonts():
    global _FONT_REG, _FONT_BOLD
    _FONT_REG = _find_font(False)
    _FONT_BOLD = _find_font(True)

def _font(path, size):
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

# ---------- Вспомогательное ----------
def _gradient(w, h, top, bottom):
    base = Image.new("RGB", (w, h), top)
    d = ImageDraw.Draw(base)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        d.line([(0, y), (w, y)], fill=(r, g, b))
    return base

def _center(d, text, font, y, fill, w):
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    d.text(((w - tw) / 2, y), text, font=font, fill=fill)

# ---------- Карточка отчества ----------
def build_card(otchestvo: str, father: str, extra: str = "") -> BytesIO:
    W, H = 900, 520
    img = _gradient(W, H, (28, 32, 56), (12, 14, 28))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([20, 20, W - 20, H - 20], radius=28,
                        outline=(120, 180, 255), width=3)

    f_small = _font(_FONT_REG, 28)
    f_title = _font(_FONT_BOLD or _FONT_REG, 84)
    f_sub = _font(_FONT_REG, 44)
    f_extra = _font(_FONT_REG, 26)
    f_foot = _font(_FONT_REG, 22)

    _center(d, "Отчество", f_small, 70, (150, 160, 190), W)
    _center(d, otchestvo, f_title, 120, (240, 244, 255), W)
    _center(d, "Отец", f_small, 260, (150, 160, 190), W)
    _center(d, father, f_sub, 305, (120, 180, 255), W)
    if extra:
        _center(d, extra, f_extra, 390, (150, 160, 190), W)
    _center(d, "сделано в боте", f_foot, 460, (110, 120, 150), W)

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf

# ---------- Паспорт ----------
def build_passport(first_name: str, father: str, otch: str, level: str) -> BytesIO:
    W, H = 900, 560
    img = _gradient(W, H, (32, 26, 50), (14, 10, 24))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([20, 20, W - 20, H - 20], radius=28,
                        outline=(200, 160, 90), width=4)

    f_small = _font(_FONT_REG, 24)
    f_bold = _font(_FONT_BOLD or _FONT_REG, 44)
    f_row = _font(_FONT_REG, 32)

    _center(d, "🛂 ПАСПОРТ ГРАЖДАНИНА", f_small, 60, (200, 160, 90), W)
    _center(d, first_name or "Гражданин", f_bold, 110, (245, 240, 255), W)
    _center(d, f"Отец: {father}", f_row, 190, (200, 160, 90), W)
    _center(d, f"Отчество: {otch}", f_row, 250, (220, 220, 240), W)
    _center(d, f"Уровень: {level}", f_row, 310, (220, 220, 240), W)
    _center(d, f"Выдан: {date.today().isoformat()}", f_small, 400, (170, 170, 200), W)
    _center(d, "Действителен бессрочно 😎", f_small, 450, (120, 120, 150), W)

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
