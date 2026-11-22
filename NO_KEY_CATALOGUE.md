# No-key catalogue and playback API

Streamivio now includes a no-key discovery layer alongside the existing local catalogue and optional, separately reviewed adapters.

## Public endpoints

All endpoints are served by the existing FastAPI app and require no API key:

| Endpoint | Purpose |
|---|---|
| `GET /open/providers` | Provider capabilities, licences and limitations |
| `GET /open/search?q=...&kind=movie` | Search movie metadata |
| `GET /open/search?q=...&kind=series` | Search TV series metadata |
| `GET /open/search?q=...&kind=anime` | Search anime metadata |
| `GET /open/search?q=...&kind=documentary` | Search documentary metadata |
| `GET /open/search?q=...&kind=all` | Search all supported Wikidata media classes |
| `GET /open/title/{QID}` | Fetch a metadata record by Wikidata ID |
| `GET /open/playback/search?q=...` | Search public-domain / CC0 film items |
| `GET /open/playback/{identifier}` | Resolve a playable video and embeddable player |

Interactive API documentation is available at `/docs`.

## Metadata provider

Wikidata's public MediaWiki API provides search and structured metadata without an API key. Its structured data is CC0. The API returns title, description, year, Wikidata ID, IMDb ID when present, genre/cast/director/country entity IDs, and available poster artwork.

Poster artwork is served through Wikimedia Commons. **The image's individual file licence is not the same as Wikidata's CC0 data licence.** The response includes the Commons source and tells clients to inspect the individual file page for licence and attribution requirements. Do not strip required attribution or imply every image is public domain.

Wikidata is community-maintained and incomplete. Results can omit cast, genres, dates, ratings and artwork. It is not a commercial film/TV availability database and does not provide video streams.

## Playback provider and rights gate

The free-playback search uses the Internet Archive's public Advanced Search and metadata endpoints. No key is required. It only searches records whose item-level `licenseurl` exactly matches this conservative allowlist:

- Creative Commons CC0 1.0
- Creative Commons Public Domain Mark 1.0

It deliberately excludes CC BY, BY-SA, BY-NC, custom licences, missing licence metadata and unverified records. The playback resolver re-fetches the item's metadata and checks the media type and allowlisted licence again before returning an embed URL and a direct video file URL.

**Important rights limitation:** an uploader-supplied licence field is not proof that the uploader owned the work or had authority to upload it. Public-domain status can also vary by country and by the underlying film, soundtrack, subtitles or restoration. A human rights review is still required before commercial redistribution, monetisation, or inclusion in a paid tier. This source is intended for public-domain/CC0 material only, not commercial studio films or current subscription titles.

## Example calls

```http
GET /open/search?q=Metropolis&kind=movie
GET /open/search?q=Planet%20Earth&kind=series
GET /open/playback/search?q=Night%20of%20the%20Living%20Dead
GET /open/playback/<archive-identifier>
```

A metadata result does not imply playback availability. The metadata search and playback search are intentionally independent.

## Existing API compatibility

The new routes are added under `/open`; existing `/catalog`, `/search`, `/title/{id}`, `/media/*` and rights-gated Hovod endpoints remain intact. The StreamX, AniList, IMDb and Hovod integrations retain their existing opt-in/rights safeguards.

## Deployment

No additional environment variables or secrets are required for these endpoints. Deploy the existing FastAPI repository to Vercel as before. The API calls public upstream services at request time, so upstream availability, rate limits and cold starts affect response times. Add a compliant cache if request volume grows; do not hammer public endpoints or use them as a bulk mirror.
