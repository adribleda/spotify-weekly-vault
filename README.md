# spotify-weekly-vault

Automatiza una playlist de Spotify con tus canciones mas escuchadas de la semana.

El repositorio hace dos cosas:

1. Cada 30 minutos guarda tus escuchas recientes en la cache de GitHub Actions.
2. Cada domingo a las 20:00 UTC calcula el top semanal y añade las 3 primeras canciones que aun no esten en tu playlist.

Esto evita el fallo principal de una ejecucion semanal unica: Spotify limita `recently-played` a 50 items por llamada, asi que hay que recolectar durante la semana para no perder escuchas si usas Spotify bastante. Referencia oficial: [Get Recently Played Tracks](https://developer.spotify.com/documentation/web-api/reference/get-recently-played).

## Setup rapido

### 1. Haz fork del repositorio

En GitHub, pulsa **Fork** y crea tu copia.

### 2. Crea una Spotify Developer App

1. Abre [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
2. Crea una app.
3. En **Redirect URIs**, añade exactamente:

```text
http://127.0.0.1:8888/callback
```

4. Guarda el **Client ID** y el **Client Secret**.

### 3. Ejecuta el setup

Clona tu fork o descarga este repo y ejecuta:

```bash
python3 setup_auth.py --github-repo TU_USUARIO/spotify-weekly-vault
```

El script:

- te pide el Client ID, Client Secret y el enlace o ID de tu playlist;
- abre Spotify en el navegador;
- recibe el callback automaticamente;
- si tienes GitHub CLI (`gh`) instalado y autenticado, sube los secrets al repo.

Si no tienes `gh`, el script imprimira estos secrets para que los pegues manualmente en **Settings -> Secrets and variables -> Actions**:

```text
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
SPOTIFY_REFRESH_TOKEN
SPOTIFY_PLAYLIST_ID
```

### 4. Prueba la accion

En tu fork:

1. Ve a **Actions -> Spotify Weekly Vault**.
2. Pulsa **Run workflow**.
3. Deja `mode` en `run`.

La primera ejecucion recolectara lo que Spotify devuelva ahora y luego intentara añadir el top disponible. A partir de ahi, GitHub Actions seguira recolectando solo.

El historial se restaura y guarda con `actions/cache`; no se commitea al repositorio.

## Configuracion

Puedes cambiar estos valores en `.github/workflows/weekly.yml`:

```yaml
SPOTIFY_TRACKS_TO_ADD: "3"
SPOTIFY_LOOKBACK_DAYS: "7"
SPOTIFY_HISTORY_RETENTION_DAYS: "14"
```

El horario semanal esta en cron UTC:

```yaml
- cron: "0 20 * * 0"
```

En Espana son las 21:00 en horario de invierno y las 22:00 en horario de verano.

## Modos manuales

Desde Actions, el desplegable `mode` permite:

- `collect`: solo guarda escuchas recientes.
- `add`: calcula el ranking desde el historial guardado y actualiza la playlist.
- `run`: hace `collect` y luego `add`.

En local tambien puedes ejecutar:

```bash
python3 weekly_top.py collect
python3 weekly_top.py add --dry-run
python3 weekly_top.py run
```

Necesitas tener las variables de entorno configuradas si lo ejecutas fuera de GitHub Actions.

## Errores comunes

`Missing GitHub secret(s)`

Falta algun secret en **Settings -> Secrets and variables -> Actions**.

`Authentication failed`

El Client ID, Client Secret o Refresh Token no cuadran. Ejecuta de nuevo `setup_auth.py`.

`SPOTIFY_PLAYLIST_ID`

Usa el ID de la playlist o pega el enlace completo de Spotify en `setup_auth.py`; el script extrae el ID.

## Seguridad

No pegues tokens ni secrets en el codigo. Los valores sensibles deben vivir solo en GitHub Actions Secrets o en variables de entorno locales temporales.

El historial de escuchas no se sube como commit. Si ejecutas el script en local, `data/recent_plays.json` queda ignorado por git.
