/**
 * weekly-vault — Cloudflare Worker
 * Adds your 3 most-played Spotify tracks to a playlist every Sunday.
 *
 * Required secrets (wrangler secret put):
 *   SPOTIFY_CLIENT_ID
 *   SPOTIFY_CLIENT_SECRET
 *   SESSION_SECRET      — any random string ≥ 32 chars
 *   ENCRYPTION_KEY      — 64-char hex string (32 bytes), run: openssl rand -hex 32
 *
 * Required env vars (wrangler.toml [vars]):
 *   REDIRECT_URI        — e.g. https://weekly-vault.YOUR_SUBDOMAIN.workers.dev/auth/callback
 *
 * Required KV namespace (wrangler.toml [[kv_namespaces]]):
 *   USERS_KV
 */

// ─────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────

const SPOTIFY_AUTH_URL  = 'https://accounts.spotify.com/authorize';
const SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token';
const SPOTIFY_API       = 'https://api.spotify.com/v1';
const SCOPES            = 'user-read-recently-played playlist-modify-public playlist-modify-private playlist-read-private';
const TRACKS_TO_ADD     = 3;
const DAYS_LOOKBACK     = 7;

// ─────────────────────────────────────────────
// Main Handler
// ─────────────────────────────────────────────

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    try {
      switch (url.pathname) {
        case '/':               return renderLanding();
        case '/auth/start':    return startAuth(request, env);
        case '/auth/callback': return handleCallback(request, env);
        case '/setup':         return renderSetup(request, env);
        case '/dashboard':     return renderDashboard(request, env);
        case '/api/playlists': return apiGetPlaylists(request, env);
        case '/api/playlist':
          if (request.method === 'POST') return apiSavePlaylist(request, env);
          break;
        case '/api/delete':
          if (request.method === 'POST') return apiDeleteAccount(request, env);
          break;
      }
      return new Response('Not found', { status: 404 });
    } catch (err) {
      console.error(err);
      return htmlResponse(errorPage('Algo salió mal. Inténtalo de nuevo.'), 500);
    }
  },

  async scheduled(event, env) {
    await runWeeklyJob(env);
  },
};

// ─────────────────────────────────────────────
// Auth Flow
// ─────────────────────────────────────────────

async function startAuth(request, env) {
  const state  = await generateState(env.SESSION_SECRET);
  const params = new URLSearchParams({
    client_id:     env.SPOTIFY_CLIENT_ID,
    response_type: 'code',
    redirect_uri:  env.REDIRECT_URI,
    scope:         SCOPES,
    state,
  });
  return Response.redirect(`${SPOTIFY_AUTH_URL}?${params}`, 302);
}

