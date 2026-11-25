"""Render a 1080x1920 clip: face-following crop (or blurred-background fit) + burned-in word captions."""
import json
import os
import subprocess
from pathlib import Path

from . import ASSETS, log
from .censor import bleep_spans, is_bleep, star

W, H = 1080, 1920


_CAPS = {}


def ffmpeg_has(kind, name):
    """kind: 'filters' or 'encoders'. Cached check of what this ffmpeg build supports."""
    if kind not in _CAPS:
        out = subprocess.run(["ffmpeg", "-hide_banner", f"-{kind}"], capture_output=True, text=True).stdout
        _CAPS[kind] = {ln.split()[1] for ln in out.splitlines() if len(ln.split()) > 1 and ln.startswith(" ")}
    return name in _CAPS[kind]


def video_codec_args():
    if ffmpeg_has("encoders", "libx264"):
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]
    if ffmpeg_has("encoders", "h264_videotoolbox"):  # Apple's built-in hardware encoder
        return ["-c:v", "h264_videotoolbox", "-b:v", "8M"]
    return ["-c:v", "mpeg4", "-q:v", "3"]


def blur_filter():
    if ffmpeg_has("filters", "boxblur"):
        return "boxblur=24:2"
    if ffmpeg_has("filters", "gblur"):
        return "gblur=sigma=24"
    return "scale=54:96,scale=1080:1920"  # cheap blur: shrink and blow back up


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    s = j["streams"][0]
    return int(s["width"]), int(s["height"]), float(j["format"]["duration"])


def face_center(path, start, end, samples=24):
    """Median horizontal face position (0..1) across the clip, or None if faces aren't stable."""
    import cv2
    import numpy as np

    casc = cv2.CascadeClassifier(str(ASSETS / "haarcascade_frontalface_default.xml"))
    cap = cv2.VideoCapture(str(path))
    xs, hits = [], 0
    for k in range(samples):
        t = start + (end - start) * (k + 0.5) / samples
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        scale = 480 / w
        g = cv2.cvtColor(cv2.resize(frame, (480, int(h * scale))), cv2.COLOR_BGR2GRAY)
        faces = casc.detectMultiScale(g, 1.1, 6, minSize=(30, 30))
        if len(faces):
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            xs.append((x + fw / 2) / 480)
            hits += 1
    cap.release()
    if hits < samples * 0.4:
        return None
    xs = np.array(xs)
    if xs.std() > 0.12:  # speakers on both sides / lots of movement -> show full frame
        return None
    return float(np.median(xs))


def _ass_time(t):
    t = max(t, 0)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def caption_lines(words, start, end, cfg):
    """[(t0, t1, text)] relative to clip start, 2-3 words per line."""
    c = cfg["captions"]
    lines = []
    chunk = []

    def flush():
        if chunk:
            txt = " ".join(star(x["w"]) if c.get("bleep_swears") and is_bleep(x["w"]) else x["w"] for x in chunk)
            if c.get("uppercase"):
                txt = txt.upper()
            txt = txt.replace("{", "(").replace("}", ")").replace("\\", "")
            lines.append((chunk[0]["start"] - start, chunk[-1]["end"] - start + 0.05, txt))

    for w in words:
        if w["end"] < start or w["start"] > end:
            continue
        if chunk and (len(chunk) >= c["words_per_line"] or w["start"] - chunk[-1]["end"] > 0.45
                      or chunk[-1]["w"].endswith((".", "?", "!", ","))):
            flush()
            chunk = []
        chunk.append(w)
    flush()
    # make lines contiguous so captions don't flicker
    fixed = []
    for i, (a, b, t) in enumerate(lines):
        if i + 1 < len(lines) and lines[i + 1][0] - b < 0.3:
            b = lines[i + 1][0]
        fixed.append((a, b, t))
    return fixed


