# Clip Autopilot

Give it a video URL → it downloads the video, transcribes it, picks the best 30-40 second moments, renders vertical 1080×1920 clips with burned-in captions, and posts one to TikTok every day. Runs entirely on **free GitHub Actions**. Nothing runs on your computer.

```
 you: open an issue with a URL
        │
        ▼
 [Make clips from a URL]  yt-dlp → whisper transcript → pick moments → ffmpeg 9:16 + captions
        │                  clips stored on the "clip-queue" release, listed in queue.json
        ▼
 [Post next clip]  daily at 5:17pm PT → TikTok → delete posted clip → warns you when < 3 days left
```

## Feeding it videos (the only thing you ever do)

- **Easiest:** open a new issue in this repo (GitHub app works) and paste the URL as the title. It comments back how many clips it queued and closes itself.
- Or: **Actions → Make clips from a URL → Run workflow**, paste the URL (optionally creator + permission note).
- Or: add URLs to `urls.txt`, one per line.

The same URL is never processed twice. Each video gives roughly one clip per 1.5 minutes, up to 6.

## One-time setup (~30 min)

### 1. Put this on GitHub
1. Create a free GitHub account and a **new public repository** (public = unlimited free Actions minutes; clips are publicly downloadable from the release until posted).
2. Upload everything in this folder, including the hidden `.github` folder. Easiest: GitHub Desktop, or
   ```
   git init && git add -A && git commit -m init
   git remote add origin https://github.com/YOU/REPO.git && git push -u origin main
   ```
3. **Settings → Pages →** Deploy from branch `main`, folder `/docs`. Your site is `https://YOU.github.io/REPO/`.
4. **Settings → Actions → General → Workflow permissions →** Read and write.

### 2. Make your TikTok developer app (free)
1. Go to developers.tiktok.com, log in, **Manage apps → Connect an app**.
2. Fill in: Website `https://YOU.github.io/REPO/`, Terms `…/terms.html`, Privacy `…/privacy.html`.
3. Add products **Login Kit** (redirect URI `https://YOU.github.io/REPO/callback.html`) and **Content Posting API** with **Direct Post** turned on. Scopes: `user.info.basic`, `video.upload`, `video.publish`.
4. Submit for review. After approval, apply for the **Content Posting API audit** (in the app page). **Until the audit passes, TikTok forces every API post to private ("only me")** and your account must be set to private while posting. The bot handles this automatically: it posts privately now and switches to public the day TikTok allows it.

### 3. Connect your account (once a year)
On your computer (Python 3, no installs needed):
```
python3 scripts/tiktok_auth.py CLIENT_KEY CLIENT_SECRET https://YOU.github.io/REPO/callback.html
```
Open the link, authorize, paste back the page URL. It prints a refresh token (valid ~365 days; the Actions log warns you 30 days before it expires).

### 4. Add repo secrets (Settings → Secrets and variables → Actions)
| Secret | Value |
|---|---|
| `TIKTOK_CLIENT_KEY` | from the developer portal |
| `TIKTOK_CLIENT_SECRET` | from the developer portal |
| `TIKTOK_REFRESH_TOKEN` | from step 3 |
| `YTDLP_COOKIES` *(optional)* | Netscape cookies.txt for YouTube, only if YouTube blocks GitHub's servers ("Sign in to confirm you're not a bot"). Use a throwaway account. |

### 5. Test
- **Actions → Post next clip → Run workflow →** backend `dry_run` (posts nothing, checks the plumbing).
- Open an issue with a short video URL; check the clips on the `clip-queue` release.

## Public posts before the audit
Swap the posting service without code changes: **Settings → Secrets and variables → Actions → Variables →** `CLIPBOT_BACKEND`:
- `zernio`: Zernio (formerly Late), already audited, free tier ~10 posts/month. Secrets `ZERNIO_API_KEY`, `ZERNIO_TIKTOK_ACCOUNT_ID`. Needs the repo public.
- `upload_post`: Upload-Post (TikTok needs a paid plan). Secrets `UPLOAD_POST_API_KEY`, `UPLOAD_POST_USER`.
- `tiktok` (default): your own app, free and unlimited (≈15 posts/day cap from TikTok).

## Tuning (`config.json`)
- `clips`: length (default 18-58s, aiming for 35s) and how many per video.
- `post.hashtags`, `caption_template`, `credit_template` (credits the creator by default).
- `transcription.whisper_model`: `small` (default), `base` (faster), `medium` (better, slower).
- More posts per day: add more `cron` lines in `.github/workflows/post.yml`.

## Hand-picking moments (optional)
Put `plans/<video-id>.json` in the repo before ingesting to override the automatic picks:
```json
[{"start": 62.0, "end": 98.5, "hook": "The one mistake everyone makes"}]
```

## Rules this follows
Only process videos you own or have permission to repost; the issue/workflow lets you record the permission note, stored per clip in `queue.json`. Posts credit the creator. Volume stays at 1/day by default to avoid spam flags.

## Local run
```
pip install -r requirements.txt   # plus ffmpeg on PATH
CLIPBOT_STORAGE=local python -m clipbot ingest URL
CLIPBOT_STORAGE=local python -m clipbot post --backend dry_run
python -m clipbot status
```

Licenses: Poppins font (SIL OFL, `assets/Poppins-OFL.txt`); OpenCV face model (BSD/Intel license in file header).
