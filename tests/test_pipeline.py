import sys
import unittest
from pathlib import Path

# Add project root to sys.path so we can import config, utils, processors
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from processors.normalizer import Normalizer
from processors.entity_extractor import EntityExtractor
from utils.helpers import format_entity_name, google_api_retry
from utils.google_sheets import GoogleSheetsConnector

class TestNormalizer(unittest.TestCase):
    def setUp(self):
        self.normalizer = Normalizer()

    def test_strip_titles(self):
        """
        Verify that common pre-nominal titles and trailing honorifics are recursively stripped.
        """
        self.assertEqual(self.normalizer.strip_titles("PM Narendra Modi"), "Narendra Modi")
        self.assertEqual(self.normalizer.strip_titles("Shri Amit Shah ji"), "Amit Shah")
        self.assertEqual(self.normalizer.strip_titles("Chief Minister Yogi Adityanath"), "Yogi Adityanath")
        self.assertEqual(self.normalizer.strip_titles("Dr S Jaishankar"), "S Jaishankar")
        self.assertEqual(self.normalizer.strip_titles("Union Minister Nitin Gadkari"), "Nitin Gadkari")

    def test_normalize_entity_direct(self):
        """
        Check that political parties, ministries, states, cities, and countries resolve to canonical forms.
        """
        # Parties
        self.assertEqual(self.normalizer.normalize_entity("bjp", "political_parties"), "Bharatiya Janata Party")
        self.assertEqual(self.normalizer.normalize_entity("Congress Party", "political_parties"), "Indian National Congress")
        
        # Ministries
        self.assertEqual(self.normalizer.normalize_entity("MEA", "organizations"), "Ministry of External Affairs")
        self.assertEqual(self.normalizer.normalize_entity("home ministry", "organizations"), "Ministry of Home Affairs")
        
        # States & Cities
        self.assertEqual(self.normalizer.normalize_entity("up", "states"), "Uttar Pradesh")
        self.assertEqual(self.normalizer.normalize_entity("Bangalore", "cities"), "Bengaluru")
        self.assertEqual(self.normalizer.normalize_entity("Bombay", "cities"), "Mumbai")
        
        # Countries
        self.assertEqual(self.normalizer.normalize_entity("us", "countries"), "United States")
        self.assertEqual(self.normalizer.normalize_entity("bharat", "countries"), "India")

    def test_casing_and_abbreviations(self):
        """
        Test that known political acronyms retain their uppercase casing, while other strings are capitalised.
        """
        self.assertEqual(format_entity_name("bjp leader"), "BJP Leader")
        self.assertEqual(format_entity_name("pm modi"), "PM Modi")
        self.assertEqual(format_entity_name("external affairs ministry"), "External Affairs Ministry")

    def test_contextual_resolution(self):
        """
        Tests the dynamic contextual resolution engine in article scope.
        1. Standalone "Rahul" is resolved to "Rahul Gandhi" if "Rahul Gandhi" is present.
        2. Standalone "Modi" resolves to "Narendra Modi" if "Narendra Modi" is present.
        3. Ambiguous names remain unchanged if no full anchor is present.
        """
        raw_text = "Rahul Gandhi visited UP. Rahul spoke about the farmers."
        
        # Mock extracted entities before resolution
        raw_entities = {
            "people": ["Rahul Gandhi", "Rahul"],
            "political_parties": [],
            "states": ["Uttar Pradesh"],
            "cities": [],
            "countries": [],
            "organizations": [],
            "topics": []
        }
        
        resolved = self.normalizer.resolve_article_context(raw_entities, raw_text)
        
        # "Rahul" must have been resolved and merged into "Rahul Gandhi"
        self.assertEqual(resolved["people"], ["Rahul Gandhi"])
        self.assertEqual(resolved["states"], ["Uttar Pradesh"])

        # Multiple anchors check (cannot uniquely resolve)
        raw_text_2 = "Rahul Gandhi and Sonia Gandhi attended. Gandhi gave a speech."
        raw_entities_2 = {
            "people": ["Rahul Gandhi", "Sonia Gandhi", "Gandhi"],
            "political_parties": [],
            "states": [],
            "cities": [],
            "countries": [],
            "organizations": [],
            "topics": []
        }
        resolved_2 = self.normalizer.resolve_article_context(raw_entities_2, raw_text_2)
        # Standalone "Gandhi" cannot be uniquely resolved to Rahul or Sonia without specific bias, 
        # so it is kept as "Gandhi"
        self.assertIn("Gandhi", resolved_2["people"])
        self.assertIn("Rahul Gandhi", resolved_2["people"])
        self.assertIn("Sonia Gandhi", resolved_2["people"])


