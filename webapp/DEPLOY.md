# Deploy — Weekly Vault Web App

Guía de despliegue para ti (una sola vez, ~20 minutos).

---

## Requisitos previos

- Cuenta en [Cloudflare](https://dash.cloudflare.com/sign-up) (gratis)
- Node.js instalado (`node --version` debe devolver algo)
- La Spotify Developer App del proyecto original (Client ID + Client Secret)

---

## Paso 1 — Instalar Wrangler (CLI de Cloudflare)

```bash
npm install -g wrangler
wrangler login
```

Abrirá el navegador para autenticarte con Cloudflare.

---

## Paso 2 — Instalar dependencias del worker

```bash
cd webapp/worker
npm install
```

---

## Paso 3 — Crear el namespace de KV

```bash
wrangler kv:namespace create USERS_KV
```

Verás algo como:

```
{ binding = "USERS_KV", id = "abc123def456..." }
```

Copia ese `id` y pégalo en `wrangler.toml`:

```toml
[[kv_namespaces]]
binding = "USERS_KV"
id      = "abc123def456..."   # ← aquí
```

---

## Paso 4 — Primer deploy (para obtener la URL)

```bash
npm run deploy
```

Al acabar verás tu URL:

```
https://weekly-vault.TU_SUBDOMINIO.workers.dev
```

---

## Paso 5 — Actualizar la Spotify Developer App

Ve a [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard), entra en tu app y añade este Redirect URI:

```
https://weekly-vault.TU_SUBDOMINIO.workers.dev/auth/callback
```

Guarda los cambios.

---

## Paso 6 — Actualizar wrangler.toml

Edita `wrangler.toml` y pon tu URL real:

```toml
[vars]
REDIRECT_URI = "https://weekly-vault.TU_SUBDOMINIO.workers.dev/auth/callback"
```

---

## Paso 7 — Configurar los secrets

Ejecuta estos comandos uno a uno. Cada uno te pedirá el valor de forma segura (no aparece en pantalla):

```bash
# Tu Client ID de Spotify
wrangler secret put SPOTIFY_CLIENT_ID

# Tu Client Secret de Spotify
wrangler secret put SPOTIFY_CLIENT_SECRET

# Cualquier string largo aleatorio (mínimo 32 caracteres)
wrangler secret put SESSION_SECRET

# Clave de cifrado AES-256: genera una con el comando de abajo
wrangler secret put ENCRYPTION_KEY
```

Para generar la `ENCRYPTION_KEY`:

```bash
openssl rand -hex 32
```

Copia el resultado y pégalo cuando Wrangler te lo pida.

---

## Paso 8 — Deploy final

```bash
npm run deploy
```

---

## Listo

Visita `https://weekly-vault.TU_SUBDOMINIO.workers.dev` — verás la landing page.

El cron se ejecuta automáticamente cada domingo a las 20:00 UTC.
Puedes probarlo manualmente desde el panel de Cloudflare:
**Workers & Pages → weekly-vault → Triggers → Cron Triggers → Run**

---

## Resumen de costes

| Recurso | Límite gratuito |
|---|---|
| Cloudflare Workers | 100.000 req/día |
| KV reads | 100.000/día |
| KV writes | 1.000/día |
| Cron triggers | Incluido |

Para este uso (unos pocos usuarios, 1 ejecución/semana por usuario) el tier gratuito es más que suficiente.

---

## Seguridad

- Los refresh tokens de Spotify se guardan **cifrados con AES-256-GCM** en KV.
- Las cookies de sesión están **firmadas con HMAC-SHA256**.
- El Client Secret nunca sale del Worker (nunca va al navegador).
- Los usuarios pueden borrar todos sus datos desde la propia web (botón "Desactivar").