async function handleCallback(request, env) {
  const url   = new URL(request.url);
  const code  = url.searchParams.get('code');
  const state = url.searchParams.get('state');
  const error = url.searchParams.get('error');

  if (error)           return htmlResponse(errorPage('Cancelaste la autorización de Spotify.'));
  if (!code || !state) return htmlResponse(errorPage('Parámetros inválidos.'));

  const stateOk = await verifyState(state, env.SESSION_SECRET);
  if (!stateOk)        return htmlResponse(errorPage('Sesión expirada. Inténtalo de nuevo.'));

  // Exchange code for tokens
  const tokenRes = await fetch(SPOTIFY_TOKEN_URL, {
    method: 'POST',
    headers: {
      Authorization:  'Basic ' + btoa(`${env.SPOTIFY_CLIENT_ID}:${env.SPOTIFY_CLIENT_SECRET}`),
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: new URLSearchParams({
      grant_type:   'authorization_code',
      code,
      redirect_uri: env.REDIRECT_URI,
    }),
  });

  if (!tokenRes.ok) return htmlResponse(errorPage('Error al conectar con Spotify. Inténtalo de nuevo.'));

  const { access_token, refresh_token } = await tokenRes.json();

  // Get Spotify user ID
  const meRes = await fetch(`${SPOTIFY_API}/me`, {
    headers: { Authorization: `Bearer ${access_token}` },
  });
  if (!meRes.ok) return htmlResponse(errorPage('No se pudo obtener tu perfil de Spotify.'));

  const me     = await meRes.json();
  const userId = me.id;

  // Encrypt refresh token and store
  const encryptedToken = await encrypt(refresh_token, env.ENCRYPTION_KEY);
  await env.USERS_KV.put(
    `user:${userId}`,
    JSON.stringify({
      refreshToken: encryptedToken,
      playlistId:   null,
      displayName:  me.display_name || userId,
      createdAt:    new Date().toISOString(),
    })
  );

  // Set signed session cookie and redirect to setup
  const session = await signValue(userId, env.SESSION_SECRET);
  return new Response(null, {
    status: 302,
    headers: {
      Location:   '/setup',
      'Set-Cookie': `session=${session}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=2592000`,
    },
  });
}

// ─────────────────────────────────────────────
// API Handlers
// ─────────────────────────────────────────────

async function apiGetPlaylists(request, env) {
  const userId = await getSessionUser(request, env);
  if (!userId) return new Response('Unauthorized', { status: 401 });

  const userData = await getUserData(userId, env);
  if (!userData)  return new Response('User not found', { status: 404 });

  const token     = await getAccessToken(userData.refreshToken, env);
  const playlists = [];
  let   nextUrl   = `${SPOTIFY_API}/me/playlists?limit=50`;

  while (nextUrl) {
    const res = await fetch(nextUrl, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) break;
    const data = await res.json();
    playlists.push(...(data.items || []).filter(p => p?.id));
    nextUrl = data.next;
  }

  return new Response(
    JSON.stringify(playlists.map(p => ({ id: p.id, name: p.name }))),
    { headers: { 'Content-Type': 'application/json' } }
  );
}

async function apiSavePlaylist(request, env) {
  const userId = await getSessionUser(request, env);
  if (!userId) return new Response('Unauthorized', { status: 401 });

  const { playlistId } = await request.json();
  if (!playlistId) return new Response('Missing playlistId', { status: 400 });

  const raw = await env.USERS_KV.get(`user:${userId}`);
  if (!raw)  return new Response('User not found', { status: 404 });

  const userData    = JSON.parse(raw);
  userData.playlistId = playlistId;
  await env.USERS_KV.put(`user:${userId}`, JSON.stringify(userData));

  return new Response(JSON.stringify({ ok: true }), {
    headers: { 'Content-Type': 'application/json' },
  });
}

async function apiDeleteAccount(request, env) {
  const userId = await getSessionUser(request, env);
  if (!userId) return Response.redirect('/', 302);

  await env.USERS_KV.delete(`user:${userId}`);

  return new Response(null, {
    status: 302,
    headers: {
      Location:     '/',
      'Set-Cookie': 'session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0',
    },
  });
}

// ─────────────────────────────────────────────
// Page Renderers
// ─────────────────────────────────────────────

function renderLanding() {
  return htmlResponse(`<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Weekly Vault</title>
  <style>${CSS}</style>
</head>
<body>
  <div class="wrap">
    <nav class="nav">
      <div class="nav-dot"></div>
      <span class="nav-wordmark">Weekly Vault</span>
    </nav>

    <section class="hero">
      <p class="eyebrow fade-up">Gratis · Sin instalación · Sin suscripción</p>
      <h1 class="hero-title fade-up d1">Tu semana<br>en música,<br>guardada sola.</h1>
      <p class="hero-sub fade-up d2">Cada domingo, tus 3 canciones más escuchadas llegan a tu playlist. Sin que tengas que hacer nada.</p>
      <a href="/auth/start" class="btn btn-green fade-up d3">Conectar con Spotify</a>
    </section>

    <section class="how">
      <p class="section-label fade-up">Cómo funciona</p>
      <ol class="steps">
        <li class="step fade-up">
          <span class="step-n">01</span>
          <div>
            <p class="step-title">Conectas tu cuenta de Spotify</p>
            <p class="step-desc">Un clic. Spotify te pide permiso con su pantalla habitual. Aceptas. No hace falta crear ninguna cuenta nueva ni instalar nada.</p>
          </div>
        </li>
        <li class="step fade-up d1">
          <span class="step-n">02</span>
          <div>
            <p class="step-title">Eliges una playlist</p>
            <p class="step-desc">La que ya tienes, o creas una nueva. Ahí es donde irán cayendo tus canciones cada semana, siempre arriba del todo.</p>
          </div>
        </li>
        <li class="step fade-up d2">
          <span class="step-n">03</span>
          <div>
            <p class="step-title">Ya está. De verdad.</p>
            <p class="step-desc">Cada domingo analizamos tus escuchas y añadimos el top 3. Si una canción ya está en la playlist, cogemos la siguiente. Sin repeticiones, sin sorpresas.</p>
          </div>
        </li>
      </ol>
    </section>

    <section class="trust fade-up">
      <p class="trust-text">Solo accedemos a tu historial de escucha y a la playlist que elijas. Puedes revocar el acceso en cualquier momento desde <a href="https://www.spotify.com/account/apps" style="color:inherit;text-underline-offset:3px">spotify.com/account/apps</a>.</p>
    </section>
  </div>
</body>
</html>`);
}

async function renderSetup(request, env) {
  const userId = await getSessionUser(request, env);
  if (!userId) return Response.redirect('/', 302);

  const userData    = await getUserData(userId, env);
  const hasPlaylist = userData?.playlistId;
  const buttonText  = hasPlaylist ? 'Guardar cambios' : 'Activar';
  const progressPct = hasPlaylist ? 100 : 66;
  const progressLbl = hasPlaylist ? 'Cambiando playlist' : 'Último paso';

  return htmlResponse(`<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Weekly Vault — Elige tu playlist</title>
  <style>${CSS}</style>
</head>
<body>
  <div class="wrap">
    <nav class="nav">
      <div class="nav-dot"></div>
      <span class="nav-wordmark">Weekly Vault</span>
    </nav>

    <div class="page-flow">
      <div class="progress fade-up">
        <span class="progress-label">${progressLbl}</span>
        <div class="progress-track"><div class="progress-fill" style="width:${progressPct}%"></div></div>
      </div>

      <h1 class="flow-title fade-up d1">¿Dónde guardamos<br>tu colección?</h1>
      <p class="flow-sub fade-up d2">Elige la playlist donde caerán tus canciones cada domingo.</p>

      <div class="select-wrap fade-up d2">
        <select id="playlist" class="select">
          <option value="">Cargando tus playlists…</option>
        </select>
        <span class="select-chevron" aria-hidden="true">▾</span>
      </div>

      <button id="btn-save" class="btn btn-green fade-up d3" disabled>${buttonText}</button>
      <p class="err-msg" id="msg"></p>

      <ul class="reassurance fade-up d4">
        <li>Gratis para siempre</li>
        <li>Sin tarjeta ni instalación</li>
        <li>Puedes parar cuando quieras</li>
      </ul>
    </div>
  </div>

  <script>
    (async () => {
      const sel = document.getElementById('playlist');
      const btn = document.getElementById('btn-save');
      const msg = document.getElementById('msg');
      const currentId = ${JSON.stringify(userData?.playlistId || null)};

      try {
        const res  = await fetch('/api/playlists');
        const list = await res.json();
        sel.innerHTML = '<option value="">— Elige una playlist —</option>' +
          list.map(p => \`<option value="\${p.id}" \${p.id === currentId ? 'selected' : ''}>\${p.name}</option>\`).join('');
        if (currentId) btn.disabled = false;
      } catch {
        sel.innerHTML = '<option value="">Error cargando playlists</option>';
      }

      sel.addEventListener('change', () => { btn.disabled = !sel.value; });

      btn.addEventListener('click', async () => {
        if (!sel.value) return;
        btn.disabled    = true;
        btn.textContent = 'Guardando…';
        try {
          const r = await fetch('/api/playlist', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ playlistId: sel.value }),
          });
          if (r.ok) {
            window.location.href = '/dashboard';
          } else {
            throw new Error();
          }
        } catch {
          msg.textContent = 'Algo salió mal. Inténtalo de nuevo.';
          btn.disabled    = false;
          btn.textContent = '${buttonText}';
        }
      });
    })();
  </script>
</body>
</html>`);
}

async function renderDashboard(request, env) {
  const userId = await getSessionUser(request, env);
  if (!userId) return Response.redirect('/', 302);

  const userData = await getUserData(userId, env);
  if (!userData?.playlistId) return Response.redirect('/setup', 302);

  let playlistName = 'Tu playlist';
  try {
    const token = await getAccessToken(userData.refreshToken, env);
    const res   = await fetch(`${SPOTIFY_API}/playlists/${userData.playlistId}?fields=name`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) playlistName = (await res.json()).name;
  } catch { /* use default */ }

  return htmlResponse(`<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Weekly Vault — Activo</title>
  <style>${CSS}</style>
</head>
<body>
  <div class="wrap">
    <nav class="nav">
      <div class="nav-dot"></div>
      <span class="nav-wordmark">Weekly Vault</span>
    </nav>

    <div class="page-flow">
      <div class="status-row fade-up">
        <div class="pulse-dot"></div>
        <span class="status-text">Activo</span>
      </div>

      <h1 class="flow-title fade-up d1">Todo en marcha.</h1>
      <p class="flow-sub fade-up d2">Cada domingo añadiremos tus 3 canciones más escuchadas a:</p>

      <div class="playlist-card fade-up d3">
        <span class="playlist-icon">♫</span>
        <div>
          <p class="playlist-name">${playlistName}</p>
          <p class="playlist-meta">Próxima ejecución: este domingo · 20:00 UTC</p>
        </div>
      </div>

      <div class="dash-actions fade-up d4">
        <a href="/setup" class="btn btn-outline">Cambiar playlist</a>
        <form method="POST" action="/api/delete"
              onsubmit="return confirm('¿Seguro? Se borrarán tus datos y dejará de funcionar.')">
          <button type="submit" class="btn-link-danger">Desactivar y borrar mis datos</button>
        </form>
      </div>
    </div>
  </div>
</body>
</html>`);
}

function errorPage(message) {
  return `<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Weekly Vault — Error</title>
  <style>${CSS}</style>
</head>
<body>
  <div class="wrap">
    <nav class="nav">
      <div class="nav-dot"></div>
      <span class="nav-wordmark">Weekly Vault</span>
    </nav>
    <div class="page-flow">
      <p class="err-code fade-up">Error</p>
      <h1 class="flow-title fade-up d1">Algo salió mal</h1>
      <p class="flow-sub fade-up d2">${message}</p>
      <a href="/" class="btn btn-green fade-up d3">Volver al inicio</a>
    </div>
  </div>
</body>
</html>`;
}

// ─────────────────────────────────────────────
// Weekly Job
// ─────────────────────────────────────────────

async function runWeeklyJob(env) {
  console.log('=== Weekly Vault — Start ===');
  const { keys } = await env.USERS_KV.list({ prefix: 'user:' });
  console.log(`Processing ${keys.length} user(s)`);

  for (const key of keys) {
    const userId = key.name.replace('user:', '');
    try {
      await processUser(userId, env);
    } catch (err) {
      console.error(`[${userId}] Error: ${err.message}`);
    }
  }

  console.log('=== Weekly Vault — Done ===');
}

async function processUser(userId, env) {
  const userData = await getUserData(userId, env);
  if (!userData?.playlistId) {
    console.log(`[${userId}] No playlist set, skipping`);
    return;
  }

  const token  = await getAccessToken(userData.refreshToken, env);
  const recent = await getRecentlyPlayed(token);

  if (recent.length === 0) {
    console.log(`[${userId}] No plays this week`);
    return;
  }
  console.log(`[${userId}] ${recent.length} plays found`);

  // Count plays per track and rank
  const counts = {};
  const info   = {};
  for (const t of recent) {
    counts[t.uri] = (counts[t.uri] || 0) + 1;
    info[t.uri]   = `${t.name} — ${t.artist}`;
  }
  const ranked = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  // Get existing playlist tracks
  const existing = await getPlaylistTracks(token, userData.playlistId);

  // Pick top 3 not already in the playlist
  const toAdd = [];
  for (const [uri, count] of ranked) {
    if (existing.has(uri)) {
      console.log(`[${userId}] Skip (already in playlist): ${info[uri]}`);
      continue;
    }
    toAdd.push(uri);
    console.log(`[${userId}] Add: ${info[uri]} (${count} plays)`);
    if (toAdd.length === TRACKS_TO_ADD) break;
  }

  if (toAdd.length === 0) {
    console.log(`[${userId}] All top tracks already in playlist`);
    return;
  }

  await addToPlaylist(token, userData.playlistId, toAdd);
  console.log(`[${userId}] Done — added ${toAdd.length} track(s) ✅`);
}

// ─────────────────────────────────────────────
// Spotify API Helpers
// ─────────────────────────────────────────────

async function getAccessToken(encryptedRefreshToken, env) {
  const refreshToken = await decrypt(encryptedRefreshToken, env.ENCRYPTION_KEY);

  const res = await fetch(SPOTIFY_TOKEN_URL, {
    method: 'POST',
    headers: {
      Authorization:  'Basic ' + btoa(`${env.SPOTIFY_CLIENT_ID}:${env.SPOTIFY_CLIENT_SECRET}`),
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: new URLSearchParams({ grant_type: 'refresh_token', refresh_token: refreshToken }),
  });

  if (!res.ok) throw new Error(`Token refresh failed: ${await res.text()}`);
  return (await res.json()).access_token;
}

async function getRecentlyPlayed(token) {
  const weekAgoMs = Date.now() - DAYS_LOOKBACK * 24 * 60 * 60 * 1000;
  const res = await fetch(
    `${SPOTIFY_API}/me/player/recently-played?limit=50&after=${weekAgoMs}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) throw new Error(`recently-played failed: ${await res.text()}`);
  const data = await res.json();

  return (data.items || [])
    .filter(item => new Date(item.played_at).getTime() >= weekAgoMs)
    .map(item => ({
      uri:    item.track.uri,
      name:   item.track.name,
      artist: item.track.artists[0].name,
    }));
}

async function getPlaylistTracks(token, playlistId) {
  const uris = new Set();
  let url = `${SPOTIFY_API}/playlists/${playlistId}/items?fields=items(track(uri)),next&limit=100`;

  while (url) {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`Playlist fetch failed: ${await res.text()}`);
    const data = await res.json();
    for (const item of data.items || []) {
      if (item?.track?.uri) uris.add(item.track.uri);
    }
    url = data.next;
  }
  return uris;
}

async function addToPlaylist(token, playlistId, uris) {
  const res = await fetch(`${SPOTIFY_API}/playlists/${playlistId}/items`, {
    method: 'POST',
    headers: {
      Authorization:  `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ uris, position: 0 }),
  });
  if (!res.ok) throw new Error(`Add tracks failed: ${await res.text()}`);
}