def write_ass(words, start, end, path, cfg):
    """Kept for anyone using libass; the renderer itself uses caption_track()."""
    c = cfg["captions"]
    fixed = caption_lines(words, start, end, cfg)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Poppins,{c['font_size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,2,80,80,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    body = "".join(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Cap,,0,0,0,,{{\\fad(40,0)}}{t}\n" for a, b, t in fixed)
    Path(path).write_text(head + body)


def caption_track(lines, dur, folder, cfg):
    """Draw each caption as a transparent 1080x1920 PNG and return an ffmpeg concat file that
    shows them at the right times. Works with any ffmpeg build (no libass needed)."""
    from PIL import Image, ImageDraw, ImageFont

    c = cfg["captions"]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(ASSETS / "Poppins-Bold.ttf"), int(c["font_size"]))
    blank = folder / "blank.png"
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(blank)
    bottom = H - 560  # same spot as before: lower third, above TikTok's buttons/caption area

    def draw(text, path):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        rows, cur = [], ""
        for word in text.split():  # wrap if a line is too wide
            trial = (cur + " " + word).strip()
            if cur and d.textlength(trial, font=font) > W - 160:
                rows.append(cur)
                cur = word
            else:
                cur = trial
        rows.append(cur)
        lh = int(c["font_size"] * 1.15)
        y = bottom - lh * len(rows)
        for row in rows:
            d.text((W / 2, y), row, font=font, fill=(255, 255, 255, 255), anchor="ma",
                   stroke_width=7, stroke_fill=(0, 0, 0, 255))
            y += lh
        img.save(path)

    entries, t = [], 0.0
    for i, (a, b, text) in enumerate(lines):
        a, b = max(a, t), min(b, dur)
        if b - a < 0.05:
            continue
        if a - t > 0.01:
            entries.append((blank, a - t))
        png = folder / f"cap_{i:03d}.png"
        draw(text, png)
        entries.append((png, b - a))
        t = b
    if dur - t > 0.01:
        entries.append((blank, dur - t))
    if not entries:
        entries.append((blank, dur))
    lst = folder / "captions.txt"
    body = "".join(f"file '{p.resolve()}'\nduration {d:.3f}\n" for p, d in entries)
    lst.write_text(body + f"file '{entries[-1][0].resolve()}'\n")
    return lst


def render(src, clip, words, out_path, cfg):
    sw, sh, _ = probe(src)
    st, en = clip["start"], clip["end"]
    if sw / sh <= 0.62:  # already vertical
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        mode = "vertical"
    else:
        fx = face_center(src, st, en)
        if fx is not None:
            sw2 = round(sw * H / sh / 2) * 2
            x = int(min(max(fx * sw2 - W / 2, 0), sw2 - W))
            vf = f"scale={sw2}:{H},crop={W}:{H}:{x}:0"
            mode = f"face-crop x={fx:.2f}"
        else:
            vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                  f"{blur_filter()}[bg];[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
            mode = "blur-fit"
    extra_inputs = []
    if cfg["captions"].get("burn_in") and words:
        lst = caption_track(caption_lines(words, st, en, cfg), en - st,
                            Path(out_path).with_suffix(""), cfg)
        extra_inputs = ["-f", "concat", "-safe", "0", "-i", str(lst.resolve())]
        fc = f"[0:v]{vf}[base];[1:v]format=rgba[cap];[base][cap]overlay=0:0:eof_action=pass[v]"
    else:
        fc = f"[0:v]{vf}[v]"
    amap = "0:a?"
    spans = bleep_spans(words, st, en) if (cfg["captions"].get("bleep_swears") and words) else []
    if spans:
        on = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in spans)
        fc += (f";[0:a]volume=0:enable='{on}'[mut];"
               f"sine=frequency=1000:sample_rate=44100:duration={en - st:.3f},volume=0.35,"
               f"volume=0:enable='not({on})'[bp];[mut][bp]amix=inputs=2:duration=first:normalize=0[a]")
        amap = "[a]"
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{st:.3f}", "-to", f"{en:.3f}", "-i", str(Path(src).resolve()),
           *extra_inputs, "-filter_complex", fc, "-map", "[v]", "-map", amap,
           "-r", "30", *video_codec_args(), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", str(Path(out_path).resolve())]
    subprocess.run(cmd, check=True, cwd=str(Path(out_path).resolve().parent))
    log(f"rendered {Path(out_path).name} [{mode}] {en - st:.1f}s, {len(spans)} bleeps")
    return mode
