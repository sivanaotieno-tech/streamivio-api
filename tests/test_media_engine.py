import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from api.index import app
import api.media_engine as media_engine


class StreamivioMediaEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.catalog = Path(self.temp.name) / "catalog.json"
        self.patch_catalog = patch.object(media_engine, "CATALOG_PATH", self.catalog)
        self.patch_catalog.start()
        self.env = patch.dict("os.environ", {
            "STREAMX_API_BASE": "",
            "STREAMX_UPSTREAM_TERMS_APPROVED": "false",
            "HOVOD_API_URL": "",
            "HOVOD_ALLOWED_MEDIA_HOSTS": "",
        })
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env.stop()
        self.patch_catalog.stop()
        self.temp.cleanup()

    def write_catalog(self, rows):
        self.catalog.write_text(json.dumps({"titles": rows}), encoding="utf-8")

    def test_health_is_standalone(self):
        response = self.client.get("/media/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["service"], "streamivio-media-engine")
        self.assertNotIn("jellyfin", response.json())

    def test_search_fallback_filters_documentaries(self):
        self.write_catalog([
            {"id": "film-1", "title": "Planet Earth", "type": "movie"},
            {"id": "doc-1", "title": "Planet Ocean", "type": "documentary"},
        ])
        response = self.client.get("/media/search?q=planet&kind=documentary")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()["results"]], ["doc-1"])

    def test_playback_requires_rights_record(self):
        self.write_catalog([{"id": "sample", "title": "Sample", "playback": {"hovod_playback_id": "Abcdefgh1234"}}])
        response = self.client.get("/media/playback/sample")
        self.assertEqual(response.status_code, 403)

    def test_playback_requires_hovod_configuration_after_rights(self):
        self.write_catalog([{
            "id": "sample", "title": "Sample",
            "distribution_authorized": True,
            "rights_status": "public_domain",
            "rights_reference": "https://example.org/rights",
            "playback": {"hovod_playback_id": "Abcdefgh1234"},
        }])
        response = self.client.get("/media/playback/sample")
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
