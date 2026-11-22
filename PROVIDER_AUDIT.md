# Streamivio provider and licence audit

**Review date:** 22 November 2026  
**Scope:** the selected StreamX metadata adapter and Hovod video pipeline. This is an engineering review, not legal advice or a substitute for the rights review already being handled for Streamivio.

## Decision summary

| Component | Project code licence | Data/media rights | Integration decision |
|---|---|---|---|
| StreamX API | MIT | Each upstream has separate terms; StreamX itself grants no blanket rights to upstream data or artwork | Integrated as an opt-in adapter; disabled by default |
| Hovod | MIT | Does not grant rights to the videos uploaded into it | Integrated for Streamivio-owned/licensed/public-domain media only |
| FFmpeg inside Hovod image | LGPL 2.1+ base; GPL applies if GPL components are enabled | Depends on the exact binary build and enabled codecs | Verify the built image's FFmpeg configuration and notices before commercial distribution |
| Cloudflare R2 / S3 | Provider contract | Storage, delivery, region and billing terms are separate | Optional storage target; configure a dedicated bucket/key |

## StreamX: source code versus upstream data

The StreamX repository identifies its **source code as MIT** and its documentation as **CC BY 4.0**. Its README explicitly warns that upstream metadata and artwork remain subject to the upstream rights holders' terms. We are not copying its source code into Streamivio; Streamivio calls a separately deployed StreamX instance through a server-side adapter.

The Streamivio adapter currently calls only:
- `/search` for movie/series discovery (Cinemeta catalogue upstream).
- `/meta/{type}/{id}?enrich=0` for base title metadata/artwork (Cinemeta/MetaHub layer; optional enrichments are disabled).
- `/anime/search` only when `ANILIST_USAGE_APPROVED=true`.

It does **not** call StreamX's `/streaming` route, JustWatch offers, IMDb suggestion search, Rotten Tomatoes, Metacritic, TVmaze, Wikidata or Wikipedia enrichment. Those are not enabled through this adapter.

### Upstream findings relevant to this integration

- **Cinemeta / MetaHub:** community Stremio metadata and artwork services. The repository documentation does not establish a commercial redistribution licence or SLA for these upstreams. Treat their data and artwork as not cleared until the rights holder/service operator provides written terms.
- **AniList:** its API terms say free use is for non-commercial usage, restrict use in competing non-complementary anime/manga list or tracker services, and require a commercial licence above the stated monthly revenue threshold. Streamivio has anime discovery and watchlists, so this is a material compatibility question. The integration is separately disabled unless `ANILIST_USAGE_APPROVED=true`, and that flag should only be set after written approval / a documented legal determination.
- **JustWatch:** its published terms describe personal, non-commercial use and prohibit unauthorised scraping/data extraction and public/commercial reuse. Streamivio does not call the JustWatch route.
- **IMDb:** IMDb's help guidance limits its permitted dataset use to personal/non-commercial use under its stated conditions and points businesses to content licensing. Streamivio does not call IMDb suggestion scraping through the StreamX adapter.
- **Rotten Tomatoes / Metacritic:** the StreamX README describes parsing public pages rather than official commercial APIs. These enrichment sources are not called by Streamivio's `enrich=0` metadata requests.
- **TVmaze:** the public API documents CC BY-SA data use with attribution and ShareAlike, and separately advertises paid business/enterprise licensing. Streamivio does not call the TVmaze adapter in this integration.
- **Wikidata:** structured data is CC0. Wikipedia text generally carries CC BY-SA and needs attribution/share-alike compliance. These enrichment sources are not called by this adapter.

The adapter remains disabled unless `STREAMX_UPSTREAM_TERMS_APPROVED=true`. That setting is an operator attestation, not an automated licence check. Do not set it merely because StreamX is MIT-licensed. The operator must retain a record of the approved upstreams, terms version, permitted territories, attribution requirements and commercial-use scope. If only some sources are cleared, do not enable the aggregate endpoint until the deployment is changed to exclude the uncleared sources.

## Hovod and video rights

Hovod's repository is MIT-licensed. That licence applies to Hovod's code, not to any film, episode, subtitle, artwork, music or other media uploaded into it.

Hovod's current security documentation states that public playback is available to anyone who knows an unlisted playback ID; playback IDs are not access-controlled. Streamivio therefore requires a catalogue rights record before resolving a Hovod asset, but this check does not make the Hovod playback URL private. Use it only for titles cleared for public playback. Do not use this integration for Plus/Premium subscriber-only titles or private content until Hovod or a separate gateway enforces authenticated entitlements on every manifest and segment request.

Each playable catalogue entry must include:
- `distribution_authorized: true`
- `rights_status: licensed | owned | public_domain`
- `rights_reference`: a non-empty reference to the licence, contract, ownership record or public-domain evidence
- `playback.hovod_playback_id`: an asset created in Streamivio's own Hovod tenant

The Hovod API's manifest host is restricted by `HOVOD_ALLOWED_MEDIA_HOSTS`. Hovod's API origin is separately configured in `HOVOD_API_URL`.

## FFmpeg and container notices

Hovod's Dockerfile installs the Debian `ffmpeg` package. FFmpeg's official legal page explains that FFmpeg is LGPL 2.1+ by default, but enabling GPL components (and certain codecs/libraries) makes the FFmpeg build GPL. We have not executed the published image or inspected its exact `ffmpeg -buildconf` output in this environment. Before distributing a modified Hovod image or making compliance claims, inspect the actual runtime build, identify linked codecs, retain the corresponding source/notices and follow the applicable LGPL/GPL obligations.

## Outstanding production gates

1. Obtain written clearance for Cinemeta/MetaHub data and artwork or replace them with licensed feeds.
2. Obtain AniList clearance or leave its adapter disabled.
3. Do not use JustWatch, IMDb scraping, RT/Metacritic scraping or other non-cleared sources in a commercial Streamivio catalogue.
4. Confirm Hovod's public playback model is suitable for each title; do not use it for paywalled/private playback.
5. Inspect FFmpeg's actual build configuration and dependency notices in the deployed Hovod image.
6. Confirm the media licence covers the territories, term, monetisation, devices, subtitles, audio tracks and CDN delivery Streamivio intends to offer.

## Primary references

- [StreamX repository and attribution/licensing notes](https://github.com/imzyrix/streamx-api)
- [Hovod MIT licence](https://github.com/Synapsr/Hovod/blob/main/LICENSE)
- [Hovod security notes on public playback](https://github.com/Synapsr/Hovod/blob/main/SECURITY.md)
- [AniList API terms](https://docs.anilist.co/guide/terms-of-use)
- [JustWatch Terms of Use](https://support.justwatch.com/article/just-watchs-terms-of-use)
- [IMDb data use guidance](https://help.imdb.com/article/imdb/general-information/can-i-use-imdb-data-in-my-software/G5JTRESSHJBBHTGX)
- [TVmaze API licensing](https://www.tvmaze.com/api)
- [Wikidata licensing](https://www.wikidata.org/wiki/Wikidata:Licensing)
- [Wikimedia content reuse](https://www.mediawiki.org/wiki/Wikimedia_APIs/Content_reuse)
- [FFmpeg legal information](https://www.ffmpeg.org/legal.html)
