# Streamivio API

Standalone FastAPI backend for Streamivio discovery and playback coordination.

## Architecture

- **Streamivio web app:** Next.js on Vercel.
- **Streamivio API:** FastAPI on Vercel; handles catalogue metadata and playback coordination, not video bytes.
- **StreamX:** optional metadata aggregation adapter. It is disabled until the operator reviews and approves the upstream data terms.
- **Hovod:** self-hosted upload/transcoding/player service on a persistent VM, with S3-compatible object storage.
- **Playback:** only catalogue entries with explicit distribution-rights records can resolve to Hovod playback.

There is no Jellyfin dependency. The API does not scrape streaming sites, extract third-party embeds, bypass DRM, or supply unlicensed media.

## Run locally

```powershell
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn api.index:app --reload
```

Open `http://127.0.0.1:8000/docs`.

## Existing catalogue API

- `GET /health`
- `GET /catalog`
- `GET /search?q=...`
- `GET /title/{id}`
- `GET /featured`
- `GET /categories`
- `GET /genres`
- `GET /playback/{id}`

## Media Engine API

- `GET /media/health`
- `GET /media/providers`
- `GET /media/search?q=...&kind=movie|series|anime|documentary`
- `GET /media/meta/{kind}/{content_id}`
- `GET /media/playback/{title_id}`

The StreamX metadata adapter requires both `STREAMX_API_BASE` and `STREAMX_UPSTREAM_TERMS_APPROVED=true`. Do not enable it until each upstream source is cleared for the intended use. AniList additionally requires `ANILIST_USAGE_APPROVED=true`; keep it disabled until its specific API restrictions are cleared. StreamX's source code is MIT; upstream data and artwork retain their own terms and rights.

The Hovod adapter requires `HOVOD_API_URL` and `HOVOD_ALLOWED_MEDIA_HOSTS`. Hovod playback IDs are public/unlisted, not access-controlled. This integration is only for content cleared for public playback; it is not suitable for subscriber-only/private content.

See [MEDIA_ENGINE_SETUP.md](MEDIA_ENGINE_SETUP.md), [PROVIDER_AUDIT.md](PROVIDER_AUDIT.md) and [media-engine/.env.hovod.example](media-engine/.env.hovod.example).

## Rights-controlled catalogue records

For Hovod playback, add these fields to the matching title in `catalog.json` only after the rights record has been verified:

```json
{
  "distribution_authorized": true,
  "rights_status": "licensed",
  "rights_reference": "https://example.org/licence-or-rights-record",
  "playback": {
    "hovod_playback_id": "replace-with-real-public-playback-id"
  }
}
```

Allowed rights statuses: `licensed`, `owned`, `public_domain`. A non-empty `rights_reference` is mandatory. Do not fabricate these values or use them to bypass a provider's restrictions.

## Deployment boundary

Vercel can host the Next.js app and FastAPI control API. It is not a persistent video worker and should not store or transcode media. Run Hovod on a persistent VM with Docker; store originals and HLS output in a dedicated S3-compatible bucket. Put Hovod behind HTTPS and a reverse proxy, restrict dashboard access, and configure the embed frame policy for the Streamivio origin.

## Environment variables

API:
- `STREAMIVIO_ALLOWED_ORIGINS`
- `STREAMX_API_BASE` (optional)
- `STREAMX_UPSTREAM_TERMS_APPROVED` (default false)
- `HOVOD_API_URL`
- `HOVOD_ALLOWED_MEDIA_HOSTS`

Frontend:
- `STREAMIVIO_API_URL` (server-only preferred; fallback `NEXT_PUBLIC_STREAMIVIO_API_URL`)

Never commit credentials, storage keys, signed URLs, or private provider tokens.
