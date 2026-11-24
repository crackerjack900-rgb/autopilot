"""Official TikTok Content Posting API (Direct Post, FILE_UPLOAD). Free.

Needs repo secrets: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN
(get the refresh token once with scripts/tiktok_auth.py).

Until TikTok audits your app, posts are forced to SELF_ONLY (private). With
tiktok_privacy="auto" we post PUBLIC_TO_EVERYONE when TikTok offers it, else SELF_ONLY.
"""
import math
import os
import time
from pathlib import Path

import requests

API = os.environ.get("TIKTOK_API_BASE", "https://open.tiktokapis.com")
CHUNK = 10 * 1024 * 1024


class TikTokError(RuntimeError):
    pass


def _check(r):
    try:
        j = r.json()
    except ValueError:
        raise TikTokError(f"HTTP {r.status_code}: {r.text[:300]}")
    err = (j.get("error") or {})
    if r.status_code >= 400 or err.get("code") not in (None, "", "ok"):
        raise TikTokError(f"{err.get('code')}: {err.get('message')} (HTTP {r.status_code}, log_id={err.get('log_id')})")
    return j


def access_token():
    r = requests.post(f"{API}/v2/oauth/token/", timeout=30, data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": os.environ["TIKTOK_REFRESH_TOKEN"],
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    j = r.json()
    if "access_token" not in j:
        raise TikTokError(f"token refresh failed: {j}")
    exp = j.get("refresh_expires_in")
    if exp and exp < 30 * 86400:
        print(f"::warning::TikTok refresh token expires in {exp // 86400} days - rerun scripts/tiktok_auth.py")
    return j["access_token"]


def post(video_path, caption, media_url, cfg):
    p = cfg["post"]
    tok = access_token()
    H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"}

    info = _check(requests.post(f"{API}/v2/post/publish/creator_info/query/", headers=H, timeout=30))["data"]
    opts = info.get("privacy_level_options", [])
    want = p.get("tiktok_privacy", "auto")
    if want == "auto":
        privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in opts else "SELF_ONLY"
    else:
        privacy = want if want in opts else "SELF_ONLY"
    max_dur = info.get("max_video_post_duration_sec")

    size = Path(video_path).stat().st_size
    if size <= 64 * 1024 * 1024:
        chunk, n = size, 1
    else:
        chunk = CHUNK
        n = size // chunk  # TikTok: last chunk absorbs the remainder
    body = {
        "post_info": {
            "title": caption[:2200],
            "privacy_level": privacy,
            "disable_comment": not p.get("allow_comments", True) or bool(info.get("comment_disabled")),
            "disable_duet": not p.get("allow_duet", False) or bool(info.get("duet_disabled")),
            "disable_stitch": not p.get("allow_stitch", False) or bool(info.get("stitch_disabled")),
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk,
                        "total_chunk_count": n},
    }
    j = _check(requests.post(f"{API}/v2/post/publish/video/init/", headers=H, json=body, timeout=60))
    publish_id, upload_url = j["data"]["publish_id"], j["data"]["upload_url"]

    with open(video_path, "rb") as f:
        for k in range(n):
            start = k * chunk
            length = (size - start) if k == n - 1 else chunk
            f.seek(start)
            data = f.read(length)
            r = requests.put(upload_url, data=data, timeout=300, headers={
                "Content-Type": "video/mp4", "Content-Length": str(length),
                "Content-Range": f"bytes {start}-{start + length - 1}/{size}"})
            if r.status_code not in (200, 201, 206):
                raise TikTokError(f"chunk {k + 1}/{n} upload failed: HTTP {r.status_code} {r.text[:200]}")

    status = "PROCESSING"
    for _ in range(60):
        time.sleep(float(os.environ.get("TIKTOK_POLL_SEC", 5)))
        s = _check(requests.post(f"{API}/v2/post/publish/status/fetch/", headers=H,
                                 json={"publish_id": publish_id}, timeout=30))["data"]
        status = s.get("status")
        if status == "PUBLISH_COMPLETE":
            ids = s.get("publicaly_available_post_id") or s.get("publicly_available_post_id") or []
            return {"status": "posted", "id": publish_id, "privacy": privacy,
                    "detail": f"post ids {ids}" if ids else "published"}
        if status == "FAILED":
            raise TikTokError(f"publish failed: {s.get('fail_reason')}")
    return {"status": "posted", "id": publish_id, "privacy": privacy,
            "detail": f"still {status} after 5 min; TikTok usually finishes on its own"}
