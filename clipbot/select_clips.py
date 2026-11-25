"""Pick the strongest self-contained moments from a transcript.

If plans/<video_id>.json exists (e.g. written by Claude or by you), it is used instead:
  [{"start": 12.3, "end": 47.0, "hook": "optional caption line"}, ...]
"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np

from . import ROOT, log
from .censor import has_blocked

HOOK_WORDS = {
    "why", "how", "what", "never", "always", "secret", "mistake", "truth", "actually", "crazy",
    "insane", "best", "worst", "wrong", "stop", "nobody", "everyone", "money", "biggest", "realize",
    "important", "problem", "imagine", "listen", "honestly", "literally", "story", "first", "only",
}
FILLER = {"um", "uh", "like", "you know", "so", "yeah", "okay", "right"}


def _sentences(words):
    sents, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 9
        if re.search(r"[.!?]$", w["w"]) or gap > 0.9:
            sents.append(cur)
            cur = []
    if cur:
        sents.append(cur)
    return [{"start": s[0]["start"], "end": s[-1]["end"], "words": s,
             "text": " ".join(x["w"] for x in s)} for s in sents]


def _loudness(video_path, hop=0.5):
    """RMS loudness per `hop` seconds, normalized 0..1."""
    sr = 8000
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video_path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True, check=True,
    ).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    n = int(sr * hop)
    if len(a) < n:
        return np.zeros(1), hop
    a = a[: len(a) // n * n].reshape(-1, n)
    rms = np.sqrt((a ** 2).mean(axis=1)) + 1e-6
    db = 20 * np.log10(rms)
    lo, hi = np.percentile(db, 10), np.percentile(db, 95)
    return np.clip((db - lo) / max(hi - lo, 1e-3), 0, 1), hop


def _score(window, loud, hop):
    text = " ".join(s["text"] for s in window).lower()
    toks = re.findall(r"[a-z']+", text)
    start, end = window[0]["start"], window[-1]["end"]
    dur = max(end - start, 1)
    wps = len(toks) / dur
    i0, i1 = int(start / hop), max(int(end / hop), int(start / hop) + 1)
    energy = float(loud[i0:i1].mean()) if i0 < len(loud) else 0.0
    first = window[0]["text"].lower()
    hook = sum(t in HOOK_WORDS for t in re.findall(r"[a-z']+", first)) * 0.6
    hook += 0.8 if "?" in first else 0
    hook += 0.4 if re.search(r"\d", first) else 0
    hook += 0.3 if re.search(r"\b(you|your)\b", first) else 0
    filler = sum(t in FILLER for t in toks) / max(len(toks), 1)
    ends_clean = 0.5 if re.search(r"[.!?]$", window[-1]["text"]) else 0
    pace = 1 - min(abs(wps - 2.8) / 2.8, 1)  # natural, lively speech ~2.8 words/s
    return 2.0 * energy + 1.5 * pace + hook + ends_clean - 3 * filler


def select(video_id, transcript, video_path, cfg, duration=None):
    plan = ROOT / "plans" / f"{video_id}.json"
    if plan.exists():
        log("using hand/Claude-written plan", plan.name)
        return json.loads(plan.read_text())

    c = cfg["clips"]
    sents = _sentences(transcript["words"])
    if not sents:
        return []
    loud, hop = _loudness(video_path)
    total = duration or sents[-1]["end"]
    n_wanted = int(max(1, min(c["max_per_video"], round(total / 60 / c["one_clip_per_n_minutes"]))))

    cands = []
    for i in range(len(sents)):
        win = []
        for j in range(i, len(sents)):
            win.append(sents[j])
            d = win[-1]["end"] - win[0]["start"]
            if d > c["max_seconds"]:
                break
            if d >= c["min_seconds"] and not has_blocked(" ".join(x["text"] for x in win)):
                s = _score(win, loud, hop) - abs(d - c["target_seconds"]) / c["target_seconds"] * 2.0
                cands.append((s, win[0]["start"], win[-1]["end"], win[0]["text"]))
    cands.sort(reverse=True)

    chosen = []
    for s, st, en, first in cands:
        if all(en <= a - 1 or st >= b + 1 for _, a, b, _ in chosen):
            chosen.append((s, st, en, first))
        if len(chosen) >= n_wanted:
            break
    chosen.sort(key=lambda x: x[1])
    out = [{"start": round(max(st - 0.15, 0), 2), "end": round(en + 0.35, 2), "hook": first, "score": round(s, 2)}
           for s, st, en, first in chosen]
    log(f"selected {len(out)} clips:", [(o['start'], o['end'], o['score']) for o in out])
    return out
