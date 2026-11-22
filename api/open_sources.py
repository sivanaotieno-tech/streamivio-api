"""No-key metadata discovery and rights-filtered free playback sources.

Metadata: Wikidata entity search (CC0 structured data; Commons artwork terms vary).
Playback: Internet Archive items whose item-level license is explicitly CC0 or
Public Domain Mark 1.0. This is a conservative allowlist, not a guarantee that
an uploader's rights assertion is correct in every territory.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/open", tags=["No-key Open Catalogue"])
TIMEOUT = httpx.Timeout(12.0, connect=5.0)
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_METADATA = "https://archive.org/metadata"
WIKIDATA_ENTITY = re.compile(r"^Q[1-9][0-9]*$")
IA_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
# Only licenses that do not impose attribution, non-commercial, or share-alike
# obligations are auto-enabled for playback. Other licenses need a separate review.
ALLOWED_LICENSES = {
    "http://creativecommons.org/publicdomain/mark/1.0/",
    "https://creativecommons.org/publicdomain/mark/1.0/",
    "http://creativecommons.org/publicdomain/zero/1.0/",
    "https://creativecommons.org/publicdomain/zero/1.0/",
}
VIDEO_FORMATS = {
    "mpeg4", "h.264", "h264", "matroska", "webm", "ogg video",
    "quicktime", "mpeg2", "mpeg2 video",
}
FILM_CLASSES = {"Q11424"}
SERIES_CLASSES = {"Q5398426", "Q3464665", "Q581714"}
ANIME_CLASSES = {"Q1107", "Q63952888", "Q21198342"}
DOCUMENTARY_CLASSES = {"Q93204"}


def _value(claims: dict, prop: str):
    rows = claims.get(prop) or []
    if not rows:
        return None
    try:
        return rows[0]["mainsnak"]["datavalue"]["value"]
    except (KeyError, TypeError, IndexError):
        return None


def _entity_id(claim: dict) -> str | None:
    try:
        value = claim["mainsnak"]["datavalue"]["value"]["id"]
        return value if WIKIDATA_ENTITY.fullmatch(value) else None
    except (KeyError, TypeError):
        return None


def _entity_year(claims: dict):
    value = _value(claims, "P577")
    if isinstance(value, dict):
        match = re.match(r"^[+-]?(\\d{4})", str(value.get("time", "")))
        return int(match.group(1)) if match else None
    return None


def _commons_file_url(filename: str) -> str | None:
    if not filename or len(filename) > 300:
        return None
    return "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(filename.replace(" ", "_"), safe="")


def _kind_matches(claims: dict, kind: str) -> bool:
    instance_ids = {_entity_id(item) for item in claims.get("P31", [])}
    instance_ids.discard(None)
    if kind == "movie":
        return bool(instance_ids & FILM_CLASSES)
    if kind == "series":
        return bool(instance_ids & SERIES_CLASSES)
    if kind == "anime":
        return bool(instance_ids & (ANIME_CLASSES | SERIES_CLASSES | FILM_CLASSES))
    return bool(instance_ids & DOCUMENTARY_CLASSES)


def _normalise_wikidata(entity: dict, requested_kind: str | None = None) -> dict:
    claims = entity.get("claims") or {}
    image = _value(claims, "P18")
    imdb = _value(claims, "P345")
    director = _entity_id({"mainsnak": claims.get("P57", [{}])[0].get("mainsnak", {})}) if claims.get("P57") else None
    genres = [_entity_id(item) for item in claims.get("P136", [])[:8]]
    cast = [_entity_id(item) for item in claims.get("P161", [])[:12]]
    countries = [_entity_id(item) for item in claims.get("P495", [])[:5]]
    return {
        "id": entity.get("id"),
        "title": (entity.get("labels") or {}).get("en", {}).get("value", ""),
        "overview": (entity.get("descriptions") or {}).get("en", {}).get("value", ""),
        "year": _entity_year(claims),
        "poster_url": _commons_file_url(image) if isinstance(image, str) else None,
        "artwork_source": "Wikimedia Commons" if isinstance(image, str) else None,
        "artwork_license_note": "Check the individual Commons file page for its licence and attribution requirements." if isinstance(image, str) else None,
        "genres": [value for value in genres if value],
        "cast_ids": [value for value in cast if value],
        "director_id": director,
        "country_ids": [value for value in countries if value],
        "imdb_id": imdb if isinstance(imdb, str) else None,
        "wikidata_url": f"https://www.wikidata.org/wiki/{entity.get('id')}",
        "type": requested_kind,
        "metadata_license": "CC0 (Wikidata structured data)",
        "provider": "wikidata",
    }


async def _get_wikidata_entity(entity_id: str) -> dict:
    if not WIKIDATA_ENTITY.fullmatch(entity_id):
        raise HTTPException(status_code=400, detail="Invalid Wikidata identifier")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.get(
                WIKIDATA_API,
                params={"action": "wbgetentities", "ids": entity_id, "props": "labels|descriptions|claims", "languages": "en", "format": "json"},
                headers={"Accept": "application/json", "User-Agent": "Streamivio/1.0 (catalogue metadata; contact via GitHub)"},
            )
            response.raise_for_status()
            payload = response.json()
        entity = (payload.get("entities") or {}).get(entity_id)
        if not isinstance(entity, dict) or "missing" in entity:
            raise HTTPException(status_code=404, detail="Metadata record not found")
        return entity
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Metadata source is temporarily unavailable") from exc


@router.get("/providers")
async def open_providers():
    return {
        "no_api_key_required": True,
        "metadata": [{
            "id": "wikidata",
            "status": "available",
            "license": "CC0 for structured data",
            "artwork": "Wikimedia Commons; each image has its own license and attribution requirements",
            "url": "https://www.wikidata.org/",
        }],
        "playback": [{
            "id": "public-domain-cinema",
            "status": "available",
            "license_allowlist": sorted(ALLOWED_LICENSES),
            "url": "https://archive.org/",
            "policy": "Only item records explicitly marked CC0 or Public Domain Mark 1.0 are returned. Territory-specific public-domain status and uploader accuracy still require review.",
        }],
        "limitations": [
            "This API discovers metadata; it does not manufacture access to commercial films or subscription catalogues.",
            "A title appearing in metadata search does not mean a playable copy exists.",
            "Wikimedia Commons poster licenses vary by individual file.",
        ],
    }


@router.get("/search")
async def open_search(
    q: str = Query(min_length=2, max_length=100),
    kind: str = Query(default="movie", pattern="^(movie|series|anime|documentary|all)$"),
    limit: int = Query(default=20, ge=1, le=50),
):
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            search_response = await client.get(
                WIKIDATA_API,
                params={"action": "wbsearchentities", "search": q, "language": "en", "uselang": "en", "type": "item", "limit": min(limit * 3, 50), "format": "json"},
                headers={"Accept": "application/json", "User-Agent": "Streamivio/1.0 (catalogue metadata; contact via GitHub)"},
            )
            search_response.raise_for_status()
            candidates = search_response.json().get("search", [])
            ids = [row.get("id") for row in candidates if isinstance(row, dict) and WIKIDATA_ENTITY.fullmatch(str(row.get("id", "")))]
            if not ids:
                return {"results": [], "total": 0, "provider": "wikidata", "metadata_license": "CC0"}
            entity_response = await client.get(
                WIKIDATA_API,
                params={"action": "wbgetentities", "ids": "|".join(ids[:50]), "props": "labels|descriptions|claims", "languages": "en", "format": "json"},
                headers={"Accept": "application/json", "User-Agent": "Streamivio/1.0 (catalogue metadata; contact via GitHub)"},
            )
            entity_response.raise_for_status()
            entities = entity_response.json().get("entities", {})
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Metadata source is temporarily unavailable") from exc

    results = []
    for candidate in candidates:
        entity_id = candidate.get("id") if isinstance(candidate, dict) else None
        entity = entities.get(entity_id) if entity_id else None
        if not isinstance(entity, dict) or "missing" in entity:
            continue
        matched_kind = next((k for k in ("movie", "series", "anime", "documentary") if _kind_matches(entity.get("claims") or {}, k)), None)
        if kind != "all":
            if kind == "anime":
                if not _kind_matches(entity.get("claims") or {}, "anime"):
                    continue
            elif matched_kind != kind:
                continue
        row = _normalise_wikidata(entity, matched_kind)
        if row["title"]:
            results.append(row)
        if len(results) >= limit:
            break
    return {"results": results, "total": len(results), "provider": "wikidata", "metadata_license": "CC0"}


@router.get("/title/{entity_id}")
async def open_title(entity_id: str):
    entity = await _get_wikidata_entity(entity_id)
    claims = entity.get("claims") or {}
    kind = next((k for k in ("movie", "series", "anime", "documentary") if _kind_matches(claims, k)), None)
    if not kind:
        raise HTTPException(status_code=404, detail="This Wikidata record is not classified as a supported movie, series, anime, or documentary.")
    return _normalise_wikidata(entity, kind)


@router.get("/playback/search")
async def public_domain_search(
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
):
    # Lucene phrase is parameterised; caller text is escaped before insertion.
    safe_query = re.sub(r"[^A-Za-z0-9 \\-]", " ", q).strip()
    if len(safe_query) < 2:
        raise HTTPException(status_code=400, detail="Search query must contain letters or numbers.")
    license_filter = " OR ".join(f'licenseurl:"{license_url}"' for license_url in sorted(ALLOWED_LICENSES))
    query = f'mediatype:movies AND ({license_filter}) AND title:({safe_query})'
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.get(
                IA_SEARCH,
                params={"q": query, "fl[]": ["identifier", "title", "year", "creator", "description", "licenseurl"], "rows": limit, "page": 1, "output": "json"},
                headers={"Accept": "application/json", "User-Agent": "Streamivio/1.0 (public-domain film discovery)"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Free film catalogue is temporarily unavailable") from exc

    docs = (payload.get("response") or {}).get("docs") or []
    results = []
    for doc in docs:
        license_url = str(doc.get("licenseurl") or "")
        identifier = str(doc.get("identifier") or "")
        if license_url not in ALLOWED_LICENSES or not IA_IDENTIFIER.fullmatch(identifier):
            continue
        results.append({
            "id": identifier,
            "title": doc.get("title") or identifier,
            "year": doc.get("year"),
            "creator": doc.get("creator"),
            "overview": doc.get("description"),
            "license_url": license_url,
            "rights_reference": f"https://archive.org/details/{identifier}",
            "provider": "public-domain-cinema",
            "playback_endpoint": f"/open/playback/{identifier}",
        })
    return {"results": results, "total": len(results), "provider": "public-domain-cinema", "license_filter": "CC0 or Public Domain Mark 1.0"}


@router.get("/playback/{identifier}")
async def public_domain_playback(identifier: str):
    if not IA_IDENTIFIER.fullmatch(identifier):
        raise HTTPException(status_code=400, detail="Invalid archive identifier")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.get(f"{IA_METADATA}/{identifier}", headers={"Accept": "application/json", "User-Agent": "Streamivio/1.0 (public-domain film playback)"})
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Free film source is temporarily unavailable") from exc

    metadata = payload.get("metadata") or {}
    license_url = str(metadata.get("licenseurl") or "")
    if metadata.get("mediatype") != "movies" or license_url not in ALLOWED_LICENSES:
        raise HTTPException(status_code=403, detail="Playback blocked: this item does not carry an explicitly allowlisted public-domain or CC0 licence.")
    files = payload.get("files") or []
    video_files = [
        item for item in files
        if isinstance(item, dict)
        and str(item.get("format") or "").casefold() in VIDEO_FORMATS
        and not str(item.get("name") or "").endswith((".torrent", ".xml", ".sqlite"))
    ]
    if not video_files:
        raise HTTPException(status_code=404, detail="No supported video file is available for this item.")
    video_files.sort(key=lambda item: (0 if "mpeg4" in str(item.get("format", "")).casefold() else 1, int(item.get("size") or 0) if str(item.get("size") or "").isdigit() else 0))
    chosen = video_files[0]
    filename = str(chosen.get("name") or "")
    if not filename or "/" in filename or "\\" in filename or len(filename) > 500:
        raise HTTPException(status_code=502, detail="The media source returned an invalid video filename.")
    return {
        "available": True,
        "title": metadata.get("title") or identifier,
        "provider": "public-domain-cinema",
        "license_url": license_url,
        "rights_reference": f"https://archive.org/details/{identifier}",
        "embed_url": f"https://archive.org/embed/{identifier}",
        "stream_url": f"https://archive.org/download/{identifier}/{quote(filename, safe='')}",
        "format": chosen.get("format"),
        "size_bytes": int(chosen.get("size")) if str(chosen.get("size") or "").isdigit() else None,
        "notice": "The item is labelled CC0 or Public Domain Mark by its uploader. Confirm uploader authority and public-domain status in every territory where you distribute it.",
    }
