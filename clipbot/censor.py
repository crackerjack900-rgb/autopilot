"""Keep clips inside TikTok's rules: bleep swears (audio + starred captions), drop clips with slurs.

Edit assets/bleep_words.txt and assets/block_words.txt to change the lists (one regex per line).
"""
import re
from functools import lru_cache

from . import ASSETS


@lru_cache(None)
def _load(name):
    p = ASSETS / name
    pats = [l.strip() for l in p.read_text().splitlines() if l.strip() and not l.startswith("#")] if p.exists() else []
    return re.compile(r"^(?:" + "|".join(pats) + r")$", re.I) if pats else None


def _core(word):
    return re.sub(r"^[^\w']+|[^\w']+$", "", word)


def is_bleep(word):
    rx = _load("bleep_words.txt")
    return bool(rx and rx.match(_core(word)))


def star(word):
    """F***, S***ty: keep first letter and surrounding punctuation."""
    core = _core(word)
    if not core:
        return word
    i = word.find(core)
    return word[:i] + core[0] + "*" * (len(core) - 1) + word[i + len(core):]


def has_blocked(text):
    rx = _load("block_words.txt")
    return bool(rx and any(rx.match(_core(w)) for w in text.split()))


def bleep_spans(words, start, end, pad=0.04):
    """(a, b) times relative to clip start for every swear inside the clip."""
    return [(max(w["start"] - start - pad, 0), w["end"] - start + pad)
            for w in words if start <= w["start"] < end and is_bleep(w["w"])]
