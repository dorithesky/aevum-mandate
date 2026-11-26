"""Build the demo video from screenshots.

    python scripts/make_video.py demo/scenes.json demo/out/mandate-demo.mp4

Scenes are real screenshots of the deployed desk and the Aevum explorer, with
captions. Frames are rendered with Pillow (slow zoom + crossfade) and piped to
ffmpeg from imageio-ffmpeg, so no system ffmpeg is needed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 30
FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
ACCENT = (61, 220, 151)
BG = (7, 10, 14)


def fit(img: Image.Image, zoom: float) -> Image.Image:
    img = img.convert("RGB")
    scale = max(W / img.width, H / img.height) * zoom
    nw, nh = int(img.width * scale), int(img.height * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - W) // 2
    top = (nh - H) // 2
    return img.crop((left, top, left + W, top + H))


def wrap(draw, text, font, max_width):
    words, lines, current = text.split(), [], ""
    for word in words:
        trial = (current + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def caption(img: Image.Image, label: str, text: str) -> Image.Image:
    base = img.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    fade_top, solid_top = H - 200, H - 132
    for y in range(fade_top, solid_top):
        t = (y - fade_top) / (solid_top - fade_top)
        d.line([(0, y), (W, y)], fill=(4, 7, 10, int(238 * t ** 0.8)))
    d.rectangle([0, solid_top, W, H], fill=(4, 7, 10, 238))
    d.rectangle([0, solid_top, W, solid_top + 1], fill=(30, 39, 52, 255))
    d.rectangle([56, solid_top + 26, 60, solid_top + 64], fill=ACCENT + (255,))
    label_font = ImageFont.truetype(FONT_BOLD, 14)
    body_font = ImageFont.truetype(FONT_REG, 23)
    d.text((76, solid_top + 20), label.upper(), font=label_font, fill=ACCENT + (255,))
    y = solid_top + 44
    for line in wrap(d, text, body_font, W - 130)[:2]:
        d.text((76, y), line, font=body_font, fill=(240, 246, 252, 255))
        y += 31
    return Image.alpha_composite(base, overlay).convert("RGB")


def title_card(title: str, subtitle: str, footer: str) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(7 + 8 * t), int(10 + 14 * t), int(14 + 16 * t)))
    d.rectangle([0, 0, W, 5], fill=ACCENT)
    f1 = ImageFont.truetype(FONT_BOLD, 64)
    f2 = ImageFont.truetype(FONT_REG, 26)
    f3 = ImageFont.truetype(FONT_REG, 19)
    d.text((90, 250), title, font=f1, fill=(240, 246, 252))
    d.text((92, 340), subtitle, font=f2, fill=(155, 172, 192))
    d.text((92, 560), footer, font=f3, fill=ACCENT)
    return img


def main(manifest: str, out: str) -> int:
    scenes = json.loads(Path(manifest).read_text())
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
        "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    prev_last = None
    fade = int(FPS * 0.45)
    total = 0
    for scene in scenes:
        if scene.get("kind") == "title":
            frame = title_card(scene["title"], scene.get("subtitle", ""), scene.get("footer", ""))
            n = int(scene.get("duration", 3.5) * FPS)
            for _ in range(n):
                proc.stdin.write(frame.tobytes())
            prev_last, total = frame, total + n
            continue
        src = Image.open(scene["image"])
        n = int(scene.get("duration", 5) * FPS)
        zoom0 = scene.get("zoom", 1.0)
        zoom1 = scene.get("zoom", 1.0) + scene.get("zoom_to", 0.035)
        for i in range(n):
            t = i / max(1, n - 1)
            zoom = zoom0 + (zoom1 - zoom0) * t
            frame = caption(fit(src, zoom), scene.get("label", ""), scene.get("caption", ""))
            if prev_last is not None and i < fade:
                frame = Image.blend(prev_last, frame, i / fade)
            proc.stdin.write(frame.tobytes())
        prev_last, total = frame, total + n
        print(f"  {scene.get('label','')}: {n} frames")
    proc.stdin.close()
    proc.wait()
    print(f"wrote {out} — {total / FPS:.1f}s, {total} frames")
    return 0 if proc.returncode == 0 else proc.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
