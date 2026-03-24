"""
spotify-weekly-vault — First-time setup
----------------------------------------
Run this script ONCE on your computer to get your Spotify refresh token.
After that, everything runs automatically in the cloud.

Requirements: Python 3.8+ (no extra installs needed)

Usage:
    python3 setup_auth.py   (Mac/Linux)
    python setup_auth.py    (Windows)
"""

import sys
import json
import webbrowser
import urllib.parse
import urllib.request
import secrets
from base64 import b64encode


# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES       = "user-read-recently-played playlist-read-private playlist-modify-public playlist-modify-private"


# ─────────────────────────────────────────────
# TOKEN EXCHANGE
# ─────────────────────────────────────────────

def exchange_code_for_tokens(client_id, client_secret, code):
    credentials = b64encode(f"{client_id}:{client_secret}".encode()).decode()

    data = urllib.parse.urlencode({
        "grant_type":   "authorization_code",
        "code":         code,
        "redirect_uri": REDIRECT_URI,
    }).encode()

    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data    = data,
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        method = "POST",
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read())


# ─────────────────────────────────────────────
# MAIN SETUP FLOW
# ─────────────────────────────────────────────

def main():
    print()
    print("=" * 60)
    print("  spotify-weekly-vault — First-time setup")
    print("=" * 60)
    print()
    print("This script will:")
    print("  1. Ask for your Spotify app credentials")
    print("  2. Open your browser to authorize access")
    print("  3. Give you a REFRESH TOKEN to store in GitHub")
    print()
    print("Before continuing, make sure you have:")
    print("  - A Spotify Developer app created at https://developer.spotify.com")
    print("  - Added 'http://127.0.0.1:8888/callback' as a Redirect URI in that app")
    print()
    print("(See README.md -> Step 2 for detailed instructions)")
    print()

    # -- Get credentials
    client_id     = input("Paste your Client ID:     ").strip()
    client_secret = input("Paste your Client Secret: ").strip()

    if not client_id or not client_secret:
        print("\n[ERROR] Client ID and Client Secret cannot be empty.")
        sys.exit(1)

    # -- Build authorization URL
    state  = secrets.token_hex(16)
    params = urllib.parse.urlencode({
        "client_id":     client_id,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES,
        "state":         state,
    })
    auth_url = f"https://accounts.spotify.com/authorize?{params}"

    # -- Open browser
    print()
    print("-" * 60)
    print("  STEP A - Authorize in your browser")
    print("-" * 60)
    print()

    # Try to open the browser automatically, but always show the URL
    # as a fallback (webbrowser.open fails silently on WSL, some Linux
    # desktops, headless environments, etc.)
    browser_opened = False
    try:
        browser_opened = webbrowser.open(auth_url)
    except Exception:
        pass

    if browser_opened:
        print("Opening Spotify authorization in your browser...")
    else:
        print("Could not open your browser automatically.")
        print("No worries — just copy and paste this URL into your browser:\n")

    print()
    print(f"  {auth_url}")
    print()
    print("  1. Open that link (if it didn't open automatically)")
    print("     and click 'Agree' on the Spotify page.")
    print()
    print("  2. Your browser will then show an error page saying")
    print("     'This site can't be reached'. That is NORMAL.")
    print()
    print("  3. Look at the ADDRESS BAR at the top of your browser.")
    print("     You will see a long URL starting with:")
    print("     http://127.0.0.1:8888/callback?code=...")
    print()
    print("  4. Copy that ENTIRE URL from the address bar.")
    print()
    print("-" * 60)
    print("  STEP B - Paste the URL here")
    print("-" * 60)
    print()

    callback_url = input("Paste the full URL from your browser here: ").strip()

    if not callback_url:
        print("\n[ERROR] No URL provided. Please try again.")
        sys.exit(1)

    # -- Extract the authorization code
    try:
        parsed     = urllib.parse.urlparse(callback_url)
        url_params = urllib.parse.parse_qs(parsed.query)
    except Exception:
        print("\n[ERROR] That doesn't look like a valid URL. Please try again.")
        sys.exit(1)

    if "error" in url_params:
        print(f"\n[ERROR] Spotify returned an error: {url_params['error'][0]}")
        print("Make sure you clicked 'Agree' on the Spotify page.")
        sys.exit(1)

    if "code" not in url_params:
        print("\n[ERROR] Could not find the authorization code in that URL.")
        print("Make sure you copied the full URL from the address bar,")
        print("not the authorization URL from the terminal.")
        sys.exit(1)

    auth_code = url_params["code"][0]
    print("\n[OK] Got the authorization code.")

    # -- Exchange code for tokens
    print("Getting your refresh token from Spotify...")
    try:
        tokens = exchange_code_for_tokens(client_id, client_secret, auth_code)
    except Exception as e:
        print(f"\n[ERROR] Failed to get tokens from Spotify: {e}")
        sys.exit(1)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("\n[ERROR] Spotify did not return a refresh token.")
        print("Make sure your app has the correct scopes and Redirect URI.")
        sys.exit(1)

    # -- Print results
    print()
    print("=" * 60)
    print("  SUCCESS! Here are your secrets for GitHub:")
    print("=" * 60)
    print()
    print(f"  SPOTIFY_CLIENT_ID       ->  {client_id}")
    print(f"  SPOTIFY_CLIENT_SECRET   ->  {client_secret}")
    print(f"  SPOTIFY_REFRESH_TOKEN   ->  {refresh_token}")
    print( "  SPOTIFY_PLAYLIST_ID     ->  (your playlist ID — see README Step 4)")
    print()
    print("Copy these values now and keep them PRIVATE.")
    print("Never paste them in the code or share them publicly.")
    print()
    print("Next step: Go to README.md -> Step 4 to add these to GitHub Secrets.")
    print()


if __name__ == "__main__":
    main()
