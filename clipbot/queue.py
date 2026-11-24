"""Clip queue: queue.json (committed to the repo) + media storage.

Storage modes (env CLIPBOT_STORAGE):
  github  - clips stored as assets on a GitHub release tagged 'clip-queue' (default in Actions)
  local   - clips stored in ./media/ (local runs and tests)
"""
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import ROOT, log

QUEUE = Path(os.environ.get("CLIPBOT_QUEUE", ROOT / "queue.json"))
TAG = "clip-queue"


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load():
    return json.loads(QUEUE.read_text()) if QUEUE.exists() else {"items": []}


def save(q):
    QUEUE.write_text(json.dumps(q, indent=2, ensure_ascii=False) + "\n")


def storage():
    return os.environ.get("CLIPBOT_STORAGE", "local")


def _gh(*args, check=True):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def ensure_release():
    if storage() == "github" and _gh("release", "view", TAG, check=False).returncode != 0:
        _gh("release", "create", TAG, "--title", "Clip queue (managed by clipbot)",
            "--notes", "Rendered clips waiting to be posted. Managed automatically.", "--latest=false")


def put_media(path):
    path = Path(path)
    if storage() == "github":
        ensure_release()
        _gh("release", "upload", TAG, str(path), "--clobber")
        repo = os.environ["GITHUB_REPOSITORY"]
        return f"https://github.com/{repo}/releases/download/{TAG}/{path.name}"
    d = ROOT / "media"
    d.mkdir(exist_ok=True)
    shutil.copy(path, d / path.name)
    return str(d / path.name)


def get_media(item, dest_dir):
    dest = Path(dest_dir) / item["file"]
    if storage() == "github":
        _gh("release", "download", TAG, "--pattern", item["file"], "--dir", str(dest_dir), "--clobber")
    else:
        shutil.copy(ROOT / "media" / item["file"], dest)
    return dest


def delete_media(item):
    if storage() == "github":
        _gh("release", "delete-asset", TAG, item["file"], "--yes", check=False)
    else:
        (ROOT / "media" / item["file"]).unlink(missing_ok=True)


def seen_source(q, source_id):
    return any(i["source_id"] == source_id for i in q["items"])


def ready(q):
    return [i for i in q["items"] if i["status"] == "ready"]


def summary(q):
    from collections import Counter
    c = Counter(i["status"] for i in q["items"])
    return dict(c) | {"total": len(q["items"])}
