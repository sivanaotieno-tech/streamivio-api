# Streamivio Media Engine — setup

The Streamivio API is the control plane. Jellyfin is the dedicated media server and delivers video, audio, subtitles, and HLS segments. Do not run FFmpeg or store media files in Vercel Functions: serverless functions are not a media server.

## 1. Start a new Jellyfin server

Requirements:
- A Windows, Linux, or NAS host that can stay online while users watch.
- Enough disk space for media you own or are authorised to stream.
- Docker Desktop (Windows) or Docker Engine (Linux).
- A stable LAN address; for remote viewing, a properly secured public hostname or VPN.

From the repository root:

```powershell
mkdir media-server\config, media-server\cache, media-server\media
docker compose -f media-server/docker-compose.yml up -d
```

Open `http://localhost:8096` and complete the Jellyfin first-run wizard. Create an administrator, then add libraries pointing at `/media` (Movies, Shows, Anime, Documentaries, etc.). The compose file mounts media read-only to prevent accidental edits/deletions from Jellyfin. To avoid filling your system drive, set `STREAMIVIO_MEDIA_PATH` in a root-level `.env` file to an existing external-drive or NAS folder (for example `STREAMIVIO_MEDIA_PATH=E:/Media` on Windows), then start Compose again. No media needs to be copied into the repository.

On Windows Docker Desktop, the example `user: "1000:1000"` may not match your file permissions. If the container cannot read your media, remove the `user` line and restart the container. Do not expose port 8096 directly to the public internet; use HTTPS through a reverse proxy or a private VPN.

## 2. Configure the Streamivio API

Copy `.env.example` values into the API deployment environment (Vercel → Project → Settings → Environment Variables):

- `JELLYFIN_URL`: the reachable HTTPS URL of your Jellyfin host, e.g. `https://media.example.com`. It must be reachable from both the API host and the user's browser.
- `STREAMIVIO_ALLOWED_ORIGINS`: the exact Streamivio website origin(s), comma-separated.
- `STREAMIVIO_LICENSED_PROVIDERS`: optional IDs for provider adapters that have an approved API/integration agreement. This is a status/configuration list, not an automatic connection.
- `OMDB_API_KEY`: optional metadata key.

Redeploy the API after setting environment variables. Check `GET /media/health` and `GET /media/providers`.

## 3. Streamivio frontend integration

API base URL is your deployed Streamivio API origin. The frontend flow:

1. Sign in with `POST /media/auth/login` using the user's Jellyfin credentials. Store the returned user access token in memory/session storage only; never commit it or put it in analytics/logs.
2. Send `Authorization: MediaBrowser Token="<access_token>"` (or `X-Emby-Token`) on calls to `/media/libraries`, `/media/items`, `/media/items/{id}`, and `/media/items/{id}/playback-info`.
3. Render the returned `MediaSources` and `MediaStreams`: let the player choose direct play when supported, otherwise use Jellyfin's returned transcoding/HLS information. The response also includes the user's Jellyfin session token for authenticated browser media requests; treat it as a password and keep it out of logs/analytics.
4. Display selectable audio/subtitle streams from `MediaStreams`. Text subtitle formats can be rendered as sidecar tracks when supported; image subtitles or incompatible codecs may require server-side burn-in transcoding.
5. Send progress to `/media/sessions/{id}/progress` periodically and `/stopped` when playback ends.

The Jellyfin host must allow browser requests from the Streamivio origin (CORS) and be served over HTTPS when Streamivio is HTTPS. The API does not relay video bytes: direct media delivery avoids serverless response-size/time limits and reduces bandwidth costs.

## 4. Metadata coverage

- Jellyfin's library scanner provides local item metadata and media stream details.
- `GET /media/metadata/anilist?q=...` adds anime catalogue metadata from AniList.
- Existing Streamivio API IMDb suggestion resolution and optional OMDb enrichment remain separate metadata sources.
- Add provider-specific adapters only for documented APIs and keys you are authorised to use. Never scrape protected services or guess playback URLs.

## 5. External streaming providers

The initial release includes a provider registry/status contract, not turnkey subscriptions to every streaming service. Each provider requires a documented API, valid credentials, permitted playback method, and a provider-specific adapter. Only playback sources that Streamivio or its users are authorised to access may be surfaced. DRM-protected services must use their official playback SDK/client; this engine does not bypass DRM.

## 6. Playback and transcoding

Jellyfin handles direct play, remuxing, and FFmpeg transcoding. Performance depends on CPU/GPU, source codec, selected quality, subtitle type, and concurrent users. Subtitle burn-in can be substantially more demanding than direct-play subtitles. Start with one test title and verify browser playback before inviting users.

## API endpoints

- `GET /media/health`
- `GET /media/providers`
- `POST /media/auth/login`
- `GET /media/libraries`
- `GET /media/items?q=...`
- `GET /media/items/{item_id}`
- `POST /media/items/{item_id}/playback-info`
- `POST /media/sessions/{item_id}/progress?position_ticks=...`
- `POST /media/sessions/{item_id}/stopped?position_ticks=...`
- `GET /media/subtitles/languages`
- `GET /media/metadata/anilist?q=...`

## Current deployment boundary

The FastAPI control plane can deploy to Vercel. The Jellyfin server, media storage, FFmpeg transcoding, and media delivery must run on a persistent host (your own PC/NAS or a dedicated server). Vercel deployment alone does not create a working media server.