class TestEntityExtractor(unittest.TestCase):
    def setUp(self):
        self.normalizer = Normalizer()
        self.extractor = EntityExtractor(self.normalizer)

    def test_topic_keyword_extraction(self):
        """
        Test that Step 1 topic keyword mapping successfully captures categories without false positives.
        """
        text_1 = "The government announced the budget for defense spending in the upcoming elections."
        topics_1 = self.extractor.extract_topics(text_1)
        
        # Expected topics
        self.assertIn("Elections", topics_1)
        self.assertIn("Budget & Economy", topics_1)
        self.assertIn("Defense & Security", topics_1)
        self.assertNotIn("Corruption & Judiciary", topics_1)

        text_2 = "Farmers protest in Delhi against the passed legislation bill."
        topics_2 = self.extractor.extract_topics(text_2)
        self.assertIn("Protests & Movements", topics_2)
        self.assertIn("Legislation", topics_2)

    def test_entity_extraction_integration(self):
        """
        Performs extraction on a combined news snippet and checks exact category sortings.
        """
        title = "PM Modi holds bilateral meeting"
        summary = "PM Narendra Modi met Amit Shah and leaders in New Delhi."
        content = "The meeting focused on the upcoming BJP election campaign and bilateral ties with the US."
        
        results = self.extractor.extract_entities(title, summary, content)
        
        # People Checks
        self.assertIn("Narendra Modi", results["people"])
        self.assertIn("Amit Shah", results["people"])
        
        # Party Checks
        self.assertIn("Bharatiya Janata Party", results["political_parties"])
        
        # Cities, States, Countries
        self.assertIn("New Delhi", results["cities"])
        self.assertIn("United States", results["countries"])
        
        # Topic Checks
        self.assertIn("Elections", results["topics"])
        self.assertIn("Diplomacy & Foreign Relations", results["topics"])


class TestSheetsRowParser(unittest.TestCase):
    def setUp(self):
        # We don't authenticate with Google APIs in unit tests, we test the row parsing logic
        self.connector = GoogleSheetsConnector.__new__(GoogleSheetsConnector)

    def test_parse_multi_column_row(self):
        """
        Checks parsing direct spreadsheet columns.
        """
        row_data = {
            "ID": 192,
            "Title": "Scraper Test",
            "Summary": "A test summary",
            "Content": "The full content of the test article.",
            "Published_At": "2026-05-22T02:00:00Z",
            "Source": "RSS Feed",
            "Url": "https://example.com/test"
        }
        
        parsed = self.connector.extract_fields_from_dict(row_data, 1)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["article_id"], "192") # ID cast as string during parsing
        self.assertEqual(parsed["title"], "Scraper Test")
        self.assertEqual(parsed["source"], "RSS Feed")
        self.assertEqual(parsed["url"], "https://example.com/test")

    def test_parse_json_column_row(self):
        """
        Checks parsing when row contains a single JSON column.
        """
        row_data = {
            "json": '{"id": 405, "title": "JSON Column Test", "summary": "Short", "content": "Body", "published_at": "2026-05-22", "source": "API", "url": "http://test.org"}'
        }
        
        parsed = self.connector.parse_source_record(row_data, 2)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["article_id"], "405")
        self.assertEqual(parsed["title"], "JSON Column Test")
        self.assertEqual(parsed["source"], "API")

    def test_parse_empty_row_silently(self):
        """
        Verifies that completely empty rows (all fields are None, empty string or whitespace) 
        are parsed as None silently without logging warnings.
        """
        empty_row_1 = {
            "ID": "",
            "Title": "",
            "Summary": "   ",
            "Content": "",
            "Published_At": None,
            "Source": "",
            "Url": ""
        }
        parsed_1 = self.connector.parse_source_record(empty_row_1, 100)
        self.assertIsNone(parsed_1)

        empty_row_2 = {
            "id": None,
            "article_id": "",
            "title": None
        }
        parsed_2 = self.connector.parse_source_record(empty_row_2, 101)
        self.assertIsNone(parsed_2)

    def test_header_normalization_variations(self):
        """
        Verify that alphanumeric key normalization successfully matches variations in spacing, 
        casing, underscores, and hyphens (e.g. 'Article ID', 'article_id', 'article-id', 'ARTICLE ID').
        """
        variations = [
            {"Article ID": "1122", "title": "Test 1"},
            {"article_id": "1122", "title": "Test 2"},
            {"article-id": "1122", "title": "Test 3"},
            {"ARTICLE ID": "1122", "title": "Test 4"},
            {"ArticleID": "1122", "title": "Test 5"},
            {"UID": "1122", "title": "Test 6"},
            {"key": "1122", "title": "Test 7"},
        ]
        
        for idx, row in enumerate(variations):
            parsed = self.connector.extract_fields_from_dict(row, idx)
            self.assertIsNotNone(parsed, f"Failed parsing variation: {row}")
            self.assertEqual(parsed["article_id"], "1122")

    def test_field_fallback_when_empty(self):
        """
        Verifies that fields with empty/whitespace values successfully check subsequent 
        fallbacks instead of aborting on the first key that is present but empty.
        """
        row_data = {
            "ID": "777",
            "summary": "   ",  # present but empty/whitespace
            "description": "Actual description content",  # fallback should be checked and used
            "content": "",
            "body": "Actual body content"
        }
        parsed = self.connector.extract_fields_from_dict(row_data, 1)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["summary"], "Actual description content")
        self.assertEqual(parsed["content"], "Actual body content")


if __name__ == "__main__":
    unittest.main()
