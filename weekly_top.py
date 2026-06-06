"""
spotify-weekly-vault
--------------------
Collects Spotify recently-played history during the week, then adds the top
new tracks to a playlist. Designed for GitHub Actions, but runnable locally.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


SPOTIFY_API = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"
DEFAULT_DATA_FILE = "data/recent_plays.json"


class ConfigError(Exception):
    pass


class SpotifyError(Exception):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}.") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}.")
    return value


def get_config(require_playlist: bool = False) -> dict:
    required = [
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "SPOTIFY_REFRESH_TOKEN",
    ]
    if require_playlist:
        required.append("SPOTIFY_PLAYLIST_ID")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise ConfigError("Missing GitHub secret(s): " + ", ".join(missing))

    return {
        "client_id": os.environ["SPOTIFY_CLIENT_ID"].strip(),
        "client_secret": os.environ["SPOTIFY_CLIENT_SECRET"].strip(),
        "refresh_token": os.environ["SPOTIFY_REFRESH_TOKEN"].strip(),
        "playlist_id": os.environ.get("SPOTIFY_PLAYLIST_ID", "").strip(),
        "tracks_to_add": env_int("SPOTIFY_TRACKS_TO_ADD", 3),
        "lookback_days": env_int("SPOTIFY_LOOKBACK_DAYS", 7),
        "retention_days": env_int("SPOTIFY_HISTORY_RETENTION_DAYS", 14),
        "data_file": Path(os.environ.get("SPOTIFY_DATA_FILE", DEFAULT_DATA_FILE)),
    }


def request_json(method: str, url: str, token: str | None = None, body: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}

    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)

    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < 2:
                retry_after = int(exc.headers.get("Retry-After", "5"))
                print(f"Spotify rate limit hit. Retrying in {retry_after}s...")
                time.sleep(retry_after)
                continue
            raise SpotifyError(f"{method} {url} failed with {exc.code}: {raw}") from exc
        except urllib.error.URLError as exc:
            if attempt < 2:
                time.sleep(2 + attempt)
                continue
            raise SpotifyError(f"{method} {url} failed: {exc.reason}") from exc

    raise SpotifyError(f"{method} {url} failed after retries")


def get_access_token(config: dict) -> str:
    credentials = b64encode(f"{config['client_id']}:{config['client_secret']}".encode()).decode()
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": config["refresh_token"],
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
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise SpotifyError(f"Authentication failed with {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise SpotifyError(f"Authentication failed: {exc.reason}") from exc

    token = payload.get("access_token")
    if not token:
        raise SpotifyError("Spotify did not return an access token.")
    return token


def load_history(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "plays": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON.") from exc
    if not isinstance(data.get("plays"), list):
        raise ConfigError(f"{path} must contain a 'plays' list.")
    return data


def save_history(path: Path, history: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    history["updated_at"] = iso_z(utc_now())
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def latest_play_ms(history: dict, retention_days: int) -> int:
    latest = None
    for play in history.get("plays", []):
        played_at = play.get("played_at")
        if played_at and (latest is None or played_at > latest):
            latest = played_at

    if latest:
        # Back up slightly. The collector deduplicates, so overlap is harmless.
        return max(0, int(parse_iso(latest).timestamp() * 1000) - 1000)

    since = utc_now() - timedelta(days=retention_days)
    return int(since.timestamp() * 1000)


def normalize_play(item: dict) -> dict | None:
    track = item.get("track") or {}
    uri = track.get("uri")
    played_at = item.get("played_at")
    if not uri or not played_at:
        return None
    artists = [artist.get("name", "") for artist in track.get("artists", []) if artist.get("name")]
    return {
        "played_at": iso_z(parse_iso(played_at)),
        "uri": uri,
        "name": track.get("name") or "Unknown track",
        "artist": ", ".join(artists) or "Unknown artist",
    }


def fetch_recently_played(token: str, after_ms: int) -> list[dict]:
    params = urllib.parse.urlencode({"limit": 50, "after": after_ms})
    data = request_json("GET", f"{SPOTIFY_API}/me/player/recently-played?{params}", token=token)
    plays = []
    for item in data.get("items", []):
        play = normalize_play(item)
        if play:
            plays.append(play)
    return plays


def merge_and_trim(history: dict, new_plays: list[dict], retention_days: int) -> tuple[dict, int, bool]:
    cutoff = utc_now() - timedelta(days=retention_days)
    by_key = {}
    old_keys = set()
    old_plays = []

    for play in history.get("plays", []):
        try:
            played_at = parse_iso(play["played_at"])
            key = f"{play['played_at']}|{play['uri']}"
        except (KeyError, ValueError):
            continue
        if played_at >= cutoff:
            by_key[key] = play
            old_keys.add(key)
            old_plays.append(play)

    added = 0
    for play in new_plays:
        try:
            played_at = parse_iso(play["played_at"])
            key = f"{play['played_at']}|{play['uri']}"
        except (KeyError, ValueError):
            continue
        if played_at < cutoff:
            continue
        if key not in old_keys:
            added += 1
        by_key[key] = play

    plays = sorted(by_key.values(), key=lambda p: p["played_at"])
    old_plays = sorted(old_plays, key=lambda p: p["played_at"])
    changed = plays != old_plays or len(old_plays) != len(history.get("plays", []))
    return {"version": 1, "plays": plays}, added, changed


def collect(config: dict, token: str) -> tuple[dict, int]:
    path = config["data_file"]
    history = load_history(path)
    after_ms = latest_play_ms(history, config["retention_days"])
    new_plays = fetch_recently_played(token, after_ms)
    updated, added, changed = merge_and_trim(history, new_plays, config["retention_days"])
    if changed:
        save_history(path, updated)
    print(f"Collected {added} new play(s). Stored {len(updated['plays'])} play(s) in {path}.")
    return updated, added


def get_playlist_track_uris(token: str, playlist_id: str) -> set[str]:
    url = (
        f"{SPOTIFY_API}/playlists/{urllib.parse.quote(playlist_id)}/items"
        "?fields=items(track(uri)),next&limit=100"
    )
    uris = set()
    while url:
        data = request_json("GET", url, token=token)
        for item in data.get("items", []):
            uri = (item.get("track") or {}).get("uri")
            if uri:
                uris.add(uri)
        url = data.get("next")
    return uris


def add_tracks_to_playlist(token: str, playlist_id: str, uris: list[str]) -> None:
    request_json(
        "POST",
        f"{SPOTIFY_API}/playlists/{urllib.parse.quote(playlist_id)}/items",
        token=token,
        body={"uris": uris, "position": 0},
    )


def weekly_candidates(history: dict, lookback_days: int) -> tuple[list[tuple[str, int]], dict[str, str]]:
    since = utc_now() - timedelta(days=lookback_days)
    counter = Counter()
    info = {}
    for play in history.get("plays", []):
        try:
            played_at = parse_iso(play["played_at"])
        except (KeyError, ValueError):
            continue
        if played_at < since:
            continue
        uri = play["uri"]
        counter[uri] += 1
        info[uri] = f"{play.get('name', 'Unknown track')} — {play.get('artist', 'Unknown artist')}"
    return counter.most_common(), info


def add_weekly_top(config: dict, token: str, dry_run: bool = False) -> int:
    history = load_history(config["data_file"])
    ranked, info = weekly_candidates(history, config["lookback_days"])
    if not ranked:
        print(f"No collected plays found in the last {config['lookback_days']} day(s). Nothing to add.")
        return 0

    print("\nWeekly ranking:")
    for index, (uri, count) in enumerate(ranked[:10], start=1):
        label = info.get(uri, uri)
        print(f"  #{index} {label} ({count} play{'s' if count != 1 else ''})")

    existing = get_playlist_track_uris(token, config["playlist_id"])
    selected = []
    print(f"\nPlaylist has {len(existing)} existing track(s). Selecting new tracks:")
    for uri, count in ranked:
        label = info.get(uri, uri)
        if uri in existing:
            print(f"  Skip: {label} is already in the playlist.")
            continue
        selected.append(uri)
        print(f"  Add: {label} ({count} play{'s' if count != 1 else ''})")
        if len(selected) >= config["tracks_to_add"]:
            break

    if not selected:
        print("\nAll ranked tracks are already in the playlist. Nothing to add.")
        return 0

    if dry_run:
        print(f"\nDry run: would add {len(selected)} track(s).")
        return len(selected)

    add_tracks_to_playlist(token, config["playlist_id"], selected)
    print(f"\nDone. Added {len(selected)} track(s) to the playlist.")
    return len(selected)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Spotify plays and update your weekly playlist.")
    parser.add_argument(
        "mode",
        nargs="?",
        default="run",
        choices=["collect", "add", "run"],
        help="'collect' stores recent plays, 'add' updates the playlist from stored plays, 'run' does both.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the tracks that would be added, without adding.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("=" * 60)
    print("spotify-weekly-vault")
    print(f"Mode: {args.mode} | Time: {iso_z(utc_now())}")
    print("=" * 60)

    try:
        config = get_config(require_playlist=args.mode in {"add", "run"})
        token = get_access_token(config)
        print("Authenticated with Spotify.")

        if args.mode in {"collect", "run"}:
            collect(config, token)
        if args.mode in {"add", "run"}:
            add_weekly_top(config, token, dry_run=args.dry_run)
    except (ConfigError, SpotifyError) as exc:
        print(f"ERROR: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
