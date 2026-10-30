# Streamivio API

Standalone FastAPI backend for the Streamivio web application.

## Features

- Health and API information endpoints
- Search and browse a local title catalog
- Normalized movie and TV title records
- Optional OMDb metadata enrichment (requires an API key)
- CORS configured for the Streamivio frontend
- Vercel-compatible Python deployment

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.index:app --reload
```

Open `http://127.0.0.1:8000/docs` for interactive API documentation.

## Endpoints

- `GET /health`
- `GET /`
- `GET /catalog`
- `GET /search?q=sonic`
- `GET /title/{id}`
- `GET /featured`
- `GET /categories`
- `GET /genres`
- `GET /playback/{id}`

## Catalog

Add authorized title metadata to `catalog.json`. Each record should include a stable `id`, `title`, and `type` (`movie` or `tv`). Optional fields include `year`, `overview`, `poster_url`, `genres`, `category`, `imdb_id`, `tmdb_id`, `featured`, and `playback`.

The API returns metadata only. It does not host, scrape, proxy, or provide unauthorized copies of copyrighted video. A playback record should point only to media the operator is authorized to distribute, or to an official provider/embed URL.

## Environment variables

- `STREAMIVIO_ALLOWED_ORIGINS`: comma-separated frontend origins. Defaults include the Streamivio Vercel app.
- `OMDB_API_KEY`: optional key for OMDb title lookup when the local catalog has no match.

Never commit API keys. Configure them in Vercel Project Settings → Environment Variables.

## Deploy to Vercel

Import this GitHub repository as a separate Vercel project. Select **FastAPI** if prompted; Vercel should detect the Python FastAPI application. The `vercel.json` rewrite routes requests to `api/index.py`.
