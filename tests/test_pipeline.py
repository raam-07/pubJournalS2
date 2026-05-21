import sys
import unittest
from pathlib import Path

# Add project root to sys.path so we can import config, utils, processors
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from processors.normalizer import Normalizer
from processors.entity_extractor import EntityExtractor
from processors.validators import EntityValidator
from utils.helpers import format_entity_name, google_api_retry, strip_title_source
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
        and metadata-only rows (having a date or source but missing ID and text content)
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

        # Metadata-only row (has source and date, but missing ID and article content)
        metadata_only_row = {
            "id": "",
            "title": "",
            "summary": "   ",
            "content": "",
            "published_at": "2026-05-22T02:00:00Z",
            "source": "RSS Feed",
            "url": ""
        }
        parsed_3 = self.connector.parse_source_record(metadata_only_row, 102)
        self.assertIsNone(parsed_3)

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


class TestEntityValidator(unittest.TestCase):
    def setUp(self):
        self.normalizer = Normalizer()
        self.validator = EntityValidator(self.normalizer)
        self.validator.min_confidence = 0.5

    def test_clean_entity_text(self):
        """
        Verify that trailing possessive 's and curly ’s are cleaned.
        """
        self.assertEqual(self.validator.clean_entity_text("Trump's"), "Trump")
        self.assertEqual(self.validator.clean_entity_text("Khamanei’s"), "Khamanei")
        self.assertEqual(self.validator.clean_entity_text("'Modi'"), "Modi")
        self.assertEqual(self.validator.clean_entity_text("Stalin’s"), "Stalin")
        self.assertEqual(self.validator.clean_entity_text("Congress’"), "Congress")

    def test_noise_filtering(self):
        """
        Ensure digits, symbols, repeated OCR characters, malformed boundaries, and ending ss are caught.
        """
        # Excessive casing/typo ends in "ss"
        is_noise, _ = self.validator.is_noise("Donald Trumpss")
        self.assertTrue(is_noise)
        is_noise, _ = self.validator.is_noise("South Koreass")
        self.assertTrue(is_noise)
        
        # Valid ss words
        is_noise, _ = self.validator.is_noise("Congress")
        self.assertFalse(is_noise)
        is_noise, _ = self.validator.is_noise("business")
        self.assertFalse(is_noise)
        
        # Repeated OCR characters
        is_noise, _ = self.validator.is_noise("Trumppp")
        self.assertTrue(is_noise)
        
        # Symbols
        is_noise, _ = self.validator.is_noise("Modi#1")
        self.assertTrue(is_noise)
        is_noise, _ = self.validator.is_noise("Amit_Shah")
        self.assertTrue(is_noise)
        
        # Digits/Numeric
        is_noise, _ = self.validator.is_noise("2026")
        self.assertTrue(is_noise)
        is_noise, _ = self.validator.is_noise("G20")
        self.assertTrue(is_noise)

    def test_casing_quality_penalty(self):
        """
        Test that lowercase or chaotic casing gets clamped to a safe penalty of -0.05,
        preserving recall for RSS feeds and foreign names.
        """
        self.assertEqual(self.validator.check_casing_quality("delhi"), -0.05) # lowercase clamped
        self.assertEqual(self.validator.check_casing_quality("Donald Trump"), 0.0) # good casing
        self.assertEqual(self.validator.check_casing_quality("donald Trump"), -0.05) # first word lowercase clamped

    def test_strict_geography_and_party(self):
        """
        Ensure that only valid cities, states, countries, and parties are accepted.
        """
        entities = {
            "political_parties": ["bjp", "Nonexistent Party"],
            "countries": ["us", "Atlantis"],
            "states": ["up", "Fake State"],
            "cities": ["Bangalore", "Paris"],
            "people": ["Donald Trump"],
            "organizations": ["Ministry of External Affairs"]
        }
        
        validated, rejected = self.validator.validate_entities(
            entities, 
            title="Meeting about BJP in UP", 
            summary="US and Bangalore details discussed with Donald Trump", 
            content="Full content repeats Donald Trump three times to ensure score is high. Donald Trump. Donald Trump.", 
            source="TOI"
        )
        
        # Geopolitical validation strictness checks
        self.assertIn("Bharatiya Janata Party", validated["political_parties"])
        self.assertNotIn("Nonexistent Party", validated["political_parties"])
        
        self.assertIn("United States", validated["countries"])
        self.assertNotIn("Atlantis", validated["countries"])
        
        self.assertIn("Uttar Pradesh", validated["states"])
        self.assertNotIn("Fake State", validated["states"])
        
        self.assertIn("Bengaluru", validated["cities"])
        self.assertNotIn("Paris", validated["cities"])
        
        # Check debug tracking works
        self.assertTrue(any(rec["entity"] == "Nonexistent Party" for rec in rejected["political_parties"]))
        self.assertTrue(any(rec["entity"] == "Atlantis" for rec in rejected["countries"]))
        self.assertTrue(any(rec["entity"] == "Paris" for rec in rejected["cities"]))

    def test_category_blacklists(self):
        """
        Test that generic administrative nouns or source names are excluded.
        """
        entities = {
            "organizations": ["Cabinet", "Government", "Times of India", "Ministry of Home Affairs"],
            "people": ["Prime Minister", "Narendra Modi"]
        }
        
        validated, rejected = self.validator.validate_entities(
            entities, 
            title="Narendra Modi Cabinet Government meeting", 
            summary="Ministry of Home Affairs meeting details from Times of India", 
            content="Narendra Modi, Prime Minister, met Home Ministry leaders.", 
            source="TOI"
        )
        
        self.assertNotIn("Cabinet", validated["organizations"])
        self.assertNotIn("Government", validated["organizations"])
        self.assertNotIn("Times of India", validated["organizations"])
        self.assertIn("Ministry of Home Affairs", validated["organizations"])
        
        self.assertNotIn("Prime Minister", validated["people"])
        self.assertIn("Narendra Modi", validated["people"])

    def test_fuzzy_deduplication_merging(self):
        """
        Test that short and long name variants are resolved and deduplicated.
        """
        names = ["Donald Trump", "Trump", "M. K. Stalin", "Stalin", "Rahul Gandhi", "Rahul"]
        merged = self.validator.merge_fuzzy_duplicates(names)
        
        self.assertIn("Donald Trump", merged)
        self.assertNotIn("Trump", merged)
        self.assertIn("M. K. Stalin", merged)
        self.assertNotIn("Stalin", merged)
        self.assertIn("Rahul Gandhi", merged)
        self.assertNotIn("Rahul", merged)

    def test_confidence_scoring_math(self):
        """
        Verifies mathematical confidence scoring base, boosts, penalties, and thresholds.
        """
        title = "Narendra Modi meets Donald Trump"
        summary = "Bilateral talks between India and US."
        content = "Donald Trump is mentioned again here to raise frequency."
        
        # 1. Dictionary exact match (Narendra Modi) must be 1.0 confidence
        score_modi, _ = self.validator.calculate_confidence("Narendra Modi", "people", title, summary, content)
        self.assertEqual(score_modi, 1.0)
        
        # 2. Multi-word spaCy entity present in title and content (Donald Trump)
        # Base (0.5) + Title Boost (0.3) + Repetition 2x (0.05) = 0.85
        score_trump, reasons = self.validator.calculate_confidence("Donald Trump", "people", title, summary, content)
        self.assertEqual(score_trump, 0.85)
        
        # 3. Single-word spaCy entity that appears only once in content
        # Base (0.3) + Single Occurrence Penalty (-0.15) = 0.15
        score_single, reasons_single = self.validator.calculate_confidence("Randomguy", "people", title, summary, content)
        self.assertEqual(score_single, 0.15)