// ─────────────────────────────────────────────
// Session Utilities
// ─────────────────────────────────────────────

async function getSessionUser(request, env) {
  const cookie = request.headers.get('Cookie') || '';
  const match  = cookie.match(/session=([^;]+)/);
  if (!match) return null;
  return verifySignedValue(match[1], env.SESSION_SECRET);
}

async function signValue(value, secret) {
  const sig = await hmacHex(value, secret);
  return `${value}.${sig}`;
}

async function verifySignedValue(signed, secret) {
  const lastDot = signed.lastIndexOf('.');
  if (lastDot === -1) return null;
  const value    = signed.slice(0, lastDot);
  const sig      = signed.slice(lastDot + 1);
  const expected = await hmacHex(value, secret);
  // Constant-time comparison to prevent timing attacks
  if (sig.length !== expected.length) return null;
  let diff = 0;
  for (let i = 0; i < sig.length; i++) diff |= sig.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0 ? value : null;
}

async function generateState(secret) {
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(16)))
    .map(b => b.toString(16).padStart(2, '0')).join('');
  return signValue(nonce, secret);
}

async function verifyState(state, secret) {
  return (await verifySignedValue(state, secret)) !== null;
}

async function hmacHex(message, secret) {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message));
  return Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, '0')).join('');
}

