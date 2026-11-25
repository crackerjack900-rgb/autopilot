"""Channel watcher: download new uploads from the channels in channels.txt to a folder
(your My Passport drive by default) and transcribe them, ready for clipping.

channels.txt lines:   <channel url>  | <creator name>
State (which videos were already handled) lives in watch_state.json, committed to the repo.
"""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from . import ROOT, load_config, log

STATE = ROOT / "watch_state.json"
DEFAULT_DIR = "/Volumes/My Passport for Mac/Chat GPT & Claude/Video Clips/Auto Downloads"
FALLBACK_DIR = os.path.expanduser("~/Movies/Clip Autopilot Downloads")


def _safe(s, n=80):
    s = re.sub(r'[\\/:*?"<>|]+', "", s).strip()
    return re.sub(r"\s+", " ", s)[:n].rstrip(". ") or "video"


def load_channels(path=None):
    out = []
    for line in Path(path or ROOT / "channels.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url, _, name = (x.strip() for x in line.partition("|"))
        out.append((url, name or url.rstrip("/").split("/")[-2 if url.endswith(("videos", "streams")) else -1]))
    return out


def target_dir():
    want = os.environ.get("WATCH_DIR") or DEFAULT_DIR
    root = Path(want)
    # the drive must be plugged in: /Volumes/<drive> has to exist, we never create it
    drive = Path(*root.parts[:3]) if str(root).startswith("/Volumes/") else root.parent
    if drive.exists():
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".write-test"
            probe.write_text("ok")
            probe.unlink()
            return root, False
        except OSError as e:
            log(f"can't write to {root}: {e}")
    log(f"WARNING: {want} isn't available (drive unplugged or no permission) - using {FALLBACK_DIR}")
    fb = Path(FALLBACK_DIR)
    fb.mkdir(parents=True, exist_ok=True)
    return fb, True


def list_uploads(url, n):
    import yt_dlp
    opts = {"extract_flat": "in_playlist", "playlistend": n, "quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return [e for e in (info.get("entries") or []) if e and e.get("id")]


def download(video_url, folder):
    import yt_dlp
    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(folder / (_safe(folder.name.split(" - ", 1)[-1]) + ".%(ext)s")),
        "noplaylist": True, "quiet": True, "no_warnings": True, "retries": 5,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
    vid = next(p for p in folder.iterdir() if p.suffix in (".mp4", ".mkv", ".webm"))
    return info, vid


def write_transcript_txt(tr, path):
    lines = []
    for s in tr.get("segments", []):
        m, sec = divmod(int(s["start"]), 60)
        h, m = divmod(m, 60)
        lines.append(f"[{h:d}:{m:02d}:{sec:02d}] {s['text']}")
    Path(path).write_text("\n".join(lines) + "\n")


def run():
    cfg = load_config()
    w = cfg.get("watch", {})
    per_channel = int(w.get("check_latest", 5))
    min_minutes = float(w.get("min_minutes", 5))
    first_take = int(w.get("first_run_take", 1))
    max_per_run = int(os.environ.get("WATCH_MAX_DOWNLOADS") or w.get("max_downloads_per_run", 3))
    do_transcribe = bool(w.get("transcribe", True))

    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    out_root, fallback = target_dir()
    log(f"saving to {out_root}")
    done = []
    for url, name in load_channels():
        seen = set(state.get(url, []))
        try:
            entries = list_uploads(url, per_channel)
        except Exception as e:  # noqa: BLE001
            log(f"[{name}] couldn't list uploads: {e}")
            continue
        def is_live(e):
            return e.get("live_status") in ("is_live", "is_upcoming")

        def too_short(e):
            return bool(e.get("duration")) and e["duration"] < min_minutes * 60

        fresh = [e for e in entries if e["id"] not in seen and not is_live(e)]  # live ones: try again later
        state.setdefault(url, [])
        for e in [e for e in fresh if too_short(e)]:  # shorts are never worth downloading
            state[url].append(e["id"])
        fresh = [e for e in fresh if not too_short(e)]
        if not seen:  # first time we see this channel: don't grab its whole back catalog
            keep, skip = fresh[:first_take], fresh[first_take:]
            state[url] += [e["id"] for e in skip]
            fresh = keep
            log(f"[{name}] first run: taking the newest {len(keep)}, skipping {len(skip)} older")
        for e in fresh:
            if len(done) >= max_per_run:
                break
            vurl = e.get("url") or f"https://www.youtube.com/watch?v={e['id']}"
            date = datetime.now().strftime("%Y-%m-%d")
            folder = out_root / _safe(name, 40) / f"{date} - {_safe(e.get('title') or e['id'])}"
            folder.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            log(f"[{name}] downloading {e.get('title')!r}")
            info, vid = download(vurl, folder)
            (folder / "info.json").write_text(json.dumps({
                "id": e["id"], "title": info.get("title"), "creator": name, "url": info.get("webpage_url") or vurl,
                "duration": info.get("duration"), "upload_date": info.get("upload_date")}, indent=2))
            if do_transcribe:
                from .transcribe import transcribe
                tc = cfg["transcription"]
                tr = transcribe(vid, tc["whisper_model"], tc.get("language"))
                write_transcript_txt(tr, folder / "transcript.txt")
            state[url].append(e["id"])
            STATE.write_text(json.dumps(state, indent=2) + "\n")  # save after each video
            done.append(f"{name}: {info.get('title')}")
            log(f"[{name}] done in {int(time.time() - t0)}s -> {folder}")
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    log(f"{len(done)} new video(s)" + (" (saved to fallback folder!)" if fallback and done else ""))
    return done, fallback
