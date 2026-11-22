"""Standalone Streamivio media integrations.

No Jellyfin dependency. Metadata and playback are separate:
- StreamX is an optional metadata adapter, disabled until upstream terms are reviewed.
- Hovod is an optional self-hosted video pipeline for content Streamivio is authorised to distribute.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/media", tags=["Streamivio Media Engine"])
ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "catalog.json"
TIMEOUT = httpx.Timeout(10.0, connect=4.0)
RIGHTS_STATUSES = {"licensed", "owned", "public_domain"}
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
PLAYBACK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _base_url(name: str) -> str:
    value = os.getenv(name, "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    if parsed.scheme != "https" and not local_http:
        return ""
    if not parsed.hostname or parsed.username or parsed.password:
        return ""
    return value


def _streamx_enabled() -> bool:
    return bool(_base_url("STREAMX_API_BASE")) and os.getenv("STREAMX_UPSTREAM_TERMS_APPROVED", "").lower() == "true"


def _read_catalog() -> list[dict]:
    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("titles", []) if isinstance(payload, dict) else payload
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _find_title(title_id: str) -> dict | None:
    return next((row for row in _read_catalog() if str(row.get("id", "")) == title_id), None)


def _has_distribution_rights(row: dict) -> bool:
    return (
        row.get("distribution_authorized") is True
        and str(row.get("rights_status", "")).lower() in RIGHTS_STATUSES
        and isinstance(row.get("rights_reference"), str)
        and bool(row["rights_reference"].strip())
    )


def _is_https_media_url(value: object, allowed_hosts: set[str]) -> bool:
    if not isinstance(value, str) or len(value) > 4096:
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.hostname.lower() in allowed_hosts
        and not parsed.username
        and not parsed.password
    )


@router.get("/health")
async def media_health():
    streamx_configured = bool(_base_url("STREAMX_API_BASE"))
    streamx_enabled = _streamx_enabled()
    hovod_configured = bool(_base_url("HOVOD_API_URL") and os.getenv("HOVOD_ALLOWED_MEDIA_HOSTS", "").strip())
    return {
        "service": "streamivio-media-engine",
        "status": "ok",
        "metadata": "enabled" if streamx_enabled else ("needs_terms_approval" if streamx_configured else "not_configured"),
        "playback": "configured" if hovod_configured else "not_configured",
    }


@router.get("/providers")
async def media_providers():
    return {
        "providers": [
            {
                "id": "streamx",
                "role": "metadata",
                "configured": bool(_base_url("STREAMX_API_BASE")),
                "enabled": _streamx_enabled(),
                "status": "enabled" if _streamx_enabled() else "disabled_until_upstream_terms_are_reviewed",
                "source": "https://github.com/imzyrix/streamx-api",
                "code_license": "MIT",
                "upstream_data_license": "varies_by_provider",
            },
            {
                "id": "hovod",
                "role": "authorised_video_delivery",
                "configured": bool(_base_url("HOVOD_API_URL") and os.getenv("HOVOD_ALLOWED_MEDIA_HOSTS", "").strip()),
                "status": "configured" if (_base_url("HOVOD_API_URL") and os.getenv("HOVOD_ALLOWED_MEDIA_HOSTS", "").strip()) else "not_configured",
                "source": "https://github.com/Synapsr/Hovod",
                "code_license": "MIT",
                "playback_access": "public_unlisted_ids",
                "warning": "Hovod public playback IDs are unlisted, not access-controlled. Use only titles cleared for public playback; do not use this mode for subscriber-only content.",
            },
        ]
    }


@router.get("/search")
async def media_search(
    q: str = Query(min_length=2, max_length=100),
    kind: str = Query(default="movie", pattern="^(movie|series|anime|documentary)$"),
    limit: int = Query(default=30, ge=1, le=100),
):
    if _streamx_enabled():
        base = _base_url("STREAMX_API_BASE")
        upstream_type = "series" if kind in {"series", "anime", "documentary"} else "movie"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
                endpoint = f"{base}/anime/search" if kind == "anime" else f"{base}/search"
                response = await client.get(
                    endpoint,
                    params={"q": q} if kind == "anime" else {"q": q, "type": upstream_type},
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
            if isinstance(payload, dict):
                payload["streamivio_metadata_provider"] = "streamx"
                return payload
            raise ValueError("Unexpected metadata response")
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="Metadata provider is temporarily unavailable") from exc

    query = q.casefold().strip()
    kind_types = {
        "movie": {"movie"},
        "series": {"tv", "series"},
        "anime": {"anime"},
        "documentary": {"documentary"},
    }[kind]
    rows = [
        row for row in _read_catalog()
        if row.get("published", True)
        and query in str(row.get("title", "")).casefold()
        and str(row.get("type", "movie")).lower() in kind_types
    ]
    return {"results": rows[:limit], "total": len(rows), "provider": "streamivio-catalog", "metadata_only": True}


@router.get("/meta/{kind}/{content_id}")
async def media_metadata(kind: str, content_id: str):
    if kind not in {"movie", "series"} or not ID_RE.fullmatch(content_id):
        raise HTTPException(status_code=400, detail="Invalid metadata type or identifier")
    if not _streamx_enabled():
        raise HTTPException(status_code=503, detail="StreamX metadata is disabled until its upstream data terms have been reviewed and approved.")
    base = _base_url("STREAMX_API_BASE")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.get(f"{base}/meta/{kind}/{content_id}", headers={"Accept": "application/json"})
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Metadata provider is temporarily unavailable") from exc


@router.get("/playback/{title_id}")
async def media_playback(title_id: str):
    if not ID_RE.fullmatch(title_id):
        raise HTTPException(status_code=400, detail="Invalid title identifier")
    row = _find_title(title_id)
    if not row:
        raise HTTPException(status_code=404, detail="Title not found")
    if not _has_distribution_rights(row):
        raise HTTPException(status_code=403, detail="Playback is disabled: this title has no verified distribution-rights record.")

    playback = row.get("playback") if isinstance(row.get("playback"), dict) else {}
    playback_id = str(playback.get("hovod_playback_id") or "")
    if not PLAYBACK_ID_RE.fullmatch(playback_id):
        raise HTTPException(status_code=404, detail="No Hovod asset is mapped to this authorised title.")

    base = _base_url("HOVOD_API_URL")
    if not base:
        raise HTTPException(status_code=503, detail="Hovod API is not configured.")
    allowed_hosts = {
        value.strip().lower()
        for value in os.getenv("HOVOD_ALLOWED_MEDIA_HOSTS", "").split(",")
        if value.strip()
    }
    api_host = (urlparse(base).hostname or "").lower()
    if not allowed_hosts:
        raise HTTPException(status_code=503, detail="Configure HOVOD_ALLOWED_MEDIA_HOSTS with the trusted Hovod/CDN hostnames.")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.get(f"{base}/v1/playback/{playback_id}", headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Hovod playback service is unavailable") from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Hovod returned an invalid playback response.")

    manifest = data.get("manifestUrl")
    player = data.get("playerUrl")
    if manifest and not _is_https_media_url(manifest, allowed_hosts):
        raise HTTPException(status_code=502, detail="Hovod returned a media URL outside the configured trusted host allowlist.")
    if player:
        parsed_player = urlparse(player) if isinstance(player, str) else None
        if not parsed_player or parsed_player.scheme != "https" or (parsed_player.hostname or "").lower() != api_host:
            player = None

    if not manifest and not player:
        raise HTTPException(status_code=409, detail="This Hovod asset is not ready for playback.")

    return {
        "available": True,
        "format": "hls" if manifest else "embed",
        "stream_url": manifest,
        "player_url": player,
        "title": row.get("title"),
        "source": "hovod",
        "rights_status": row.get("rights_status"),
        "notice": "Playback is enabled only for catalogue entries with an explicit distribution-rights record.",
    }
