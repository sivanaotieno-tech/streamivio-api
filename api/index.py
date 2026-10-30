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
        rows = data.get("titles", []) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []
        return [normalize_title(item) for item in rows if isinstance(item, dict) and item.get("published", True)]
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
        "rating": item.get("rating"),
        "overview": str(item.get("overview") or item.get("description") or ""),
        "poster_url": item.get("poster_url") or item.get("poster"),
        "genres": genres,
        "country": item.get("country") if isinstance(item.get("country"), list) else ([item.get("country")] if item.get("country") else []),
        "age_rating": item.get("age_rating") or item.get("ageRating"),
        "original_title": item.get("original_title") or title,
        "alternate_titles": item.get("alternate_titles") or item.get("aliases") or [],
        "keywords": item.get("keywords") or item.get("tags") or [],
        "cast": item.get("cast") or item.get("actors") or [],
        "directors": item.get("directors") or [],
        "playback_available": bool(item.get("video_url")),
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
    title_fields = [
        name,
        str(title.get("original_title") or "").casefold(),
        *(str(value).casefold() for value in title.get("alternate_titles", []) or []),
    ]
    metadata_fields = [
        str(title.get("overview") or "").casefold(),
        str(title.get("type") or "").casefold(),
        str(title.get("year") or "").casefold(),
        str(title.get("age_rating") or "").casefold(),
        *(str(value).casefold() for field in ("genres", "keywords", "country", "cast", "directors") for value in (title.get(field) or [])),
    ]
    if name == q:
        score = 1000
    elif any(value.startswith(q) for value in title_fields):
        score = 800
    elif any(q in value for value in title_fields):
        score = 600
    elif any(q in value for value in metadata_fields):
        score = 180
    else:
        score = 0
    query_words = [word for word in re.findall(r"[a-z0-9]+", q) if word not in {"a", "an", "and", "for", "in", "of", "or", "the", "to", "with"}]
    title_words = set(re.findall(r"[a-z0-9]+", " ".join(title_fields)))
    metadata_words = set(re.findall(r"[a-z0-9]+", " ".join(metadata_fields)))
    matched = 0
    for word in query_words:
        if word in title_words:
            score += 80
            matched += 1
        elif any(candidate.startswith(word) or (len(word) >= 4 and word in candidate) for candidate in title_words):
            score += 45
            matched += 1
        elif word in metadata_words:
            score += 15
            matched += 1
    if query_words and matched == len(query_words):
        score += 50
    return score


def get_catalog() -> list[dict[str, Any]]:
    return load_catalog()


async def resolve_imdb_id(title: str, year: str | None = None, kind: str = "movie") -> dict[str, Any] | None:
    """Resolve a catalog title to an IMDb ID using IMDb's public suggestion data."""
    clean = re.sub(r"[^A-Za-z0-9 ]", "", title).strip()
    if len(clean) < 2:
        return None
    first = clean[0].lower()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", clean).strip("_")
    url = f"https://v2.sg.media-imdb.com/suggestion/{first}/{slug}.json"
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "application/json", "User-Agent": "Streamivio/1.0"})
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    rows = payload.get("d", []) if isinstance(payload, dict) else []
    wanted = re.sub(r"[^a-z0-9]", "", title.casefold())
    candidates = []
    for row in rows:
        if not isinstance(row, dict) or not re.fullmatch(r"tt\d{5,12}", str(row.get("id", ""))):
            continue
        candidate_title = str(row.get("l") or "").strip()
        candidate_norm = re.sub(r"[^a-z0-9]", "", candidate_title.casefold())
        candidate_year = str(row.get("y") or "")
        if candidate_norm != wanted:
            continue
        if year and candidate_year and candidate_year != str(year):
            continue
        row_type = str(row.get("q") or "").casefold()
        is_tv = any(word in row_type for word in ("tv", "series", "episode", "mini"))
        if (kind == "tv") != is_tv and row_type:
            continue
        candidates.append({
            "imdb_id": row["id"],
            "title": candidate_title,
            "year": candidate_year or year,
            "type": "tv" if is_tv else "movie",
            "poster_url": row.get("i", {}).get("imageUrl") if isinstance(row.get("i"), dict) else None,
        })
    return candidates[0] if candidates else None


