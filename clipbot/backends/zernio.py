"""Zernio (formerly Late / getlate.dev): audited TikTok app, public posts, free tier (~10 posts/mo).

Secrets: ZERNIO_API_KEY, ZERNIO_TIKTOK_ACCOUNT_ID. Optional ZERNIO_API_BASE.
Requires a PUBLIC media URL -> keep this repo public (clips are served from the release).
Verify field names against https://docs.zernio.com/platforms/tiktok on first run.
"""
import os

import requests

API = os.environ.get("ZERNIO_API_BASE", "https://zernio.com/api/v1")


def post(video_path, caption, media_url, cfg):
    if not media_url.startswith("http"):
        raise RuntimeError("zernio needs a public https media URL (use CLIPBOT_STORAGE=github with a public repo)")
    p = cfg["post"]
    body = {
        "content": caption[:2200],
        "mediaItems": [{"type": "video", "url": media_url}],
        "platforms": [{
            "platform": "tiktok",
            "accountId": os.environ["ZERNIO_TIKTOK_ACCOUNT_ID"],
            "platformSpecificData": {
                "privacyLevel": "PUBLIC_TO_EVERYONE",
                "allowComment": p.get("allow_comments", True),
                "allowDuet": p.get("allow_duet", False),
                "allowStitch": p.get("allow_stitch", False),
                "contentPreviewConfirmed": True,
                "expressConsentGiven": True,
            },
        }],
        "publishNow": True,
    }
    r = requests.post(f"{API}/posts", json=body, timeout=120,
                      headers={"Authorization": f"Bearer {os.environ['ZERNIO_API_KEY']}"})
    if r.status_code >= 400:
        raise RuntimeError(f"zernio HTTP {r.status_code}: {r.text[:400]}")
    j = r.json()
    return {"status": "posted", "id": str(j.get("_id") or j.get("id") or j.get("post", {}).get("_id")),
            "privacy": "PUBLIC_TO_EVERYONE", "detail": "via zernio"}