// ─────────────────────────────────────────────
// Encryption Utilities (AES-256-GCM)
// ─────────────────────────────────────────────

async function encrypt(plaintext, keyHex) {
  const key       = await importAESKey(keyHex);
  const iv        = crypto.getRandomValues(new Uint8Array(12));
  const encoded   = new TextEncoder().encode(plaintext);
  const encrypted = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
  const combined  = new Uint8Array(12 + encrypted.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(encrypted), 12);
  return btoa(String.fromCharCode(...combined));
}

async function decrypt(b64, keyHex) {
  const key      = await importAESKey(keyHex);
  const combined = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const iv       = combined.slice(0, 12);
  const data     = combined.slice(12);
  const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, data);
  return new TextDecoder().decode(decrypted);
}

async function importAESKey(keyHex) {
  const bytes = new Uint8Array(keyHex.match(/.{2}/g).map(b => parseInt(b, 16)));
  return crypto.subtle.importKey('raw', bytes, 'AES-GCM', false, ['encrypt', 'decrypt']);
}

// ─────────────────────────────────────────────
// KV Helper
// ─────────────────────────────────────────────

async function getUserData(userId, env) {
  const raw = await env.USERS_KV.get(`user:${userId}`);
  return raw ? JSON.parse(raw) : null;
}