@app.get("/")
async def root():
    return {"name": "Streamivio API", "version": app.version, "docs": "/docs", "health": "/health"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "streamivio-api", "catalog_titles": len(get_catalog())}


@app.get("/catalog")
async def catalog_endpoint(
    q: str | None = None,
    type: str | None = None,
    category: str | None = None,
    genre: str | None = None,
    country: str | None = None,
    year: str | None = None,
    sort: str = "relevance",
    limit: int = Query(default=60, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    rows = get_catalog()
    if q:
        rows = [row for row in rows if search_score(row, q) > 0]
    if type:
        wanted = type.casefold()
        rows = [row for row in rows if row["type"] == wanted or (wanted == "tv" and row["type"] in {"anime", "documentary", "kids", "reality"})]
    if category:
        rows = [row for row in rows if str(row.get("category") or "").casefold() == category.casefold()]
    if genre:
        rows = [row for row in rows if any(str(item).casefold() == genre.casefold() for item in row.get("genres", []))]
    if country:
        rows = [row for row in rows if any(str(item).casefold() == country.casefold() for item in row.get("country", []))]
    if year:
        rows = [row for row in rows if str(row.get("year") or "") == year]
    if sort == "title":
        rows.sort(key=lambda row: row["title"].casefold())
    elif sort == "year":
        rows.sort(key=lambda row: str(row.get("year") or ""), reverse=True)
    elif sort == "rating":
        rows.sort(key=lambda row: float(row.get("rating") or 0), reverse=True)
    elif q:
        rows.sort(key=lambda row: search_score(row, q), reverse=True)
    total = len(rows)
    return {"results": rows[offset:offset + limit], "total": total, "limit": limit, "offset": offset}


@app.get("/search")
async def search_endpoint(q: str = Query(min_length=2, max_length=100), type: str | None = None, limit: int = Query(default=30, ge=1, le=100)):
    result = await catalog_endpoint(q=q, type=type, limit=limit, offset=0)
    return result


@app.get("/title/{title_id}")
async def title_endpoint(title_id: str):
    row = next((item for item in get_catalog() if item["id"] == title_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Title not found")
    return row


@app.get("/resolve")
async def resolve_endpoint(title: str = Query(min_length=2, max_length=150), year: str | None = None, type: str = "movie"):
    kind = "tv" if type in {"tv", "anime", "documentary", "kids", "reality"} else "movie"
    result = await resolve_imdb_id(title, year, kind)
    if not result:
        raise HTTPException(status_code=404, detail="No exact IMDb match found for this title and year")
    return {"resolved": True, **result}


@app.get("/playback/{title_id}")
async def playback_endpoint(title_id: str):
    row = next((item for item in get_catalog() if item["id"] == title_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Title not found")
    if row.get("imdb_id") or row.get("tmdb_id"):
        return {"resolved": True, "available": False, "imdb_id": row.get("imdb_id"), "tmdb_id": row.get("tmdb_id"), "title": row["title"]}
    resolved = await resolve_imdb_id(row["title"], str(row.get("year") or "") or None, row["type"])
    if not resolved:
        raise HTTPException(status_code=404, detail="No exact IMDb match found; add a verified imdb_id or tmdb_id to the catalog.")
    return {"resolved": True, "available": False, **resolved, "message": "Provider ID resolved. Configure an authorized playback provider to play this title."}


@app.get("/featured")
async def featured_endpoint(limit: int = Query(default=12, ge=1, le=50)):
    rows = get_catalog()
    featured = [row for row in rows if row.get("featured")]
    if not featured:
        featured = sorted(rows, key=lambda row: float(row.get("rating") or 0), reverse=True)
    return {"results": featured[:limit], "total": len(featured[:limit])}


@app.get("/categories")
async def categories_endpoint():
    return {"results": sorted({str(row.get("category")) for row in get_catalog() if row.get("category")})}


@app.get("/genres")
async def genres_endpoint():
    return {"results": sorted({genre for row in get_catalog() for genre in row.get("genres", [])})}
