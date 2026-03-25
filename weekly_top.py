"""
spotify-weekly-vault
--------------------
Every Sunday, finds your top 3 most-played tracks of the week
and adds them to a playlist — skipping any already there.

All credentials are read from environment variables (never hardcoded).
"""

import os
import sys
import requests
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from collections import Counter


# ─────────────────────────────────────────────
# 1. AUTHENTICATION
# ─────────────────────────────────────────────

def get_access_token():
    """
    Uses the refresh token (stored as a GitHub Secret) to get
    a fresh, short-lived access token from Spotify.
    """
    client_id     = os.environ["SPOTIFY_CLIENT_ID"]
    client_secret = os.environ["SPOTIFY_CLIENT_SECRET"]
    refresh_token = os.environ["SPOTIFY_REFRESH_TOKEN"]

    credentials = b64encode(f"{client_id}:{client_secret}".encode()).decode()

    response = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {credentials}"},
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=15,
    )

    # ── DIAGNOSTIC: print what Spotify actually returned ──
    if not response.ok:
        print(f"[DIAG] Token request failed {response.status_code}: {response.text}")
    else:
        data = response.json()
        granted_scopes = data.get("scope", "(no scope field returned)")
        print(f"[DIAG] Token granted. Scopes: {granted_scopes}")

    response.raise_for_status()
    return response.json()["access_token"]


# ─────────────────────────────────────────────
# 2. GET THIS WEEK'S PLAYS
# ─────────────────────────────────────────────

def get_recently_played(token):
    """
    Fetches up to 50 of your most recent Spotify plays and
    filters only those from the last 7 days.
    Returns a list of dicts: {uri, name, artist}
    """
    week_ago  = datetime.now(timezone.utc) - timedelta(days=7)
    after_ms  = int(week_ago.timestamp() * 1000)

    headers  = {"Authorization": f"Bearer {token}"}
    url      = (
        "https://api.spotify.com/v1/me/player/recently-played"
        f"?limit=50&after={after_ms}"
    )

    response = requests.get(url, headers=headers, timeout=15)
    if not response.ok:
        print(f"[DIAG] recently-played failed {response.status_code}: {response.text}")
    response.raise_for_status()
    data = response.json()

    tracks = []
    for item in data.get("items", []):
        played_at = datetime.fromisoformat(item["played_at"].replace("Z", "+00:00"))
        if played_at >= week_ago:
            tracks.append({
                "uri":    item["track"]["uri"],
                "name":   item["track"]["name"],
                "artist": item["track"]["artists"][0]["name"],
            })

    return tracks


# ─────────────────────────────────────────────
# 3. GET CURRENT PLAYLIST CONTENTS
# ─────────────────────────────────────────────

def get_playlist_track_uris(token, playlist_id):
    """
    Returns a set of all track URIs already in your playlist.
    Handles playlists longer than 100 songs automatically (pagination).
    """
    headers = {"Authorization": f"Bearer {token}"}
    uris    = set()
    url     = (
        f"https://api.spotify.com/v1/playlists/{playlist_id}/items"
        "?fields=items(track(uri)),next&limit=100"
    )

    while url:
        response = requests.get(url, headers=headers, timeout=15)

        # ── DIAGNOSTIC: print Spotify's exact error body ──
        if not response.ok:
            print(f"[DIAG] Playlist read failed {response.status_code}: {response.text}")

        response.raise_for_status()
        data = response.json()

        for item in data.get("items", []):
            if item.get("track"):
                uris.add(item["track"]["uri"])

        url = data.get("next")

    return uris


# ─────────────────────────────────────────────
# 4. ADD TRACKS TO PLAYLIST
# ─────────────────────────────────────────────

def add_tracks_to_playlist(token, playlist_id, track_uris):
    """
    Inserts the given track URIs at the TOP of the playlist.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    response = requests.post(
        f"https://api.spotify.com/v1/playlists/{playlist_id}/items",
        headers=headers,
        json={"uris": track_uris, "position": 0},
        timeout=15,
    )
    if not response.ok:
        print(f"[DIAG] Add tracks failed {response.status_code}: {response.text}")
    response.raise_for_status()


# ─────────────────────────────────────────────
# 5. MAIN LOGIC
# ─────────────────────────────────────────────

def main():
    playlist_id = os.environ.get("SPOTIFY_PLAYLIST_ID")
    if not playlist_id:
        print("❌  SPOTIFY_PLAYLIST_ID secret is not set. Add it in GitHub Secrets.")
        sys.exit(1)

    print("=" * 50)
    print("  spotify-weekly-vault")
    print(f"  Run date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 50)

    # Step 1 — Authenticate
    try:
        token = get_access_token()
        print("✅  Authenticated with Spotify")
    except Exception as e:
        print(f"❌  Authentication failed: {e}")
        sys.exit(1)

    # Step 2 — Get this week's plays
    try:
        recent = get_recently_played(token)
    except Exception as e:
        print(f"❌  Could not fetch recent plays: {e}")
        sys.exit(1)

    if not recent:
        print("⚠️   No plays found in the last 7 days. Nothing to do.")
        sys.exit(0)

    print(f"📊  {len(recent)} plays recorded this week")

    # Step 3 — Count plays per track and rank them
    counter    = Counter()
    track_info = {}
    for track in recent:
        counter[track["uri"]] += 1
        track_info[track["uri"]] = f"{track['name']} — {track['artist']}"

    ranked = counter.most_common()

    print("\n  Your weekly ranking:")
    for i, (uri, count) in enumerate(ranked[:10], 1):
        print(f"    #{i}  {track_info[uri]}  ({count} play{'s' if count > 1 else ''})")

    # Step 4 — Get playlist contents
    try:
        playlist_uris = get_playlist_track_uris(token, playlist_id)
    except Exception as e:
        print(f"❌  Could not read playlist: {e}")
        sys.exit(1)

    print(f"\n📋  Playlist currently has {len(playlist_uris)} tracks")

    # Step 5 — Walk down the ranking, skip songs already in playlist
    print("\n  Selecting top 3 new tracks:")
    to_add = []
    for uri, count in ranked:
        if uri in playlist_uris:
            print(f"    ⏭️   Already in playlist — skipping: {track_info[uri]}")
        else:
            to_add.append(uri)
            print(f"    ➕  Selected: {track_info[uri]}  ({count} play{'s' if count > 1 else ''})")

        if len(to_add) == 3:
            break

    if not to_add:
        print("\nℹ️   All your top tracks are already in the playlist. Nothing added.")
        sys.exit(0)

    # Step 6 — Add to playlist
    try:
        add_tracks_to_playlist(token, playlist_id, to_add)
    except Exception as e:
        print(f"❌  Could not add tracks to playlist: {e}")
        sys.exit(1)

    print(f"\n✅  Done! Added {len(to_add)} track(s) to your playlist.")
    print("=" * 50)


if __name__ == "__main__":
    main()
