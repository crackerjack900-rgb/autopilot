"""clipbot: URL in -> vertical captioned clips -> daily TikTok posts."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
WORK = Path(os.environ.get("CLIPBOT_WORK", ROOT / "work"))


def load_config(path=None):
    p = Path(path or os.environ.get("CLIPBOT_CONFIG", ROOT / "config.json"))
    return json.loads(p.read_text())


def log(*a):
    print("[clipbot]", *a, flush=True)