// ─────────────────────────────────────────────
// Response Helper
// ─────────────────────────────────────────────

function htmlResponse(content, status = 200) {
  return new Response(content, {
    status,
    headers: { 'Content-Type': 'text/html;charset=UTF-8' },
  });
}

// ─────────────────────────────────────────────
// CSS
// ─────────────────────────────────────────────

const CSS = `
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:          oklch(0.10 0.008 145);
    --bg-raised:   oklch(0.14 0.010 145);
    --bg-border:   oklch(0.21 0.012 145);
    --green:       oklch(0.72 0.18  145);
    --green-hover: oklch(0.78 0.18  145);
    --green-dark:  oklch(0.10 0.005 145);
    --text:        oklch(0.95 0.005 145);
    --text-sub:    oklch(0.68 0.015 145);
    --text-faint:  oklch(0.42 0.010 145);
    --red:         oklch(0.65 0.18  25);
  }

  html { scroll-behavior: smooth; }

  body {
    font-family: ui-rounded, -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
  }

  /* ── Layout ── */
  .wrap {
    max-width: 600px;
    margin: 0 auto;
    padding: 0 1.5rem;
  }

  /* ── Nav ── */
  .nav {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 1.5rem 0;
  }
  .nav-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--green);
    flex-shrink: 0;
  }
  .nav-wordmark {
    font-size: 0.95rem;
    font-weight: 700;
    letter-spacing: -0.01em;
  }

  /* ── Hero (landing) ── */
  .hero { padding: clamp(3rem, 10vw, 5rem) 0 clamp(2.5rem, 8vw, 4rem); }

  .eyebrow {
    display: block;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--green);
    margin-bottom: 1.25rem;
  }

  .hero-title {
    font-size: clamp(2.8rem, 10vw, 5rem);
    font-weight: 800;
    line-height: 1.03;
    letter-spacing: -0.04em;
    margin-bottom: 1.25rem;
  }

  .hero-sub {
    font-size: clamp(1rem, 2.5vw, 1.1rem);
    color: var(--text-sub);
    line-height: 1.65;
    max-width: 44ch;
    margin-bottom: 2rem;
  }

  /* ── How it works ── */
  .how {
    padding: 2.5rem 0;
    border-top: 1px solid var(--bg-border);
  }

  .section-label {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-faint);
    margin-bottom: 2rem;
  }

  .steps { list-style: none; }

  .step {
    display: grid;
    grid-template-columns: 2.75rem 1fr;
    gap: 1rem;
    padding: 1.75rem 0;
    border-bottom: 1px solid var(--bg-border);
  }
  .step:last-child { border-bottom: none; }

  .step-n {
    font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: var(--green);
    padding-top: 0.2rem;
  }

  .step-title {
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    margin-bottom: 0.35rem;
  }

  .step-desc {
    font-size: 0.9rem;
    color: var(--text-sub);
    line-height: 1.6;
    max-width: 50ch;
  }

  /* ── Trust footer ── */
  .trust { padding: 2rem 0 3.5rem; }

  .trust-text {
    font-size: 0.78rem;
    color: var(--text-faint);
    line-height: 1.7;
    max-width: 52ch;
  }

  /* ── Buttons ── */
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.9rem;
    font-weight: 700;
    font-family: inherit;
    border-radius: 999px;
    border: none;
    cursor: pointer;
    text-decoration: none;
    transition: background 0.15s, border-color 0.15s, transform 0.12s;
    white-space: nowrap;
  }
  .btn:active { transform: scale(0.97); }

  .btn-green {
    background: var(--green);
    color: var(--green-dark);
    padding: 0.9rem 2rem;
  }
  .btn-green:hover    { background: var(--green-hover); }
  .btn-green:disabled { background: var(--bg-border); color: var(--text-faint); cursor: not-allowed; }
  .btn-green:disabled:active { transform: none; }

  .btn-outline {
    background: transparent;
    color: var(--text);
    padding: 0.8rem 1.75rem;
    border: 1.5px solid var(--bg-border);
  }
  .btn-outline:hover { border-color: var(--text-faint); }

  .btn-link-danger {
    background: none;
    border: none;
    color: var(--red);
    font-size: 0.82rem;
    font-family: inherit;
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 3px;
    padding: 0.25rem 0;
  }
  .btn-link-danger:hover { color: oklch(0.72 0.20 25); }

  /* ── Page flow (setup / dashboard / error) ── */
  .page-flow {
    padding: 2rem 0 3.5rem;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0;
  }

  /* ── Progress ── */
  .progress { margin-bottom: 2.5rem; }

  .progress-label {
    display: block;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--text-faint);
    margin-bottom: 0.5rem;
  }

  .progress-track {
    width: 100%;
    max-width: 280px;
    height: 2px;
    background: var(--bg-border);
    border-radius: 2px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: var(--green);
    border-radius: 2px;
    transition: width 0.5s cubic-bezier(0.22, 1, 0.36, 1);
  }

  /* ── Flow titles ── */
  .flow-title {
    font-size: clamp(2rem, 7vw, 3.2rem);
    font-weight: 800;
    letter-spacing: -0.035em;
    line-height: 1.08;
    margin-bottom: 0.75rem;
  }

  .flow-sub {
    font-size: 0.95rem;
    color: var(--text-sub);
    line-height: 1.6;
    max-width: 42ch;
    margin-bottom: 1.75rem;
  }

  /* ── Select ── */
  .select-wrap {
    position: relative;
    width: 100%;
    max-width: 380px;
    margin-bottom: 1.25rem;
  }

  .select {
    width: 100%;
    padding: 0.9rem 2.75rem 0.9rem 1.1rem;
    border-radius: 10px;
    border: 1.5px solid var(--bg-border);
    background: var(--bg-raised);
    color: var(--text);
    font-size: 0.95rem;
    font-family: inherit;
    cursor: pointer;
    appearance: none;
    -webkit-appearance: none;
    outline: none;
    transition: border-color 0.15s;
  }
  .select:focus  { border-color: var(--green); }
  .select option { background: var(--bg-raised); }

  .select-chevron {
    position: absolute;
    right: 1rem;
    top: 50%;
    transform: translateY(-50%);
    pointer-events: none;
    color: var(--text-faint);
    font-size: 0.8rem;
  }

  /* ── Reassurance list ── */
  .reassurance {
    list-style: none;
    margin-top: 1.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .reassurance li {
    font-size: 0.82rem;
    color: var(--text-faint);
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .reassurance li::before {
    content: '✓';
    color: var(--green);
    font-size: 0.75rem;
    font-weight: 700;
  }

  /* ── Dashboard ── */
  .status-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 1.75rem;
  }

  .pulse-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--green);
    flex-shrink: 0;
    animation: pulse 2.5s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { box-shadow: 0 0 0 0 oklch(0.72 0.18 145 / 0.5); }
    50%       { box-shadow: 0 0 0 6px oklch(0.72 0.18 145 / 0); }
  }

  .status-text {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--green);
  }

  .playlist-card {
    display: flex;
    align-items: center;
    gap: 1rem;
    background: var(--bg-raised);
    border: 1.5px solid var(--bg-border);
    border-radius: 12px;
    padding: 1rem 1.25rem;
    width: 100%;
    max-width: 380px;
    margin-bottom: 2rem;
  }

  .playlist-icon {
    font-size: 1.5rem;
    line-height: 1;
    flex-shrink: 0;
  }

  .playlist-name {
    font-size: 0.95rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    margin-bottom: 0.2rem;
  }

  .playlist-meta {
    font-size: 0.78rem;
    color: var(--text-faint);
  }

  .dash-actions {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.75rem;
  }

  /* ── Error ── */
  .err-code {
    font-family: ui-monospace, monospace;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--red);
    margin-bottom: 1.25rem;
  }

  .err-msg {
    font-size: 0.82rem;
    color: var(--red);
    min-height: 1.2em;
    margin-top: 0.5rem;
  }

  /* ── Entry animations ── */
  @media (prefers-reduced-motion: no-preference) {
    .fade-up {
      animation: fadeUp 0.55s cubic-bezier(0.22, 1, 0.36, 1) both;
    }
    .d1 { animation-delay: 0.07s; }
    .d2 { animation-delay: 0.14s; }
    .d3 { animation-delay: 0.21s; }
    .d4 { animation-delay: 0.28s; }

    @keyframes fadeUp {
      from { opacity: 0; transform: translateY(16px); }
      to   { opacity: 1; transform: translateY(0);    }
    }
  }

  /* ── Responsive ── */
  @media (min-width: 480px) {
    .step { grid-template-columns: 3.25rem 1fr; }
  }
`;
