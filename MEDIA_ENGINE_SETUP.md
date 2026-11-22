# Streamivio Media Engine — standalone, hybrid deployment

Streamivio does not require Jellyfin. The web application and metadata/control API can run on Vercel; the persistent video pipeline runs on a small cloud VM and stores authorised media in S3-compatible object storage (Cloudflare R2 is one option).

## Components

- **Streamivio web app:** Next.js on Vercel.
- **Streamivio API:** FastAPI on Vercel. It exposes metadata and playback coordination, not video bytes.
- **StreamX API:** optional metadata adapter. Its source code is MIT, but its upstream providers have different terms. Keep it disabled until the operator has reviewed and approved the exact upstream sources for the intended use.
- **Hovod:** self-hosted video upload/transcoding/player service on a persistent VM. Its source code is MIT.
- **Object storage:** S3-compatible bucket for originals, HLS renditions, thumbnails and captions. Do not store large media in the Git repository or Vercel filesystem.

## 1. Hovod hybrid host

Use a Linux VM with Docker and enough CPU/RAM for the expected number of simultaneous transcodes. Hovod's worker needs temporary disk space during encoding (the upstream guide recommends planning for roughly 3× the source size). Keep its API behind HTTPS reverse proxy; the Compose file binds port 3000 to loopback.

1. Create an S3-compatible bucket and a dedicated access key limited to that bucket.
2. Copy `.env.hovod.example` to `.env.hovod`.
3. Set the R2/S3 endpoint, bucket, access keys, public media base URL, public application URL, CORS origin and a unique JWT secret.
4. Set `EMBED_FRAME_ANCESTORS` to the Streamivio origin so the player can be embedded.
5. Run `docker compose -f media-engine/docker-compose.yml up -d`.
6. Configure a reverse proxy with TLS and expose the Hovod API/dashboard at the hostname you choose.

Do not expose the container port directly to the public internet. Restrict dashboard/admin access at the reverse proxy or network layer.

## 2. Streamivio API environment

Set these server-side variables in the API deployment:

- `HOVOD_API_URL`: HTTPS origin of the Hovod service, e.g. `https://media-api.example.com`.
- `HOVOD_ALLOWED_MEDIA_HOSTS`: comma-separated hostnames allowed for HLS manifests, e.g. `media-api.example.com,media-assets.example.com`. Hostnames only; no schemes or paths.
- `STREAMX_API_BASE`: your self-hosted StreamX API origin. Leave unset until deployed.
- `STREAMX_UPSTREAM_TERMS_APPROVED`: set to `true` only after reviewing the Cinemeta/MetaHub upstream terms and rights for the intended use. The default is disabled.
- `ANILIST_USAGE_APPROVED`: separate opt-in for AniList anime search. Keep false unless the AniList API terms and Streamivio's service model have been cleared.
- `IMDB_LOOKUP_APPROVED`: controls the existing IMDb suggestion ID lookup route. Keep false unless IMDb has approved the intended use.

The frontend playback route also reads `STREAMIVIO_API_URL` (or `NEXT_PUBLIC_STREAMIVIO_API_URL`) to call the Streamivio API. Prefer the server-only `STREAMIVIO_API_URL` variable.

## 3. Rights-controlled catalogue entries

Hovod public playback IDs are unlisted, not access-controlled. This integration is therefore restricted to titles cleared for public playback. It is not suitable for subscriber-only/private titles until an authenticated playback gateway is implemented.

A title must explicitly carry all of the following in `catalog.json`:

```json
{
  "id": "public-domain-sample",
  "title": "Example authorised title",
  "distribution_authorized": true,
  "rights_status": "public_domain",
  "rights_reference": "https://example.org/rights-record",
  "playback": {
    "hovod_playback_id": "replace-with-real-hovod-playback-id"
  }
}
```

Allowed `rights_status` values are `licensed`, `owned`, and `public_domain`. `rights_reference` must point to the underlying contract, licence, ownership record or public-domain evidence. Do not set these fields merely to make a title playable.

The Hovod playback route verifies the rights fields before asking Hovod for the public playback manifest. The returned manifest hostname must also be listed in `HOVOD_ALLOWED_MEDIA_HOSTS`.

## 4. Metadata provider terms

StreamX code is MIT-licensed; its data is not one blanket licence. Its README lists Cinemeta, MetaHub, Wikidata, Wikipedia, IMDb suggestion data, Rotten Tomatoes, Metacritic, JustWatch, TVmaze and AniList. Some are community endpoints, some are public/open-data sources, and some are parsed public web pages rather than official commercial APIs. Posters and artwork remain owned by their respective rights holders.

For production or commercial use:
- Review each upstream's current terms and obtain permission where required.
- Keep attribution and source provenance where required.
- Do not assume a public endpoint, no-key endpoint, or MIT code licence grants redistribution rights.
- Disable upstreams whose terms do not clearly permit your use. Replace those adapters with licensed data feeds if necessary.

The StreamX adapter is intentionally disabled unless `STREAMX_UPSTREAM_TERMS_APPROVED=true` is explicitly set.

## 5. Hovod playback limitations

Hovod's current public playback endpoint allows anyone with the unlisted playback ID to watch. Do not put confidential or subscriber-only content there. The Streamivio adapter only enables public playback for catalogue items with a rights record, but that is a rights check, not user-level access control.

Hovod provides its own embeddable player URL (including captions and quality controls) and HLS manifest URL. Streamivio prefers the Hovod player when available; the manifest is used as a fallback.

## 6. Local checks

API:
```powershell
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn api.index:app --reload
# Open http://127.0.0.1:8000/docs
```

Check:
- `GET /media/health`
- `GET /media/providers`
- `GET /media/search?q=planet&kind=documentary`
- `GET /media/playback/{catalog-id}` (must return 403 unless a valid rights record and Hovod mapping exist)

Hovod:
```powershell
docker compose -f media-engine/docker-compose.yml config
```

A successful API health response does not prove a video can play. Test one authorised sample asset end-to-end in a real browser, including captions, CORS, CDN access and playback on mobile networks before production.
