# ============================================================
# gif_renderer.py — рендер Lottie / static → MP4 для Telegram
# ============================================================
import asyncio
import json
import math
import shutil
import subprocess
import tempfile
import logging
import os
from pathlib import Path

import aiohttp
import pyppeteer

logger = logging.getLogger("gif_renderer")

DEFAULT_PARAMS = {
    "card_w": 800,
    "card_h": 450,
    "fps": 24,
    "frame_skip": 2,
    "crf": 23,
    "preset": "veryfast",
    "pix_fmt": "yuv420p",
    "static_duration": 3,
}

LOTTIE_URL = "https://nft.fragment.com/gift/{slug}.lottie.json"
IMAGE_URL = "https://nft.fragment.com/gift/{slug}.webp"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

_browser = None

async def init_browser():
    global _browser
    if _browser is not None:
        return _browser

    logger.info("🎬 Запускаю Chromium для рендера гифок...")
    _browser = await pyppeteer.launch(
        headless=True,
        executablePath='/usr/bin/chromium', # Если на винде, укажи путь к chrome.exe
        args=[
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
        ]
    )
    logger.info("🎬 Chromium запущен")
    return _browser


async def close_browser():
    global _browser
    if _browser:
        try:
            await _browser.close()
        except:
            pass
        _browser = None


def check_ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg не найден")
    return exe


async def download_lottie(slug_full: str, dest: Path):
    url = LOTTIE_URL.format(slug=slug_full)
    logger.info(f"[lottie] → {url}")
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": UA}) as s:
        async with s.get(url) as r:
            if r.status == 404:
                logger.warning(f"[lottie] 404 для {slug_full} — новая коллекция")
                return 0
            if r.status != 200:
                raise ValueError(f"Lottie HTTP {r.status} для {slug_full}")
            data = await r.read()
    dest.write_bytes(data)
    return len(data)


async def download_fragment_image(slug_full: str, dest: Path):
    url = IMAGE_URL.format(slug=slug_full)
    logger.info(f"[image] → {url}")
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": UA}) as s:
        async with s.get(url) as r:
            if r.status != 200:
                raise ValueError(f"Image HTTP {r.status} для {slug_full}")
            data = await r.read()
    dest.write_bytes(data)
    return len(data)


def _build_html(bg_data: dict, anim_data: dict, params: dict) -> str:
    cw = params["card_w"]
    ch = params["card_h"]
    comp_w = int(anim_data.get("w", 512))
    comp_h = int(anim_data.get("h", 512))

    return f"""<!DOCTYPE html>
<html>
<head>
<script src="https://cdnjs.cloudflare.com/ajax/libs/bodymovin/5.12.2/lottie.min.js"></script>
<style>
  body {{ margin:0; padding:0; background:transparent; overflow:hidden; }}
  #bg   {{ position:absolute; top:0; left:0; width:{cw}px; height:{ch}px; }}
  #gift {{ position:absolute; top:{(ch-comp_h)//2}px; left:{(cw-comp_w)//2}px;
           width:{comp_w}px; height:{comp_h}px; }}
  #bg svg, #gift svg {{ width:100% !important; height:100% !important; }}
</style>
</head>
<body>
<div id="bg"></div>
<div id="gift"></div>
<script>
  const bgAnim = lottie.loadAnimation({{
    container: document.getElementById('bg'), renderer:'svg',
    loop:false, autoplay:false, animationData: {json.dumps(bg_data)},
    rendererSettings: {{ preserveAspectRatio:'none' }}
  }});
  const giftAnim = lottie.loadAnimation({{
    container: document.getElementById('gift'), renderer:'svg',
    loop:false, autoplay:false, animationData: {json.dumps(anim_data)},
    rendererSettings: {{ preserveAspectRatio:'xMidYMid meet' }}
  }});
  window.setFrame = (f) => {{
    bgAnim.goToAndStop(f, true);
    giftAnim.goToAndStop(f, true);
  }};
  window.ready = true;
</script>
</body>
</html>"""


async def render_static_mp4(webp_path: Path, out_mp4: Path, params: dict):
    ff = check_ffmpeg()
    duration = int(params.get("static_duration", 3))
    cw = params["card_w"]
    ch = params["card_h"]

    cmd = [
        ff, "-y", "-loop", "1", "-i", str(webp_path), "-t", str(duration),
        "-vf", f"scale={cw}:{ch}:force_original_aspect_ratio=decrease,pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color=#1a1a1a,format=yuv420p",
        "-r", str(params["fps"]), "-c:v", "libx264", "-profile:v", "main",
        "-level", "4.0", "-preset", params["preset"], "-crf", str(params["crf"]),
        "-pix_fmt", params["pix_fmt"], "-threads", "0", "-movflags", "+faststart",
        str(out_mp4),
    ]
    logger.info(f"[static-render] ffmpeg → {out_mp4.name}")
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg static error: {res.stderr[-500:]}")
    return out_mp4.stat().st_size


