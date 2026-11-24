"""Posting backends. Each exposes post(video_path, caption, media_url, cfg) -> dict(status, id, detail)."""
import importlib


def get(name):
    return importlib.import_module(f"clipbot.backends.{name}")
