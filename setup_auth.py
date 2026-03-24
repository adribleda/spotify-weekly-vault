"""
spotify-weekly-vault — First-time setup
----------------------------------------
Run this script ONCE on your computer to get your Spotify refresh token.
After that, everything runs automatically in the cloud.

Requirements: Python 3.8+ (no extra installs needed)

Usage:
    python setup_auth.py
"""

import os
import sys
import json
import webbrowser
import urllib.parse
import urllib.request
import http.server
import threading
import secrets
from base64 import b64encode


# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

REDIRECT_URI = "http://localhost:8888/callback"
SCOPES       = "user-read-recently-played playlist-modify-public playlist-modify-private"
PORT         = 8888


# ─────────────────────────────────────────────
# LOCAL SERVER (catches Spotify's redirect)
# ─────────────────────────────────────────────

auth_code  = None
auth_error = None

class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code, auth_error

        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            auth_code = params["code"][0]
            message   = "✅ Authorization successful! You can close this tab."
        elif "error" in params:
            auth_error = params["error"][0]
            message    = f"❌ Authorization failed: {auth_error}. You can close this tab."
        else:
            message = "⚠️ Unexpected response. You can close this tab."

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            f"<html><body style='font-family:sans-serif;padding:40px'>"
            f"<h2>{message}</h2>"
            f"<p>Return to your terminal to continue.</p>"
            f"</body></html>".encode()
        )

    def log_message(self, format, *args):
        pass   # Suppress noisy server logs


def start_server():
    server = http.server.HTTPServer(("localhost", PORT), CallbackHandler)
    server.handle_request()   # Handle exactly one request, then stop


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
    print("  • A Spotify Developer app created at https://developer.spotify.com")
    print("  • Added 'http://localhost:8888/callback' as a Redirect URI in that app")
    print()
    print("(See README.md → Step 2 for detailed instructions)")
    print()

    # ── Get credentials ──────────────────────────────────────────
    client_id     = input("Paste your Client ID:     ").strip()
    client_secret = input("Paste your Client Secret: ").strip()

    if not client_id or not client_secret:
        print("\n❌  Client ID and Client Secret cannot be empty.")
        sys.exit(1)

    # ── Build authorization URL ───────────────────────────────────
    state  = secrets.token_hex(16)   # CSRF protection
    params = urllib.parse.urlencode({
        "client_id":     client_id,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES,
        "state":         state,
    })
    auth_url = f"https://accounts.spotify.com/authorize?{params}"

    # ── Start local server in background ─────────────────────────
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # ── Open browser ──────────────────────────────────────────────
    print("\n🌐  Opening your browser to authorize Spotify access...")
    print(f"   (If it doesn't open, visit this URL manually:\n   {auth_url})\n")
    webbrowser.open(auth_url)

    # ── Wait for callback ─────────────────────────────────────────
    print("⏳  Waiting for you to authorize in the browser...")
    server_thread.join(timeout=120)

    if auth_error:
        print(f"\n❌  Spotify returned an error: {auth_error}")
        sys.exit(1)

    if not auth_code:
        print("\n❌  Timed out waiting for authorization. Please try again.")
        sys.exit(1)

    # ── Exchange code for tokens ──────────────────────────────────
    try:
        tokens = exchange_code_for_tokens(client_id, client_secret, auth_code)
    except Exception as e:
        print(f"\n❌  Failed to get tokens from Spotify: {e}")
        sys.exit(1)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("\n❌  Spotify did not return a refresh token. Check your app's scopes.")
        sys.exit(1)

    # ── Print results ─────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  ✅  SUCCESS! Here are your secrets for GitHub:")
    print("=" * 60)
    print()
    print(f"  SPOTIFY_CLIENT_ID       →  {client_id}")
    print(f"  SPOTIFY_CLIENT_SECRET   →  {client_secret}")
    print(f"  SPOTIFY_REFRESH_TOKEN   →  {refresh_token}")
    print(f"  SPOTIFY_PLAYLIST_ID     →  4DKniCfecXgSOs550jjYu6")
    print()
    print("⚠️   Copy these values now — keep them PRIVATE.")
    print("    Never paste them in the code or share them publicly.")
    print()
    print("Next step: Go to README.md → Step 4 to add these to GitHub Secrets.")
    print()


if __name__ == "__main__":
    main()
