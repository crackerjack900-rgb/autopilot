"""Pretend to post (for testing the schedule without touching TikTok)."""


def post(video_path, caption, media_url, cfg):
    print(f"[dry_run] would post {video_path}\n---\n{caption}\n---")
    return {"status": "posted", "id": "dry-run", "privacy": "n/a", "detail": "dry run"}
