import unittest

from fastapi import HTTPException

from api import open_sources


class NoKeyCatalogueTests(unittest.TestCase):
    def test_film_class_is_detected(self):
        claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q11424"}}}}]}
        self.assertTrue(open_sources._kind_matches(claims, "movie"))
        self.assertFalse(open_sources._kind_matches(claims, "series"))

    def test_anime_class_is_detected(self):
        claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q63952888"}}}}]}
        self.assertTrue(open_sources._kind_matches(claims, "anime"))

    def test_wikidata_result_has_source_and_license_attribution(self):
        entity = {
            "id": "Q123",
            "labels": {"en": {"value": "Example Film"}},
            "descriptions": {"en": {"value": "An example film."}},
            "claims": {
                "P577": [{"mainsnak": {"datavalue": {"value": {"time": "+2020-01-01T00:00:00Z"}}}}],
                "P18": [{"mainsnak": {"datavalue": {"value": "Example poster.jpg"}}}],
                "P345": [{"mainsnak": {"datavalue": {"value": "tt1234567"}}}],
            },
        }
        result = open_sources._normalise_wikidata(entity, "movie")
        self.assertEqual(result["title"], "Example Film")
        self.assertEqual(result["year"], 2020)
        self.assertEqual(result["metadata_license"], "CC0 (Wikidata structured data)")
        self.assertIn("commons.wikimedia.org", result["poster_url"])
        self.assertIn("individual Commons file page", result["artwork_license_note"])

    def test_only_cc0_and_public_domain_mark_are_allowlisted(self):
        self.assertIn("https://creativecommons.org/publicdomain/zero/1.0/", open_sources.ALLOWED_LICENSES)
        self.assertNotIn("https://creativecommons.org/licenses/by-nc/4.0/", open_sources.ALLOWED_LICENSES)
        self.assertNotIn("https://creativecommons.org/licenses/by/4.0/", open_sources.ALLOWED_LICENSES)

    def test_invalid_archive_identifier_is_rejected_before_network(self):
        async def run():
            with self.assertRaises(HTTPException) as error:
                await open_sources.public_domain_playback("../not-a-valid-id")
            self.assertEqual(error.exception.status_code, 400)
        import asyncio
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
