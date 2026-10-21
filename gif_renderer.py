# ============================================================
# gif_renderer.py — рендер Lottie → MP4 для Telegram
# ============================================================
import asyncio
import json
import math
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path

import aiohttp
import pyppeteer

logger = logging.getLogger("gif_renderer")

# ============================================================
# ⚙️ ПАРАМЕТРЫ РЕНДЕРА ПО УМОЛЧАНИЮ
# Баланс качества и скорости:
#   800×450, FPS 24, CRF 23, FRAME_SKIP 2
# ============================================================
DEFAULT_PARAMS = {
    "card_w": 800,
    "card_h": 450,
    "fps": 24,
    "frame_skip": 2,
    "crf": 23,
    "preset": "veryfast",
    "pix_fmt": "yuv420p",
}

LOTTIE_URL = "https://nft.fragment.com/gift/{slug}.lottie.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

_browser = None


async def init_browser():
    global _browser
    if _browser is not None:
        return _browser
    logger.info("🎬 Запускаю Chromium для рендера гифок...")
    _browser = await pyppeteer.launch(
        headless=True,
        executablePath='/usr/bin/chromium',
        args=[
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--single-process',
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
        raise RuntimeError(
            "ffmpeg не найден. Установи: Windows — https://www.gyan.dev/ffmpeg/builds/, "
            "macOS — brew install ffmpeg, Linux — apt install ffmpeg"
        )
    return exe


async def download_lottie(slug: str, dest: Path):
    url = LOTTIE_URL.format(slug=slug)
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": UA}) as s:
        async with s.get(url) as r:
            if r.status != 200:
                raise ValueError(f"Lottie HTTP {r.status} для {slug}")
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


async def render_mp4(slug: str, out_mp4: Path, params: dict, work_dir: Path):
    browser = await init_browser()
    ff = check_ffmpeg()

    lottie_path = work_dir / "anim.json"
    size = await download_lottie(slug, lottie_path)
    logger.info(f"[render] {slug}: Lottie {size} байт")

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
        raise RuntimeError(f"Не найдены слои Background/Gift в Lottie {slug}")

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

        logger.info(f"[render] {slug}: {len(frame_numbers)} кадров, fps={final_fps}")
    finally:
        await page.close()

    cmd = [
        ff, "-y",
        "-framerate", str(final_fps),
        "-i", str(work_dir / "frames" / "f_%06d.png"),
        "-an",
        "-c:v", "libx264",
        "-profile:v", "main",
        "-level", "4.0",
        "-preset", params["preset"],
        "-crf", str(params["crf"]),
        "-pix_fmt", params["pix_fmt"],
        "-threads", "0",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {res.stderr[-500:]}")

    size_mp4 = out_mp4.stat().st_size
    logger.info(f"[render] {slug}: MP4 {size_mp4} байт")
    return size_mp4


async def render_to_tempfile(slug: str, params: dict = None):
    params = {**DEFAULT_PARAMS, **(params or {})}
    work_dir = Path(tempfile.mkdtemp(prefix=f"gif_{slug}_"))
    out_mp4 = work_dir / f"{slug}.mp4"
    await render_mp4(slug, out_mp4, params, work_dir)
    return out_mp4, work_dir