async def render_mp4(slug_full: str, out_mp4: Path, params: dict, work_dir: Path):
    browser = await init_browser()
    ff = check_ffmpeg()

    lottie_path = work_dir / "anim.json"
    size = await download_lottie(slug_full, lottie_path)
    if size == 0:
        raise RuntimeError(f"Lottie 404 для {slug_full}")

    data = json.loads(lottie_path.read_text(encoding="utf-8"))

    frame_rate = float(data.get("fr", 60))
    ip = float(data.get("ip", 0))
    op = float(data.get("op", 1))

    step = max(1, round(frame_rate / params["fps"]))
    frame_numbers = list(range(int(ip), int(op), step)) or [int(ip)]
    frame_numbers = frame_numbers[::params["frame_skip"]]
    final_fps = max(1, math.ceil(params["fps"] / params["frame_skip"]))

    layers = data.get("layers", [])
    bg_names = {"Background", "Pattern", "Color Icon"}
    anim_names = {"Gift"}
    bg_layers = [x for x in layers if x.get("nm") in bg_names]
    anim_layers = [x for x in layers if x.get("nm") in anim_names]

    if not bg_layers or not anim_layers:
        raise RuntimeError(f"Не найдены слои Background/Gift в Lottie {slug_full}")

    bg_data = dict(data); bg_data["layers"] = bg_layers
    anim_data = dict(data); anim_data["layers"] = anim_layers

    html = _build_html(bg_data, anim_data, params)
    html_path = work_dir / "render.html"
    html_path.write_text(html, encoding="utf-8")

    page = await browser.newPage()
    try:
        await page.setViewport({"width": params["card_w"], "height": params["card_h"]})
        await page.goto(f"file://{html_path}")
        await page.waitForFunction("window.ready === true", timeout=15000)

        frames_dir = work_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        for idx, fnum in enumerate(frame_numbers):
            await page.evaluate(f"setFrame({fnum})")
            fp = frames_dir / f"f_{idx:06d}.png"
            await page.screenshot({"path": str(fp), "omitBackground": True})
    finally:
        await page.close()

    cmd = [
        ff, "-y", "-framerate", str(final_fps), "-i", str(work_dir / "frames" / "f_%06d.png"),
        "-an", "-c:v", "libx264", "-profile:v", "main", "-level", "4.0",
        "-preset", params["preset"], "-crf", str(params["crf"]),
        "-pix_fmt", params["pix_fmt"], "-threads", "0", "-movflags", "+faststart",
        str(out_mp4),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {res.stderr[-500:]}")
    return out_mp4.stat().st_size


async def render_to_tempfile(slug_full: str, params: dict = None):
    params = {**DEFAULT_PARAMS, **(params or {})}
    work_dir = Path(tempfile.mkdtemp(prefix=f"gif_{slug_full}_"))
    out_mp4 = work_dir / f"{slug_full}.mp4"

    try:
        await render_mp4(slug_full, out_mp4, params, work_dir)
        return out_mp4, work_dir
    except RuntimeError as e:
        if "Lottie 404" not in str(e) and "Lottie" not in str(e):
            raise
        logger.info(f"[fallback] {slug_full}: Lottie нет → статичная картинка")

    webp_path = work_dir / "preview.webp"
    await download_fragment_image(slug_full, webp_path)
    await render_static_mp4(webp_path, out_mp4, params)
    return out_mp4, work_dir

# ===== НОВОЕ: Генерация заглушки =====
async def generate_placeholder(logo_path: str, out_mp4: Path, params: dict):
    """Создает короткое видео из логотипа для заглушки"""
    ff = check_ffmpeg()
    cw = params.get("card_w", 800)
    ch = params.get("card_h", 450)
    
    # Плавный зум логотипа на темном фоне
    cmd = [
        ff, "-y", "-loop", "1", "-i", logo_path,
        "-t", "2",
        "-vf", f"scale={cw}:{ch}:force_original_aspect_ratio=decrease,pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color=#111111,zoompan=z='min(zoom+0.0015,1.2)':d=48:s={cw}x{ch}:fps=24",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_mp4)
    ]
    
    logger.info("[placeholder] Генерирую заглушку...")
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg placeholder error: {res.stderr[-500:]}")
    return out_mp4
