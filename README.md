# 🎵 spotify-weekly-vault

Automatically adds your **3 most-played songs of the week** to a Spotify playlist every Sunday — skipping any tracks already in it.

No apps to install. No subscriptions. 100% free.

---

## How it works

Every Sunday at 20:00 UTC the tool:

1. Looks at everything you've listened to on Spotify in the past 7 days
2. Ranks those songs by how many times you played them
3. Picks the top 3 that aren't already in your chosen playlist
4. Adds them automatically

If a song is already in the playlist, it moves down the ranking until it finds one that isn't.

---

## Setup guide (one-time, ~15 minutes)

### Step 1 — Fork this repository

"Forking" means making your own personal copy of this project on your GitHub account.

1. Make sure you're logged into [github.com](https://github.com)
2. Click the **Fork** button at the top-right of this page
3. Click **Create fork**

You now have your own copy at `github.com/YOUR_USERNAME/spotify-weekly-vault`.

---

### Step 2 — Create a Spotify Developer App

This is how you get permission to connect this tool to your Spotify account. It's free.

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Log in with your normal Spotify account
3. Click **Create app**
4. Fill in the form:
   - **App name**: `weekly-vault` (or any name you like)
   - **App description**: anything, e.g. `Weekly top tracks tool`
   - **Redirect URI**: paste this exactly → `http://localhost:8888/callback`
   - **Which API/SDKs are you planning to use?** → check **Web API** only
   - Check the box to accept the Terms of Service
5. Click **Save**
6. On the next screen, click **Settings**
7. You'll see your **Client ID** — copy it somewhere safe
8. Click **View client secret** — copy that too

> ⚠️ These are like passwords. Don't share them or put them in the code.
---

### Step 3 — Run the setup script on your computer

This script opens your browser, asks you to authorize Spotify, and gives you a **Refresh Token** (a permanent key the tool uses to access your account automatically).

**Requirements:** Python 3.8 or later. Check by opening Terminal (Mac/Linux) or Command Prompt (Windows) and typing:
```
python --version
```
If you see a version number starting with 3, you're good.

**Run the script:**
```bash
python setup_auth.py
```

Follow the prompts:
- Paste your **Client ID** when asked
- Paste your **Client Secret** when asked
- Your browser will open — click **Agree** to authorize
- Come back to the terminal

At the end you'll see something like:
```
SPOTIFY_CLIENT_ID       →  abc123...
SPOTIFY_CLIENT_SECRET   →  xyz789...
SPOTIFY_REFRESH_TOKEN   →  AQD...
SPOTIFY_PLAYLIST_ID     →  4DKniCfecXgSOs550jjYu6
```

**Copy all four values.** You'll need them in the next step.

---

### Step 4 — Add your secrets to GitHub

"Secrets" is GitHub's secure vault for storing passwords and tokens. Your code can use them without anyone being able to see their values — not even you, once saved.

1. Go to your forked repository on GitHub
2. Click **Settings** (top menu of the repo)
3. In the left sidebar, click **Secrets and variables** → **Actions**
4. Click **New repository secret** and add each of the four values:

| Name | Value |
|---|---|
| `SPOTIFY_CLIENT_ID` | Your Client ID from Step 2 |
| `SPOTIFY_CLIENT_SECRET` | Your Client Secret from Step 2 |
| `SPOTIFY_REFRESH_TOKEN` | The token from Step 3 |
| `SPOTIFY_PLAYLIST_ID` | Your playlist ID (or `4DKniCfecXgSOs550jjYu6` if using the default) |

Add them one by one: type the name, paste the value, click **Add secret**.

---

### Step 5 — Test it manually

Before waiting for Sunday, let's make sure everything works.

1. In your repository, click the **Actions** tab
2. On the left, click **Weekly Top Tracks**
3. Click **Run workflow** → **Run workflow**
4. Wait ~30 seconds, then click the run to see the log

