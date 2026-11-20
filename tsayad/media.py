"""Branded product visuals with Pillow (RTL Hebrew via libraqm, python-bidi fallback)
and short vertical videos with FFmpeg. The product photo is always the real seller photo
from AliExpress – never an AI image presented as the product."""
from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

from . import config, http, log

L = log.get("media")
RAQM = features.check("raqm")
C = config.BRAND["colors"]


def font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(config.FONT_PATH), size, layout_engine=ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC)
    try:
        f.set_variation_by_name(weight)
    except Exception:  # noqa: BLE001
        pass
    return f


def _shape(text: str) -> str:
    if RAQM:
        return text
    from bidi.algorithm import get_display  # fallback when raqm missing
    return get_display(text)


def _kw() -> dict:
    return {"direction": "rtl", "language": "he"} if RAQM else {}


def text_w(draw: ImageDraw.ImageDraw, text: str, f) -> float:
    return draw.textlength(_shape(text), font=f, **_kw())


def wrap(draw, text: str, f, max_w: int, max_lines: int = 3) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if text_w(draw, test, f) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and " ".join(lines) != text:
        lines[-1] = lines[-1].rstrip("…") + "…"
    return lines


def rtl_text(draw, right_x: int, y: int, text: str, f, fill) -> None:
    w = text_w(draw, text, f)
    draw.text((right_x - w, y), _shape(text), font=f, fill=fill, **_kw())


def center_text(draw, cx: int, y: int, text: str, f, fill) -> None:
    w = text_w(draw, text, f)
    draw.text((cx - w / 2, y), _shape(text), font=f, fill=fill, **_kw())


def fetch_image(url: str) -> Image.Image | None:
    try:
        r = http.request("GET", url, retries=2, timeout=20)
        if r.status_code != 200 or not r.headers.get("Content-Type", "image").startswith("image"):
            return None
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception as e:  # noqa: BLE001
        L.warning("image download failed %s: %s", url, e)
        return None


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *img.size), radius, fill=255)
    out = Image.new("RGBA", img.size)
    out.paste(img, (0, 0), mask)
    return out