class TestEntityValidatorPackage(unittest.TestCase):
    def setUp(self):
        self.normalizer = Normalizer()
        self.validator = EntityValidator(self.normalizer)
        self.validator.min_confidence = 0.5

    def test_aggressive_title_stripping(self):
        """
        Test that publisher suffixes and updates prefixes are aggressively cleaned from titles.
        """
        self.assertEqual(strip_title_source("Donald Trump meets PM Modi | The Guardian"), "Donald Trump meets PM Modi")
        self.assertEqual(strip_title_source("LIVE: India elections updates - The Times of India"), "India elections updates")
        self.assertEqual(strip_title_source("Breaking News: Strait of Hormuz conflict | BBC"), "Strait of Hormuz conflict")
        self.assertEqual(strip_title_source("Crisis in West Bank - DAWN.COM"), "Crisis in West Bank")

    def test_soft_geography_recall_allowance(self):
        """
        Verify that unregistered geographical entities (like Strait of Hormuz, West Bank, Rafah, Gaza Strip)
        successfully bypass dictionary filters and survive when meeting soft heuristics.
        """
        entities = {
            "countries": ["Strait of Hormuz", "Gaza Strip"],
            "cities": ["Rafah", "Unregistered Place"]
        }
        
        title = "Tension rises in Strait of Hormuz and Gaza Strip"
        summary = "Reports from the border at Rafah suggest troop deployments."
        content = "The Strait of Hormuz remains heavily guarded. Gaza Strip is tense. Rafah border is closed."
        
        validated, rejected = self.validator.validate_entities(
            entities, title, summary, content, source="News"
        )
        
        # Should survive because of title presence, multi-word, multiple occurrences, and geo context keywords
        self.assertIn("Strait of Hormuz", validated["countries"])
        self.assertIn("Gaza Strip", validated["countries"])
        self.assertIn("Rafah", validated["cities"])
        
        # Should be filtered out because it has zero occurrences, not in title, single occurrences, no geo context
        self.assertNotIn("Unregistered Place", validated["cities"])

    def test_entity_priority_conflict_resolution(self):
        """
        Ensure category classification priority conflicts are resolved correctly:
        political_parties > people > countries/cities > organizations
        based on dictionary match and contextual keywords.
        """
        entities = {
            "people": ["Trump", "Labour"],
            "political_parties": ["Labour"],
            "organizations": ["Trump", "BBC", "NDA"],
            "countries": ["NDA"]
        }
        
        # Article context: political/elections campaign
        title = "Labour Party leads campaign against NDA coalition"
        summary = "Trump met with BBC representatives in Washington."
        content = "Trump discussed the upcoming elections. Labour announced its candidates. NDA front is prepared."
        
        validated, rejected = self.validator.validate_entities(
            entities, title, summary, content, source="BBC"
        )
        
        # "Labour" exists in political_parties map (Labor Party) -> political_parties
        self.assertIn("Labour Party", validated["political_parties"])
        self.assertNotIn("Labour", validated["people"])
        self.assertNotIn("Labour", validated["organizations"])
        
        # "Trump" exists in politicians_map (Donald Trump) -> people
        self.assertIn("Donald Trump", validated["people"])
        self.assertNotIn("Trump", validated["organizations"])
        
        # "BBC" -> organization (default priority organization + contextual keywords)
        self.assertIn("BBC", validated["organizations"])
        
        # "NDA" -> political party (National Democratic Alliance in dict) -> political_parties
        self.assertIn("National Democratic Alliance", validated["political_parties"])
        self.assertNotIn("NDA", validated["countries"])
        self.assertNotIn("NDA", validated["organizations"])

    def test_article_level_context_classifier(self):
        """
        Verify that article topic context detects 'Politics' and successfully triggers
        contextual resolutions like mapping generic 'Congress' to 'Indian National Congress'.
        """
        # Scenario A: Politics Context
        entities_a = {
            "organizations": ["Congress"],
            "topics": []
        }
        title_a = "Congress announces candidate list for upcoming assembly elections"
        summary_a = "PM Modi slams Congress during campaigning."
        content_a = "The Congress party will contest all seats. BJP is preparing for polls."
        
        validated_a, _ = self.validator.validate_entities(
            entities_a, title_a, summary_a, content_a, source="News"
        )
        
        # Should be resolved to Indian National Congress under politics context
        self.assertIn("Indian National Congress", validated_a["political_parties"])
        self.assertNotIn("Congress", validated_a["organizations"])
        self.assertIn("Politics", validated_a["topics"])
        self.assertIn("Elections", validated_a["topics"])

        # Scenario B: Finance Context (without politics keywords)
        entities_b = {
            "organizations": ["Congress"],
            "topics": []
        }
        title_b = "US Congress discusses corporate budget, market revenue, and tax inflation"
        summary_b = "The financial audit of corporate profits was presented."
        content_b = "Congress passed the budget to stabilize gdp and control inflation rates."
        
        validated_b, _ = self.validator.validate_entities(
            entities_b, title_b, summary_b, content_b, source="News"
        )
        
        # Should remain a standard organization "Congress" under finance context
        self.assertIn("Congress", validated_b["organizations"])
        self.assertNotIn("Indian National Congress", validated_b["political_parties"])
        self.assertIn("Finance", validated_b["topics"])


if __name__ == "__main__":
    unittest.main()