You should see something like:
```
✅  Authenticated with Spotify
📊  34 plays recorded this week
➕  Added: Satélites — Baiuca (8 plays)
➕  Added: Quiero — Bad Gyal (5 plays)
➕  Added: Rosa — Vetusta Morla (4 plays)
✅  Done! Added 3 track(s) to your playlist.
```

If you see a ❌ error, here are the most common causes:

| Error message | What to check |
|---|---|
| `Authentication failed` | Your Client ID, Client Secret or Refresh Token are wrong. Re-run `setup_auth.py` to get a new token. |
| `No plays found in the last 7 days` | Your Spotify account needs "Recently Played" history enabled, and plays must have happened while online. |
| `Could not read playlist` | Your `SPOTIFY_PLAYLIST_ID` secret is wrong, or the playlist doesn't belong to your account. |
| `This workflow is disabled` | Go to Actions → Weekly Top Tracks → click **Enable workflow**. |

---

## How to change the playlist

If you want to use a different playlist:

1. Open Spotify → go to the playlist
2. Click the three dots (···) → **Share** → **Copy link to playlist**
3. The link looks like: `https://open.spotify.com/playlist/`**`XXXXXXXXXXXX`**
4. That last part is the ID
5. Go to your GitHub repo → Settings → Secrets → update `SPOTIFY_PLAYLIST_ID`

---

## Schedule

The tool runs every **Sunday at 20:00 UTC**, which is:

| 🌍 Location | 🕐 Winter time | ☀️ Summer time |
|---|---|---|
| 🇪🇸 Spain | 21:00 | 22:00 |
| 🇬🇧 UK | 20:00 | 21:00 |
| 🇺🇸 New York (ET) | 15:00 | 16:00 |
| 🇺🇸 Chicago (CT) | 14:00 | 15:00 |
| 🇺🇸 Denver (MT) | 13:00 | 14:00 |
| 🇺🇸 Los Angeles (PT) | 12:00 | 13:00 |

To change the schedule, edit `.github/workflows/weekly.yml` and update the cron line.
[Crontab.guru](https://crontab.guru) is a handy tool for building cron schedules.

---

## Pausing and resuming

You can pause the automatic Sunday runs at any time — no code changes needed.

**To pause:**
1. Go to your repository on GitHub
2. Click the **Actions** tab (top menu)
3. On the left, click **Weekly Top Tracks**
4. Click the **···** button (top right of the page)
5. Click **Disable workflow**

The script will stop running on Sundays. Your playlist and all your settings stay untouched.

**To resume:**
Follow the same steps and click **Enable workflow** instead.

> You can also run it manually at any time — even while paused — using the **Run workflow** button on that same page.

---

## Troubleshooting

**"No plays found in the last 7 days"**
→ Make sure your Spotify account has "Recently Played" history enabled. Also, plays must have been on a device connected to your account while online.

**"Authentication failed"**
→ Double-check that your `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, and `SPOTIFY_REFRESH_TOKEN` secrets are correct. Re-run `setup_auth.py` to get a fresh refresh token.

**"Could not read playlist"**
→ Check that `SPOTIFY_PLAYLIST_ID` is correct and that the playlist belongs to your account.

**Actions tab shows "This workflow is disabled"**
→ Click the **Enable workflow** button on the Actions page.

---

## Privacy & security

- Your Spotify credentials are stored only in your GitHub repository's encrypted Secrets vault — never in the code
- The tool only requests the minimum permissions it needs: reading your play history and editing one playlist
- No data is sent anywhere except directly to Spotify's official API
- You can revoke access at any time at [spotify.com/account/apps](https://www.spotify.com/account/apps)

---

## Tech stack

- **Language**: Python 3 (standard library + `requests`)
- **Automation**: GitHub Actions (free tier)
- **API**: [Spotify Web API](https://developer.spotify.com/documentation/web-api)

---

## License

MIT — free to use, fork, and modify.
