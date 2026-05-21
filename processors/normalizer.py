import re
import json
import logging
from typing import Dict, List, Set, Any
from config import settings
from utils.helpers import clean_text, format_entity_name

logger = logging.getLogger(__name__)

# Regex to strip common titles and honorifics (case-insensitive)
TITLE_STRIP_RE = re.compile(
    r"^(?:pm|cm|dr|mr|mrs|ms|shri|smt|sardar|minister|president|governor|chief\s+minister|prime\s+minister|union\s+minister|mp|mla|ji)\.?\s+",
    re.IGNORECASE
)

class Normalizer:
    def __init__(self):
        self.politicians_map: Dict[str, str] = {}
        self.parties_map: Dict[str, str] = {}
        self.ministries_map: Dict[str, str] = {}
        self.states_map: Dict[str, str] = {}
        self.cities_map: Dict[str, str] = {}
        self.countries_map: Dict[str, str] = {}
        self.abbreviations_map: Dict[str, str] = {}
        
        self.load_dictionaries()

    def load_dictionaries(self):
        """
        Loads all compiled JSON dictionaries from the data directory and 
        builds reverse lookup maps from alias to canonical name.
        """
        dict_files = {
            "politicians.json": self.politicians_map,
            "parties.json": self.parties_map,
            "ministries.json": self.ministries_map,
            "states.json": self.states_map,
            "cities.json": self.cities_map,
            "countries.json": self.countries_map,
            "abbreviations.json": self.abbreviations_map
        }
        
        for filename, target_map in dict_files.items():
            filepath = settings.DATA_DIR / filename
            if not filepath.exists():
                logger.warning(f"Dictionary file {filename} does not exist at {filepath}. Skipping.")
                continue
            
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for canonical, aliases in data.items():
                        # Set canonical itself in the map
                        target_map[canonical.lower()] = canonical
                        # Map all aliases to canonical
                        for alias in aliases:
                            target_map[alias.lower()] = canonical
                logger.info(f"Successfully loaded and compiled {filename} mapping.")
            except Exception as e:
                logger.error(f"Error reading dictionary {filename}: {e}")

    def strip_titles(self, name: str) -> str:
        """
        Recursively strips pre-nominal titles and honorifics.
        Example: "PM Narendra Modi" -> "Narendra Modi"
        """
        prev_name = ""
        cleaned = clean_text(name)
        
        # Keep stripping as long as a prefix match is found
        while cleaned != prev_name:
            prev_name = cleaned
            cleaned = TITLE_STRIP_RE.sub("", cleaned)
            
        # Strip trailing "ji" which is common in Indian English
        if cleaned.lower().endswith(" ji"):
            cleaned = cleaned[:-3].strip()
            
        return cleaned

    def normalize_entity(self, name: str, category: str) -> str:
        """
        Normalizes a single entity string against standard dictionaries for a specific category.
        """
        stripped = self.strip_titles(name)
        if not stripped:
            return ""
            
        stripped_lower = stripped.lower()
        
        # Select target dictionary based on category
        target_map = None
        if category == "people":
            target_map = self.politicians_map
        elif category == "political_parties":
            target_map = self.parties_map
        elif category == "organizations":
            # Map organizations to ministries or generic abbreviations
            target_map = self.ministries_map
        elif category == "states":
            target_map = self.states_map
        elif category == "cities":
            target_map = self.cities_map
        elif category == "countries":
            target_map = self.countries_map
            
        # 1. Attempt exact/alias match in category dictionary
        if target_map and stripped_lower in target_map:
            return target_map[stripped_lower]
            
        # 2. Cross-category check if not found (e.g., in case NER misclassified)
        for maps in [self.politicians_map, self.parties_map, self.ministries_map, 
                     self.states_map, self.cities_map, self.countries_map]:
            if stripped_lower in maps:
                return maps[stripped_lower]
                
        # 3. If no dictionary match, clean the casing and return it
        return format_entity_name(stripped)

    def resolve_article_context(self, entities: Dict[str, List[str]], raw_text: str) -> Dict[str, List[str]]:
        """
        Applies dynamic contextual resolution within a single article.
        Specifically for people: resolves partial names (e.g. "Modi") to full anchor names 
        (e.g. "Narendra Modi") if the full anchor name is present in the list of extracted entities.
        """
        resolved_entities = {k: list(v) for k, v in entities.items()}
        people = resolved_entities.get("people", [])
        if not people:
            return resolved_entities
            
        # 1. Find all anchor names (people whose normalized names contain at least one space)
        anchors = [p for p in people if " " in p]
        
        # 2. Iterate and resolve shorter partial names
        resolved_people = set()
        for person in people:
            # If it's already an anchor, keep it
            if person in anchors:
                resolved_people.add(person)
                continue
                
            # If it's a short name, check if it matches any anchor in the same article
            person_lower = person.lower()
            candidate_anchor = None
            matches_count = 0
            
            # Check if this short name is a known alias of an anchor in the article
            for anchor in anchors:
                anchor_lower = anchor.lower()
                
                # Check 1: Is it a direct word match in the anchor (e.g. "Modi" in "Narendra Modi")
                words_in_anchor = anchor_lower.split(" ")
                
                # Check 2: Check global politician dict aliases for this anchor to see if short name matches
                global_aliases = []
                # Find canonical key in politicians_map
                canonical_name = self.politicians_map.get(anchor_lower)
                if canonical_name:
                    # Collect all aliases for this politician
                    global_aliases = [
                        k for k, v in self.politicians_map.items() 
                        if v == canonical_name
                    ]
                
                if person_lower in words_in_anchor or person_lower in global_aliases:
                    candidate_anchor = anchor
                    matches_count += 1
            
            # If exactly one anchor is found, resolve to it!
            if matches_count == 1 and candidate_anchor:
                logger.debug(f"Contextual Resolution: '{person}' resolved to '{candidate_anchor}'")
                resolved_people.add(candidate_anchor)
            else:
                # If there are 0 or multiple matches (e.g. "Gandhi" when both "Rahul Gandhi" 
                # and "Sonia Gandhi" are in the article), do not resolve. 
                # Let's see if we can resolve it using global politicians map
                global_canonical = self.politicians_map.get(person_lower)
                if global_canonical:
                    # Ensure it's not a generic ambiguous word
                    # Ambiguous check: if the canonical name itself contains this word, 
                    # but check if it's generally safe (e.g. "Kejriwal" -> "Arvind Kejriwal")
                    if person_lower in ["gandhi", "modi", "shah"]:
                        # Too generic without context, keep it as formatted
                        resolved_people.add(format_entity_name(person))
                    else:
                        resolved_people.add(global_canonical)
                else:
                    resolved_people.add(format_entity_name(person))
                    
        # 3. Sort and deduplicate cleanly
        resolved_entities["people"] = sorted(list(resolved_people))
        
        # Sort and deduplicate all other categories as well
        for cat in resolved_entities:
            if cat != "people":
                resolved_entities[cat] = sorted(list(set(resolved_entities[cat])))
                
        return resolved_entities
