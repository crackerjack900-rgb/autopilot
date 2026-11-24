"""Upload-Post (paid plan needed for TikTok). Secrets: UPLOAD_POST_API_KEY, UPLOAD_POST_USER."""
import os

import requests


def post(video_path, caption, media_url, cfg):
    with open(video_path, "rb") as f:
        r = requests.post("https://api.upload-post.com/api/upload", timeout=600,
                          headers={"Authorization": f"Apikey {os.environ['UPLOAD_POST_API_KEY']}"},
                          data={"user": os.environ["UPLOAD_POST_USER"], "platform[]": "tiktok",
                                "title": caption[:2200]},
                          files={"video": (os.path.basename(video_path), f, "video/mp4")})
    if r.status_code >= 400:
        raise RuntimeError(f"upload-post HTTP {r.status_code}: {r.text[:400]}")
    return {"status": "posted", "id": str(r.json().get("request_id", "")), "privacy": "PUBLIC",
            "detail": "via upload-post"}
