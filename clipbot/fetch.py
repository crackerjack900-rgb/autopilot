"""Download a source video (YouTube, Vimeo, X, Drive, direct .mp4, 1000+ sites via yt-dlp)."""
import json
import os
import re
import shutil
from pathlib import Path

from . import WORK, log


def _slug(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s)[:60].strip("-") or "video"


def fetch(url, local_file=None):
    """Returns dict(id, title, creator, duration, url, path). local_file skips download (tests / dropped files)."""
    if local_file:
        src = Path(local_file)
        vid = _slug(src.stem)
        out = WORK / vid
        out.mkdir(parents=True, exist_ok=True)
        dst = out / "source.mp4"
        if src.resolve() != dst.resolve():
            shutil.copy(src, dst)
        meta = {"id": vid, "title": src.stem, "creator": os.environ.get("CLIPBOT_CREATOR", ""),
                "duration": None, "url": url or str(src), "path": str(dst)}
        (out / "info.json").write_text(json.dumps(meta, indent=2))
        return meta

    import yt_dlp

    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(WORK / "%(id)s" / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
    }
    cookies = os.environ.get("YTDLP_COOKIES_FILE")
    if cookies and Path(cookies).exists() and Path(cookies).stat().st_size > 0:
        opts["cookiefile"] = cookies
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    vid = info["id"]
    out = WORK / vid
    path = next(out.glob("source.*"))
    if path.suffix != ".mp4":
        path = path.rename(out / "source.mp4")
    meta = {
        "id": _slug(f"{info.get('extractor_key','web')}-{vid}"),
        "title": info.get("title") or vid,
        "creator": info.get("uploader") or info.get("channel") or "",
        "duration": info.get("duration"),
        "url": info.get("webpage_url") or url,
        "path": str(path),
    }
    (out / "info.json").write_text(json.dumps(meta, indent=2))
    log("downloaded", meta["title"], f"({meta['duration']}s)")
    return meta
