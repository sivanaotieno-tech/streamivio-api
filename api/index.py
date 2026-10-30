from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "catalog.json"

app = FastAPI(
    title="Streamivio API",
    description="Search and metadata API for the Streamivio web application.",
    version="1.0.0",
)

origins = [
    item.strip().rstrip("/")
    for item in os.getenv(
        "STREAMIVIO_ALLOWED_ORIGINS",
        "https://streamivio.vercel.app,https://streamflix-zfep-sivanaotieno-techs-projects.vercel.app",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


def load_catalog() -> list[dict[str, Any]]:
    try:
        with CATALOG_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, list):
            return []
        return [normalize_title(item) for item in data if isinstance(item, dict)]
    except (OSError, json.JSONDecodeError):
        return []


def normalize_title(item: dict[str, Any]) -> dict[str, Any]:
    title = str(item.get("title") or item.get("name") or "").strip()
    raw_type = str(item.get("type") or item.get("media_type") or "movie").lower()
    aliases = {"show": "tv", "series": "tv", "tvshow": "tv", "tv_show": "tv", "documentaries": "documentary"}
    media_type = aliases.get(raw_type, raw_type)
    if media_type not in {"movie", "tv", "anime", "documentary", "kids", "reality"}:
        media_type = "movie"
    genres = item.get("genres") or []
    if isinstance(genres, str):
        genres = [part.strip() for part in genres.split(",") if part.strip()]
    if not isinstance(genres, list):
        genres = []
    playback = item.get("playback") if isinstance(item.get("playback"), dict) else {}
    return {
        "id": str(item.get("id") or item.get("imdb_id") or slugify(title)),
        "title": title,
        "type": media_type,
        "year": item.get("year"),
        "overview": str(item.get("overview") or item.get("description") or ""),
        "poster_url": item.get("poster_url") or item.get("poster"),
        "genres": genres,
        "category": item.get("category"),
        "imdb_id": item.get("imdb_id"),
        "tmdb_id": item.get("tmdb_id"),
        "featured": bool(item.get("featured", False)),
        "playback": playback,
    }


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value or "untitled"


def search_score(title: dict[str, Any], query: str) -> int:
    q = query.casefold().strip()
    name = title["title"].casefold()
    if name == q:
        return 100
    if name.startswith(q):
        return 80
    if q in name:
        return 60
    words = set(re.findall(r"[a-z0-9]+", q))
    target = set(re.findall(r"[a-z0-9]+", name))
    if words and words.issubset(target):
        return 40
    return 0


async def omdb_search(query: str, media_type: str | None, limit: int) -> list[dict[str, Any]]:
    key = os.getenv("OMDB_API_KEY")
    if not key:
        return []
    params: dict[str, str] = {"apikey": key, "s": query}
    if media_type in {"movie", "tv"}:
        params["type"] = media_type
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get("https://www.omdbapi.com/", params=params)
            response.raise_for_status()
            payload = response.json()
        if payload.get("Response") != "True":
            return []
        results = []
        for item in payload.get("Search", [])[:limit]:
            results.append(normalize_title({
                "id": item.get("imdbID"),
                "title": item.get("Title"),
                "type": item.get("Type"),
                "year": item.get("Year"),
                "poster_url": item.get("Poster") if item.get("Poster") != "N/A" else None,
                "imdb_id": item.get("imdbID"),
            }))
        return results
    except (httpx.HTTPError, ValueError):
        return []


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "name": "Streamivio API",
        "version": app.version,
        "status": "online",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "streamivio-api", "catalog_count": len(load_catalog())}


@app.get("/catalog")
async def catalog(
    q: str | None = Query(default=None, min_length=1, max_length=120),
    type: str | None = Query(default=None, pattern="^(movie|tv|anime|documentary|kids|reality)$"),
    category: str | None = None,
    genre: str | None = None,
    country: str | None = None,
    year: str | None = Query(default=None, pattern="^\\d{4}$"),
    sort: str = Query(default="relevance", pattern="^(relevance|rating|year|title)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    items = load_catalog()
    if type:
        items = [item for item in items if item["type"] == type]
    if category:
        items = [item for item in items if str(item.get("category") or "").casefold() == category.casefold()]
    if genre:
        items = [item for item in items if any(genre.casefold() == str(g).casefold() for g in item["genres"])]
    if country:
        items = [item for item in items if any(country.casefold() in str(c).casefold() for c in (item.get("country") or []))]
    if year:
        items = [item for item in items if str(item.get("year") or "")[:4] == year]
    if q:
        items = [item for item in items if search_score(item, q) > 0]
        items.sort(key=lambda item: search_score(item, q), reverse=True)
    elif sort == "title":
        items.sort(key=lambda item: item["title"].casefold())
    elif sort == "year":
        items.sort(key=lambda item: int(str(item.get("year") or "0")[:4]) if str(item.get("year") or "")[:4].isdigit() else 0, reverse=True)
    return {"results": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}


@app.get("/search")
async def search(
    q: str = Query(min_length=1, max_length=120),
    type: str | None = Query(default=None, pattern="^(movie|tv)$"),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Search query cannot be empty.")
    local = [item for item in load_catalog() if (not type or item["type"] == type)]
    ranked = [(search_score(item, query), item) for item in local]
    matches = [item for score, item in sorted(ranked, key=lambda pair: pair[0], reverse=True) if score > 0]
    source = "catalog"
    if not matches:
        matches = await omdb_search(query, type, limit)
        source = "omdb" if matches else "catalog"
    return {"query": query, "results": matches[:limit], "total": len(matches), "source": source}


@app.get("/title/{title_id}")
async def title_details(title_id: str) -> dict[str, Any]:
    for item in load_catalog():
        if item["id"].casefold() == title_id.casefold() or str(item.get("imdb_id") or "").casefold() == title_id.casefold():
            return item
    key = os.getenv("OMDB_API_KEY")
    if key and title_id.startswith("tt"):
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get("https://www.omdbapi.com/", params={"apikey": key, "i": title_id, "plot": "full"})
                response.raise_for_status()
                data = response.json()
            if data.get("Response") == "True":
                return normalize_title({
                    "id": data.get("imdbID"), "title": data.get("Title"),
                    "type": data.get("Type"), "year": data.get("Year"),
                    "overview": data.get("Plot"), "poster_url": data.get("Poster"),
                    "genres": data.get("Genre"), "imdb_id": data.get("imdbID"),
                })
        except (httpx.HTTPError, ValueError):
            pass
    raise HTTPException(status_code=404, detail="Title not found in the catalog or configured metadata provider.")


@app.get("/featured")
async def featured(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    items = [item for item in load_catalog() if item["featured"]]
    return {"results": items[:limit], "total": len(items)}


@app.get("/categories")
async def categories() -> dict[str, Any]:
    values = sorted({str(item["category"]) for item in load_catalog() if item.get("category")})
    return {"results": values, "total": len(values)}


@app.get("/genres")
async def genres() -> dict[str, Any]:
    values = sorted({str(genre) for item in load_catalog() for genre in item["genres"] if genre})
    return {"results": values, "total": len(values)}


@app.get("/playback/{title_id}")
async def playback(title_id: str) -> dict[str, Any]:
    item = await title_details(title_id)
    playback_data = item.get("playback") or {}
    if not playback_data:
        raise HTTPException(status_code=404, detail="No authorized playback source is configured for this title.")
    return {"id": item["id"], "title": item["title"], "type": item["type"], **playback_data}
