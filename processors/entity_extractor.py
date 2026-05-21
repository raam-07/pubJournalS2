import re
import json
import spacy
import logging
from typing import Dict, List, Set, Any
from config import settings
from processors.normalizer import Normalizer

logger = logging.getLogger(__name__)

class EntityExtractor:
    def __init__(self, normalizer: Normalizer):
        self.normalizer = normalizer
        self.nlp = None
        self.load_spacy_model()
        
        # Load topics dictionary
        self.topics_dict: Dict[str, List[str]] = {}
        self.load_topics()
        
        # Compile dictionary matchers for direct matching (word-bounded)
        self.party_patterns: List[tuple] = []
        self.ministry_patterns: List[tuple] = []
        self.state_patterns: List[tuple] = []
        self.city_patterns: List[tuple] = []
        self.country_patterns: List[tuple] = []
        self.politician_patterns: List[tuple] = []
        self.abbreviation_patterns: List[tuple] = []
        self.compile_dictionary_patterns()

    def load_spacy_model(self):
        """
        Attempts to load the configured spaCy model.
        """
        try:
            self.nlp = spacy.load(settings.SPACY_MODEL)
            logger.info(f"Successfully loaded spaCy model: {settings.SPACY_MODEL}")
        except OSError:
            logger.error(
                f"spaCy model '{settings.SPACY_MODEL}' not found. "
                f"Please run 'python -m spacy download {settings.SPACY_MODEL}' before running the pipeline."
            )
            # Fail gracefully, but set nlp to None so we can mock or raise in execution
            raise

    def load_topics(self):
        """
        Loads the curated topics keywords for Step 1 mapping.
        """
        filepath = settings.DATA_DIR / "topics.json"
        if filepath.exists():
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    self.topics_dict = json.load(f)
                logger.info("Successfully loaded Step 1 topics keyword dictionary.")
            except Exception as e:
                logger.error(f"Error loading topics.json: {e}")

    def compile_dictionary_patterns(self):
        """
        Compiles word-bounded case-insensitive regex patterns for dictionary matching
        to ensure rapid and precise lookups.
        """
        configs = [
            (self.normalizer.parties_map, self.party_patterns),
            (self.normalizer.ministries_map, self.ministry_patterns),
            (self.normalizer.states_map, self.state_patterns),
            (self.normalizer.cities_map, self.city_patterns),
            (self.normalizer.countries_map, self.country_patterns),
            (self.normalizer.politicians_map, self.politician_patterns),
            (self.normalizer.abbreviations_map, self.abbreviation_patterns)
        ]
        
        for lookup_map, pattern_list in configs:
            # We want to match aliases. Group by canonical name to match aliases in descending length
            # to prevent shorter substrings from matching before longer aliases (e.g. "PM Modi" before "Modi")
            aliases_sorted = sorted(list(lookup_map.keys()), key=len, reverse=True)
            for alias in aliases_sorted:
                canonical = lookup_map[alias]
                # Avoid matching single-character symbols or extremely short strings in generic NER
                if len(alias) <= 1:
                    continue
                # Create word boundary regex
                # Use raw string boundaries and handle characters like & and ( )
                escaped = re.escape(alias)
                pattern = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
                pattern_list.append((pattern, canonical))

    def extract_topics(self, text: str) -> List[str]:
        """
        Performs extremely lightweight Step 1 dictionary-based topic extraction.
        Scans text for curated keyword matches and maps to canonical topics.
        """
        extracted = set()
        if not text:
            return []
            
        for topic, keywords in self.topics_dict.items():
            for keyword in keywords:
                escaped = re.escape(keyword)
                # Word-boundary check
                pattern = re.compile(rf"\b{escaped}s?\b", re.IGNORECASE)
                if pattern.search(text):
                    extracted.add(topic)
                    break # Topic matched, move to next topic
                    
        return sorted(list(extracted))

    def extract_entities(self, title: str, summary: str, content: str) -> Dict[str, List[str]]:
        """
        Extracts raw entities using spaCy NER, sorts GPE labels, augments using word-bounded
        custom dictionaries, and returns normalized and resolved categories.
        """
        combined_text = f"{title}\n{summary}\n{content}"
        
        raw_results = {
            "people": set(),
            "political_parties": set(),
            "countries": set(),
            "states": set(),
            "cities": set(),
            "organizations": set(),
            "topics": set()
        }
        
        # 1. spaCy NER Processing
        if self.nlp:
            doc = self.nlp(combined_text)
            for ent in doc.ents:
                text_val = ent.text.strip()
                if len(text_val) < 2:
                    continue
                
                # Check category mapping
                if ent.label_ == "PERSON":
                    normalized = self.normalizer.normalize_entity(text_val, "people")
                    if normalized:
                        raw_results["people"].add(normalized)
                        
                elif ent.label_ == "ORG":
                    # Determine if it matches political parties or ministries first
                    norm_party = self.normalizer.normalize_entity(text_val, "political_parties")
                    norm_org = self.normalizer.normalize_entity(text_val, "organizations")
                    
                    # If normalized maps to a party, sort it
                    if text_val.lower() in self.normalizer.parties_map or norm_party in self.normalizer.parties_map.values():
                        raw_results["political_parties"].add(norm_party)
                    elif text_val.lower() in self.normalizer.ministries_map or norm_org in self.normalizer.ministries_map.values():
                        raw_results["organizations"].add(norm_org)
                    else:
                        # Standard ORG
                        raw_results["organizations"].add(norm_org)
                        
                elif ent.label_ in ["GPE", "LOC"]:
                    # Determine correct category: country, state, or city
                    text_lower = text_val.lower()
                    
                    if text_lower in self.normalizer.countries_map:
                        norm = self.normalizer.normalize_entity(text_val, "countries")
                        raw_results["countries"].add(norm)
                    elif text_lower in self.normalizer.states_map:
                        norm = self.normalizer.normalize_entity(text_val, "states")
                        raw_results["states"].add(norm)
                    elif text_lower in self.normalizer.cities_map:
                        norm = self.normalizer.normalize_entity(text_val, "cities")
                        raw_results["cities"].add(norm)
                    else:
                        # Fallback heuristic: search maps
                        matched = False
                        for maps, cat in [
                            (self.normalizer.countries_map, "countries"),
                            (self.normalizer.states_map, "states"),
                            (self.normalizer.cities_map, "cities")
                        ]:
                            if text_lower in maps:
                                raw_results[cat].add(self.normalizer.normalize_entity(text_val, cat))
                                matched = True
                                break
                        if not matched:
                            # Default to country or organization if unknown region, 
                            # but let's keep it as countries or drop it if it's too noisy.
                            # Standard GPE normally maps to countries/locations. Let's map to countries.
                            raw_results["countries"].add(self.normalizer.normalize_entity(text_val, "countries"))

        # 2. Custom Dictionary Augmentation (Word-Bounded Regex Matching)
        # Helps extract critical political details that spaCy missed
        dictionaries_to_scan = [
            (self.party_patterns, "political_parties"),
            (self.ministry_patterns, "organizations"),
            (self.state_patterns, "states"),
            (self.city_patterns, "cities"),
            (self.country_patterns, "countries"),
            (self.politician_patterns, "people"),
            (self.abbreviation_patterns, "organizations") # e.g. Supreme Court, ECI -> organizations
        ]
        
        for patterns, category in dictionaries_to_scan:
            for pattern, canonical in patterns:
                if pattern.search(combined_text):
                    raw_results[category].add(canonical)

        # 3. Extract Topics
        topics = self.extract_topics(combined_text)
        raw_results["topics"] = set(topics)

        # Convert sets to sorted lists for finalization
        final_raw = {k: sorted(list(v)) for k, v in raw_results.items()}

        # 4. Apply Dynamic Contextual Resolution & Deduplication
        final_resolved = self.normalizer.resolve_article_context(final_raw, combined_text)

        return final_resolved
