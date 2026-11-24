"""One-time: get a TikTok refresh token for your own developer app (valid ~1 year).

  python scripts/tiktok_auth.py CLIENT_KEY CLIENT_SECRET REDIRECT_URI

1. It prints a link. Open it, log in with the TikTok account you'll post to, click Authorize.
2. You land on REDIRECT_URI (this repo's GitHub Pages callback page shows the code).
3. Paste the full URL (or just the code) back here.
4. Put the printed refresh token in the repo secret TIKTOK_REFRESH_TOKEN.
"""
import json
import secrets
import sys
import urllib.parse
import urllib.request

SCOPES = "user.info.basic,video.publish,video.upload"


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    key, secret, redirect = sys.argv[1:]
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": key, "scope": SCOPES, "response_type": "code",
        "redirect_uri": redirect, "state": state})
    print("\nOpen this link and authorize:\n\n" + url + "\n")
    got = input("Paste the URL you landed on (or the code): ").strip()
    if got.startswith("http"):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(got).query)
        if qs.get("state", [state])[0] != state:
            sys.exit("state mismatch - start again")
        code = qs["code"][0]
    else:
        code = got
    data = urllib.parse.urlencode({"client_key": key, "client_secret": secret, "code": urllib.parse.unquote(code),
                                   "grant_type": "authorization_code", "redirect_uri": redirect}).encode()
    req = urllib.request.Request("https://open.tiktokapis.com/v2/oauth/token/", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read())
    if "refresh_token" not in j:
        sys.exit(f"failed: {j}")
    print("\nTIKTOK_REFRESH_TOKEN =", j["refresh_token"])
    print(f"(valid for {j.get('refresh_expires_in', 0) // 86400} days; scopes: {j.get('scope')})")


if __name__ == "__main__":
    main()
