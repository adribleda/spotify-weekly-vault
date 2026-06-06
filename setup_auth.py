"""
spotify-weekly-vault setup
--------------------------
Run once to authorize Spotify and print, or optionally upload, the GitHub
Actions secrets used by the automation.
"""

from __future__ import annotations

import argparse
import getpass
import json
import secrets
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, HTTPServer


REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "user-read-recently-played playlist-read-private playlist-modify-public playlist-modify-private"
TOKEN_URL = "https://accounts.spotify.com/api/token"


def exchange_code_for_tokens(client_id: str, client_secret: str, code: str) -> dict:
    credentials = b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read())


def build_auth_url(client_id: str, state: str) -> str:
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
        }
    )
    return f"https://accounts.spotify.com/authorize?{params}"


def wait_for_callback(expected_state: str, timeout: int = 180) -> str:
    result = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            return

        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            if "error" in params:
                result["error"] = params["error"][0]
            elif params.get("state", [""])[0] != expected_state:
                result["error"] = "Invalid state returned by Spotify."
            elif "code" not in params:
                result["error"] = "Spotify callback did not include a code."
            else:
                result["code"] = params["code"][0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            message = (
                "<h1>Listo</h1><p>Ya puedes volver al terminal.</p>"
                if "code" in result
                else "<h1>Error</h1><p>Vuelve al terminal para ver el detalle.</p>"
            )
            self.wfile.write(
                f"<!doctype html><html lang='es'><meta charset='utf-8'>{message}</html>".encode("utf-8")
            )

    try:
        server = HTTPServer(("127.0.0.1", 8888), CallbackHandler)
    except OSError as exc:
        raise RuntimeError(
            f"Could not start the local callback server on {REDIRECT_URI}. "
            "Close anything using port 8888 and run this script again."
        ) from exc

    timer = threading.Timer(timeout, server.shutdown)
    timer.start()
    try:
        server.handle_request()
    finally:
        timer.cancel()
        server.server_close()

    if "code" in result:
        return result["code"]
    if "error" in result:
        raise RuntimeError(result["error"])
    raise RuntimeError("Timed out waiting for Spotify authorization.")


def extract_playlist_id(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if "open.spotify.com/playlist/" in value:
        parsed = urllib.parse.urlparse(value)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "playlist":
            return parts[1]
    if value.startswith("spotify:playlist:"):
        return value.split(":")[-1]
    return value


def gh_secret_set(repo: str, name: str, value: str) -> None:
    subprocess.run(
        ["gh", "secret", "set", name, "-R", repo],
        input=value.encode("utf-8"),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def maybe_upload_secrets(repo: str, values: dict) -> bool:
    if not repo:
        return False
    if not shutil.which("gh"):
        print("\nGitHub CLI ('gh') is not installed, so I cannot upload secrets automatically.")
        return False

    print(f"\nUploading secrets to {repo} with GitHub CLI...")
    try:
        for name, value in values.items():
            gh_secret_set(repo, name, value)
            print(f"  set {name}")
        subprocess.run(["gh", "workflow", "enable", "weekly.yml", "-R", repo], check=False)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
        print(f"\nCould not upload all secrets with gh: {detail}")
        return False

    print("Secrets uploaded. The workflow is enabled if GitHub allowed it.")
    return True


def print_manual_values(values: dict) -> None:
    print()
    print("=" * 64)
    print("GitHub Actions secrets")
    print("=" * 64)
    for name, value in values.items():
        print(f"{name}={value}")
    print()
    print("Add each value as a separate repository secret in GitHub.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Authorize Spotify for spotify-weekly-vault.")
    parser.add_argument(
        "--github-repo",
        metavar="OWNER/REPO",
        help="Optional. Upload secrets with GitHub CLI, e.g. adribleda/spotify-weekly-vault.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print()
    print("=" * 64)
    print("spotify-weekly-vault setup")
    print("=" * 64)
    print()
    print("Spotify Developer App must include this Redirect URI:")
    print(f"  {REDIRECT_URI}")
    print()

    client_id = input("Spotify Client ID: ").strip()
    client_secret = getpass.getpass("Spotify Client Secret: ").strip()
    playlist = input("Spotify playlist link or ID: ").strip()
    playlist_id = extract_playlist_id(playlist)

    if not client_id or not client_secret or not playlist_id:
        print("\nERROR: Client ID, Client Secret and playlist are required.")
        return 1

    state = secrets.token_hex(16)
    auth_url = build_auth_url(client_id, state)

    print("\nOpening Spotify authorization in your browser...")
    print("If it does not open, paste this URL in your browser:")
    print(auth_url)
    webbrowser.open(auth_url)

    try:
        code = wait_for_callback(state)
        tokens = exchange_code_for_tokens(client_id, client_secret, code)
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"\nERROR: {exc}")
        return 1

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("\nERROR: Spotify did not return a refresh token. Re-run setup and approve every permission.")
        return 1

    values = {
        "SPOTIFY_CLIENT_ID": client_id,
        "SPOTIFY_CLIENT_SECRET": client_secret,
        "SPOTIFY_REFRESH_TOKEN": refresh_token,
        "SPOTIFY_PLAYLIST_ID": playlist_id,
    }

    uploaded = maybe_upload_secrets(args.github_repo, values)
    if not uploaded:
        print_manual_values(values)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
