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
