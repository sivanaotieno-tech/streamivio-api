"""Streamivio Media Engine: secure Jellyfin control-plane and metadata adapters.

The API coordinates sessions and metadata. Video bytes/HLS segments are served by
the dedicated Jellyfin host, never by Vercel serverless functions.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/media", tags=["Streamivio Media Engine"])
TIMEOUT = httpx.Timeout(12.0, connect=5.0)


def jellyfin_url() -> str:
    value = os.getenv("JELLYFIN_URL", "").strip().rstrip("/")
    if not value:
        raise HTTPException(status_code=503, detail="Jellyfin server is not configured")
    return value


def client_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "X-Emby-Authorization": 'MediaBrowser Client="Streamivio", Device="Web", DeviceId="streamivio-web", Version="1.0.0"',
    }
    if token:
        # Jellyfin accepts the user's session token in the MediaBrowser header.
        headers["X-Emby-Token"] = token
        headers["Authorization"] = f'MediaBrowser Token="{token}"'
    return headers


async def jf(method: str, path: str, token: str | None = None, **kwargs: Any) -> Any:
    url = f"{jellyfin_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.request(method, url, headers=client_headers(token), **kwargs)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Jellyfin connection failed: {type(exc).__name__}") from exc
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Jellyfin authentication failed")
    if response.status_code == 403:
        raise HTTPException(status_code=403, detail="Jellyfin denied this operation")
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Jellyfin item was not found")
    if response.is_error:
        raise HTTPException(status_code=502, detail=f"Jellyfin returned HTTP {response.status_code}")
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {"text": response.text}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=512)


class PlaybackRequest(BaseModel):
    device_id: str = Field(default="streamivio-web", min_length=3, max_length=128)
    max_bitrate: int | None = Field(default=None, ge=250_000, le=80_000_000)
    audio_stream_index: int | None = Field(default=None, ge=0)
    subtitle_stream_index: int | None = Field(default=None, ge=-1)


def require_token(authorization: str | None, x_emby_token: str | None) -> str:
    token = x_emby_token
    if not token and authorization:
        # Accept a Jellyfin MediaBrowser token, never a Streamivio admin key.
        marker = 'Token="'
        if marker in authorization:
            token = authorization.split(marker, 1)[1].split('"', 1)[0]
        elif authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
    if not token or len(token) > 4096:
        raise HTTPException(status_code=401, detail="Sign in to Streamivio to continue")
    return token


def auth_token(authorization: str | None, x_emby_token: str | None) -> str:
    return require_token(authorization, x_emby_token)


@router.get("/health")
async def media_health():
    configured = bool(os.getenv("JELLYFIN_URL", "").strip())
    if not configured:
        return {"service": "streamivio-media-engine", "status": "needs_configuration", "jellyfin": False}
    try:
        data = await jf("GET", "/System/Info/Public")
        return {"service": "streamivio-media-engine", "status": "ok", "jellyfin": True, "server_name": data.get("ServerName")}
    except HTTPException as exc:
        return {"service": "streamivio-media-engine", "status": "unavailable", "jellyfin": False, "reason": exc.detail}


@router.post("/auth/login")
async def media_login(payload: LoginRequest):
    data = await jf(
        "POST",
        "/Users/AuthenticateByName",
        json={"Username": payload.username, "Pw": payload.password},
        headers={"Content-Type": "application/json", **client_headers()},
    )
    user = data.get("User") or {}
    token = data.get("AccessToken")
    if not token or not user.get("Id"):
        raise HTTPException(status_code=502, detail="Jellyfin did not return a valid user session")
    return {
        "access_token": token,
        "token_type": "MediaBrowser",
        "user": {"id": user.get("Id"), "name": user.get("Name")},
        "server": data.get("ServerId"),
    }


@router.get("/libraries")
async def media_libraries(authorization: str | None = Header(default=None), x_emby_token: str | None = Header(default=None)):
    token = auth_token(authorization, x_emby_token)
    return await jf("GET", "/Library/VirtualFolders", token)


@router.get("/items")
async def media_items(
    q: str | None = Query(default=None, max_length=150),
    parent_id: str | None = None,
    include_types: str | None = None,
    limit: int = Query(default=40, ge=1, le=100),
    start_index: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
    x_emby_token: str | None = Header(default=None),
):
    token = auth_token(authorization, x_emby_token)
    user = await jf("GET", "/Users/Me", token)
    params: dict[str, Any] = {
        "UserId": user["Id"], "Recursive": "true", "StartIndex": start_index,
        "Limit": limit, "Fields": "Overview,Genres,People,ProviderIds,MediaSources,DateCreated,PremiereDate,RunTimeTicks",
        "ImageTypeLimit": 1, "EnableImageTypes": "Primary,Backdrop,Thumb",
    }
    if q:
        params["SearchTerm"] = q
    if parent_id:
        params["ParentId"] = parent_id
    if include_types:
        params["IncludeItemTypes"] = include_types
    return await jf("GET", f"/Users/{user['Id']}/Items", token, params=params)


@router.get("/items/{item_id}")
async def media_item(item_id: str, authorization: str | None = Header(default=None), x_emby_token: str | None = Header(default=None)):
    token = auth_token(authorization, x_emby_token)
    return await jf("GET", f"/Items/{item_id}", token, params={"Fields": "Overview,Genres,People,ProviderIds,MediaSources,DateCreated,PremiereDate,RunTimeTicks"})


@router.post("/items/{item_id}/playback-info")
async def playback_info(
    item_id: str,
    payload: PlaybackRequest,
    authorization: str | None = Header(default=None),
    x_emby_token: str | None = Header(default=None),
):
    token = auth_token(authorization, x_emby_token)
    params: dict[str, Any] = {"UserId": (await jf("GET", "/Users/Me", token))["Id"], "EnableDirectPlay": "true", "EnableDirectStream": "true", "EnableTranscoding": "true", "AutoOpenLiveStream": "true", "DeviceId": payload.device_id}
    if payload.max_bitrate:
        params["MaxStreamingBitrate"] = payload.max_bitrate
    if payload.audio_stream_index is not None:
        params["AudioStreamIndex"] = payload.audio_stream_index
    if payload.subtitle_stream_index is not None:
        params["SubtitleStreamIndex"] = payload.subtitle_stream_index
    result = await jf("GET", f"/Items/{item_id}/PlaybackInfo", token, params=params)
    # Provide the server origin so the client can play the HLS/direct stream itself.
    result["Streamivio"] = {
        "server_url": jellyfin_url(),
        "delivery": "Jellyfin direct play or adaptive HLS/transcoding",
        "note": "The browser connects directly to the configured Jellyfin host for media bytes.",
    }
    return result


@router.post("/sessions/{item_id}/progress")
async def playback_progress(
    item_id: str,
    position_ticks: int = Query(ge=0),
    is_paused: bool = False,
    authorization: str | None = Header(default=None),
    x_emby_token: str | None = Header(default=None),
):
    token = auth_token(authorization, x_emby_token)
    return await jf("POST", f"/Sessions/Playing/Progress", token, params={"ItemId": item_id, "PositionTicks": position_ticks, "IsPaused": str(is_paused).lower()})


@router.post("/sessions/{item_id}/stopped")
async def playback_stopped(
    item_id: str,
    position_ticks: int = Query(ge=0),
    authorization: str | None = Header(default=None),
    x_emby_token: str | None = Header(default=None),
):
    token = auth_token(authorization, x_emby_token)
    return await jf("POST", "/Sessions/Playing/Stopped", token, params={"ItemId": item_id, "PositionTicks": position_ticks})


@router.get("/subtitles/languages")
async def subtitle_languages():
    return {"supported": ["en", "sw", "ja", "fr", "es", "de", "pt", "ar"], "formats": ["srt", "vtt", "ass", "ssa", "pgs", "vobsub"], "source": "embedded, sidecar, or configured authorised subtitle provider"}


@router.get("/metadata/anilist")
async def anilist_search(q: str = Query(min_length=2, max_length=100), page: int = Query(default=1, ge=1, le=100)):
    query = """
    query ($search: String, $page: Int) {
      Page(page: $page, perPage: 20) {
        media(search: $search, type: ANIME) {
          id idMal format status episodes seasonYear averageScore description(asHtml: false)
          title { romaji english native }
          coverImage { extraLarge large }
          genres
        }
      }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post("https://graphql.anilist.co", json={"query": query, "variables": {"search": q, "page": page}})
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="AniList metadata provider is unavailable") from exc
    return {"provider": "AniList", "results": payload.get("data", {}).get("Page", {}).get("media", [])}


@router.get("/providers")
async def provider_status():
    configured = [name.strip() for name in os.getenv("STREAMIVIO_LICENSED_PROVIDERS", "").split(",") if name.strip()]
    return {
        "jellyfin": bool(os.getenv("JELLYFIN_URL", "").strip()),
        "metadata": {"anilist": True, "imdb_suggestion": True, "omdb": bool(os.getenv("OMDB_API_KEY"))},
        "licensed_external_providers": [{"id": name, "configured": True} for name in configured],
        "external_provider_policy": "Only provider APIs and playback URLs supplied under a valid operator agreement are enabled.",
    }
