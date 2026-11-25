"""CLI.
  python -m clipbot ingest URL [--creator NAME] [--permission NOTE] [--local-file PATH] [--force]
  python -m clipbot ingest-file urls.txt      # every not-yet-processed URL in the file
  python -m clipbot post [--backend NAME]     # post the next ready clip(s)
  python -m clipbot status
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from . import WORK, load_config, log
from . import queue as Q

URL_RE = re.compile(r"https?://\S+")


def build_caption(cfg, hook, creator):
    p = cfg["post"]
    hook = re.sub(r"\s+", " ", hook).strip()
    if len(hook) > 120:
        hook = hook[:117].rsplit(" ", 1)[0] + "..."
    credit = p["credit_template"].format(creator=creator) if creator else ""
    cap = p["caption_template"].format(hook=hook, credit=credit, hashtags=" ".join(p["hashtags"]))
    return re.sub(r"[ \t]+", " ", cap).strip()


def ingest(url, cfg, creator=None, permission=None, local_file=None, force=False, max_minutes=None):
    from .fetch import fetch
    from .render import render
    from .select_clips import select
    from .transcribe import transcribe

    q = Q.load()
    max_minutes = max_minutes or cfg.get("fetch", {}).get("max_minutes")
    meta = fetch(url, local_file=local_file, max_minutes=max_minutes)
    if Q.seen_source(q, meta["id"]) and not force:
        log("already processed", meta["id"], "- skipping (use --force to redo)")
        return []
    creator = creator or meta["creator"]
    t = cfg["transcription"]
    tr = transcribe(meta["path"], t["whisper_model"], t.get("language"))
    clips = select(meta["id"], tr, meta["path"], cfg, meta.get("duration"))
    added = []
    outdir = WORK / meta["id"] / "clips"
    outdir.mkdir(parents=True, exist_ok=True)
    for k, c in enumerate(clips, 1):
        name = f"{meta['id']}_{k:02d}.mp4"
        out = outdir / name
        mode = render(meta["path"], c, tr["words"], out, cfg)
        hook = c.get("hook") or meta["title"]
        item = {
            "file": name, "source_id": meta["id"], "source_url": meta["url"], "source_title": meta["title"],
            "creator": creator, "permission": permission or "", "start": c["start"], "end": c["end"],
            "caption": build_caption(cfg, hook, creator), "layout": mode, "status": "ready",
            "created": Q.now(), "attempts": 0,
        }
        item["media_url"] = Q.put_media(out)
        q["items"].append(item)
        Q.save(q)  # save after each clip so a crash keeps progress
        added.append(item)
    log(f"queued {len(added)} clips from {meta['title']!r}")
    return added


def post(cfg, backend=None):
    from .backends import get
    backend = backend or os.environ.get("CLIPBOT_BACKEND") or cfg["post"]["backend"]
    mod = get(backend)
    q = Q.load()
    q["last_run"] = Q.now()  # heartbeat commit keeps GitHub from pausing the schedule
    Q.save(q)
    results = []
    for _ in range(cfg["queue"]["posts_per_run"]):
        todo = Q.ready(q)
        if not todo:
            log("queue empty - nothing to post")
            break
        item = todo[0]
        item["attempts"] = item.get("attempts", 0) + 1
        try:
            with tempfile.TemporaryDirectory() as d:
                path = Q.get_media(item, d)
                res = mod.post(str(path), item["caption"], item.get("media_url", ""), cfg)
            item.update(status="posted", posted_at=Q.now(), post_id=res.get("id"),
                        privacy=res.get("privacy"), detail=res.get("detail"))
            log("posted", item["file"], res)
            if backend != "zernio":  # zernio may still be fetching the URL
                Q.delete_media(item)
        except Exception as e:  # noqa: BLE001
            item["last_error"] = str(e)[:500]
            if item["attempts"] >= cfg["queue"]["max_attempts"]:
                item["status"] = "failed"
            log("POST FAILED", item["file"], e)
            Q.save(q)
            results.append({"file": item["file"], "error": str(e)})
            break
        Q.save(q)
        results.append({"file": item["file"], **res})
    return results


def low_queue(cfg, q=None):
    q = q or Q.load()
    need = cfg["queue"]["low_queue_alert_days"] * cfg["queue"]["posts_per_run"]
    return len(Q.ready(q)) < need


def main(argv=None):
    ap = argparse.ArgumentParser(prog="clipbot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ingest"); a.add_argument("url"); a.add_argument("--creator"); a.add_argument("--permission")
    a.add_argument("--local-file"); a.add_argument("--force", action="store_true")
    a.add_argument("--max-minutes", type=float, help="only use the first N minutes of the video")
    b = sub.add_parser("ingest-text"); b.add_argument("text", help="any text; every URL in it is ingested")
    b.add_argument("--creator"); b.add_argument("--permission")
    c = sub.add_parser("ingest-file"); c.add_argument("path")
    d = sub.add_parser("post"); d.add_argument("--backend")
    sub.add_parser("status")
    sub.add_parser("watch", help="download + transcribe new uploads from channels.txt")
    args = ap.parse_args(argv)
    cfg = load_config()
    gh_out = os.environ.get("GITHUB_OUTPUT")

    def emit(k, v):
        if gh_out:
            with open(gh_out, "a") as f:
                f.write(f"{k}={v}\n")

    if args.cmd == "ingest":
        added = ingest(args.url, cfg, args.creator, args.permission, args.local_file, args.force, args.max_minutes)
        emit("added", len(added))
    elif args.cmd in ("ingest-text", "ingest-file"):
        text = Path(args.path).read_text() if args.cmd == "ingest-file" else args.text
        total, errors = 0, []
        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue
            for url in URL_RE.findall(line):
                try:
                    total += len(ingest(url.rstrip(").,>"), cfg, getattr(args, "creator", None),
                                        getattr(args, "permission", None)))
                except Exception as e:  # noqa: BLE001
                    log("INGEST FAILED", url, e)
                    errors.append(f"{url}: {e}")
        emit("added", total)
        emit("errors", json.dumps(errors)[:900])
        if errors and total == 0:
            sys.exit(1)
    elif args.cmd == "post":
        res = post(cfg, args.backend)
        emit("low_queue", str(low_queue(cfg)).lower())
        emit("ready", len(Q.ready(Q.load())))
        if any("error" in r for r in res):
            sys.exit(1)
    elif args.cmd == "watch":
        from .watch import run
        done, fallback = run()
        emit("new", len(done))
        emit("fallback", str(fallback).lower())
        emit("titles", json.dumps(done)[:900])
    elif args.cmd == "status":
        q = Q.load()
        print(json.dumps(Q.summary(q), indent=2))
        for i in Q.ready(q)[:10]:
            print(" ready:", i["file"], "|", i["caption"].splitlines()[0][:70])


if __name__ == "__main__":
    main()