def _fit(img: Image.Image, box: tuple[int, int]) -> Image.Image:
    im = img.copy()
    im.thumbnail(box, Image.LANCZOS)
    canvas = Image.new("RGB", box, "white")
    canvas.paste(im, ((box[0] - im.width) // 2, (box[1] - im.height) // 2))
    return canvas


def logo_badge(draw, x: int, y: int, scale: float = 1.0) -> None:
    f = font(int(46 * scale), "Black")
    w = text_w(draw, config.BRAND["name_he"], f)
    pad = int(22 * scale)
    draw.rounded_rectangle((x, y, x + w + pad * 2 + int(40 * scale), y + int(74 * scale)), int(37 * scale), fill=C["primary"])
    draw.text((x + pad + int(40 * scale), y + int(6 * scale)), _shape(config.BRAND["name_he"]), font=f, fill="white", **_kw())
    # tag icon
    tx, ty = x + pad, y + int(20 * scale)
    draw.rounded_rectangle((tx, ty, tx + int(30 * scale), ty + int(34 * scale)), int(6 * scale), fill=C["accent"])
    draw.ellipse((tx + int(9 * scale), ty + int(7 * scale), tx + int(19 * scale), ty + int(17 * scale)), fill=C["primary"])


def card(product: dict, headline: str, size: tuple[int, int], out: Path, photo: Image.Image) -> Path:
    W, H = size
    vertical = H > W
    bg = Image.new("RGB", size, C["bg"])
    # soft blurred photo backdrop for depth
    backdrop = _fit(photo, size).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, backdrop, 0.25)
    d = ImageDraw.Draw(bg)
    m = 60
    logo_badge(d, m, m, 1.0 if not vertical else 1.2)
    top = m + 110
    if vertical:
        hf = font(70, "Black")
        y = 260
        for line in wrap(d, headline, hf, W - 2 * m, 2):
            center_text(d, W // 2, y, line, hf, C["dark"])
            y += 90
        top = y + 30
    from .content import facts
    f = facts(product)
    tf = font(40 if not vertical else 50, "SemiBold")
    pf = font(72 if not vertical else 90, "Black")
    sf = font(32 if not vertical else 42, "Medium")
    title_lines = wrap(d, product.get("title_he", ""), tf, W - 2 * m, 2)
    lh = int(tf.size * 1.3)
    bottom = H - m - (150 if vertical else 0)
    price_h = pf.size + 40
    price_y = bottom - price_h
    stat = " · ".join(x for x in [f["feedback"], f["orders"]] if x)
    stat_y = price_y - (sf.size + 22)
    title_y = (stat_y if stat else price_y) - 14 - lh * len(title_lines)
    photo_h = title_y - 28 - top
    box = (W - 2 * m, photo_h)
    ph = _rounded(_fit(photo, box), 36)
    shadow = Image.new("RGBA", (box[0] + 40, box[1] + 40), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((20, 24, box[0] + 20, box[1] + 24), 36, fill=(0, 0, 0, 60))
    sh = shadow.filter(ImageFilter.GaussianBlur(14))
    bg.paste(sh, (m - 20, top - 20), sh)
    bg.paste(ph, (m, top), ph)
    d = ImageDraw.Draw(bg)
    y = title_y
    for line in title_lines:
        rtl_text(d, W - m, y, line, tf, C["text"])
        y += lh
    if stat:
        rtl_text(d, W - m, stat_y, stat, sf, C["dark"])
    price = f["price"]
    pw = d.textlength(price, font=pf) + 70
    d.rounded_rectangle((W - m - pw, price_y, W - m, price_y + price_h), 30, fill=C["dark"])
    d.text((W - m - pw + 35, price_y + 8), price, font=pf, fill="white")
    if f["discount"]:
        df = font(44 if not vertical else 54, "Black")
        dt = f"-{f['discount']}"
        dw = d.textlength(dt, font=df) + 50
        x1 = W - m - pw - 20
        d.rounded_rectangle((x1 - dw, price_y + 10, x1, price_y + price_h - 10), 26, fill=C["primary"])
        d.text((x1 - dw + 25, price_y + (price_h - df.size) / 2 - 6), dt, font=df, fill="white")
    if vertical:
        cf = font(46, "Bold")
        center_text(d, W // 2, H - 150, "עוד דילים בערוץ הטלגרם שלנו", cf, C["primary"])
        u = f"t.me/{config.BRAND['telegram_username']}"
        d.text((W / 2 - d.textlength(u, font=cf) / 2, H - 92), u, font=cf, fill=C["dark"])
    out.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    return out


def make_all(product: dict, headline: str, out_dir: Path) -> dict | None:
    photo = fetch_image(product["image_url"])
    if photo is None or min(photo.size) < 200:
        return None
    pid = product["id"]
    sq = card(product, headline, (1080, 1080), out_dir / f"{pid}_square.jpg", photo)
    vt = card(product, headline, (1080, 1920), out_dir / f"{pid}_story.jpg", photo)
    res = {"square": sq, "vertical": vt}
    vid = video(vt, out_dir / f"{pid}_reel.mp4")
    if vid:
        res["video"] = vid
    return res


def video(still: Path, out: Path, seconds: int = 8) -> Path | None:
    """9:16 slow-zoom clip (TikTok/Reels/Shorts). Silent – add trending audio in-app to avoid copyright issues."""
    ff = shutil.which("ffmpeg")
    if not ff:
        L.warning("ffmpeg not found – skipping video")
        return None
    fps = 30
    frames = seconds * fps
    cmd = [ff, "-y", "-loglevel", "error", "-loop", "1", "-i", str(still), "-f", "lavfi", "-i",
           "anullsrc=channel_layout=stereo:sample_rate=44100",
           "-vf", f"scale=1188:2112,zoompan=z='min(zoom+0.0006,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                  f":d={frames}:s=1080x1920:fps={fps},format=yuv420p",
           "-t", str(seconds), "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)]
    try:
        subprocess.run(cmd, check=True, timeout=180)
        return out
    except Exception as e:  # noqa: BLE001
        L.warning("ffmpeg failed: %s", e)
        return None


def brand_assets(out_dir: Path) -> list[Path]:
    """Logo / profile picture / banner – generated, so brand stays consistent everywhere."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    # profile picture 1024x1024 (Telegram/Instagram/TikTok/Facebook all crop to circle)
    im = Image.new("RGB", (1024, 1024), C["primary"])
    d = ImageDraw.Draw(im)
    d.ellipse((112, 112, 912, 912), fill=C["bg"])
    words = config.BRAND["name_he"].split()
    f = font(200 if len(words) > 1 else 250, "Black")
    y0 = 290 if len(words) > 1 else 380
    for i, w in enumerate(words[:2]):
        center_text(d, 512, y0 + i * 210, w, f, C["dark"])
    d.rounded_rectangle((392, 760, 632, 776), 8, fill=C["primary"])
    p = out_dir / "profile.png"
    im.save(p)
    files.append(p)
    # wide banner 1640x624 (Facebook cover) – also used as og:image
    b = Image.new("RGB", (1640, 624), C["dark"])
    d = ImageDraw.Draw(b)
    d.rectangle((0, 520, 1640, 624), fill=C["primary"])
    center_text(d, 820, 120, config.BRAND["name_he"], font(200, "Black"), "white")
    center_text(d, 820, 370, config.BRAND["slogan"], font(56, "Medium"), C["accent"])
    center_text(d, 820, 538, f"t.me/{config.BRAND['telegram_username']}", font(48, "Bold"), "white")
    p = out_dir / "banner.png"
    b.save(p)
    files.append(p)
    return files
