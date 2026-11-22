import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
import api.media_engine as media_engine


class StreamivioMediaEngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.catalog = Path(self.temp.name) / "catalog.json"
        self.patch_catalog = patch.object(media_engine, "CATALOG_PATH", self.catalog)
        self.patch_catalog.start()
        self.env = patch.dict(os.environ, {
            "STREAMX_API_BASE": "",
            "STREAMX_UPSTREAM_TERMS_APPROVED": "false",
            "ANILIST_USAGE_APPROVED": "false",
            "HOVOD_API_URL": "",
            "HOVOD_ALLOWED_MEDIA_HOSTS": "",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.patch_catalog.stop()
        self.temp.cleanup()

    def write_catalog(self, rows):
        self.catalog.write_text(json.dumps({"titles": rows}), encoding="utf-8")

    async def test_health_is_standalone(self):
        response = await media_engine.media_health()
        self.assertEqual(response["service"], "streamivio-media-engine")
        self.assertNotIn("jellyfin", response)

    async def test_search_fallback_filters_documentaries(self):
        self.write_catalog([
            {"id": "film-1", "title": "Planet Earth", "type": "movie"},
            {"id": "doc-1", "title": "Planet Ocean", "type": "documentary"},
        ])
        response = await media_engine.media_search(q="planet", kind="documentary")
        self.assertEqual([row["id"] for row in response["results"]], ["doc-1"])

    async def test_anilist_is_not_enabled_without_explicit_approval(self):
        self.write_catalog([])
        with patch.dict(os.environ, {
            "STREAMX_API_BASE": "https://metadata.example.org",
            "STREAMX_UPSTREAM_TERMS_APPROVED": "true",
            "ANILIST_USAGE_APPROVED": "false",
        }):
            with self.assertRaises(HTTPException) as error:
                await media_engine.media_search(q="one piece", kind="anime")
        self.assertEqual(error.exception.status_code, 503)

    async def test_playback_requires_rights_record(self):
        self.write_catalog([{"id": "sample", "title": "Sample", "playback": {"hovod_playback_id": "Abcdefgh1234"}}])
        with self.assertRaises(HTTPException) as error:
            await media_engine.media_playback(title_id="sample")
        self.assertEqual(error.exception.status_code, 403)

    async def test_playback_requires_hovod_configuration_after_rights(self):
        self.write_catalog([{
            "id": "sample", "title": "Sample",
            "distribution_authorized": True,
            "rights_status": "public_domain",
            "rights_reference": "https://example.org/rights",
            "playback": {"hovod_playback_id": "Abcdefgh1234"},
        }])
        with self.assertRaises(HTTPException) as error:
            await media_engine.media_playback(title_id="sample")
        self.assertEqual(error.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
