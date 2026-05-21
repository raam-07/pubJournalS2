import re
from utils.helpers import format_entity_name

GEOGRAPHIC_KEYWORDS = {
    "strait", "gulf", "bank", "island", "strip", "port", "river", 
    "valley", "mount", "lake", "sea", "ocean", "bay", "region", 
    "district", "province", "village", "town", "border", "zone", 
    "pass", "highway", "road", "canal", "peninsula", "channel",
    "delta", "coast", "cape", "desert", "forest", "mountain", "hill"
}

def validate_geography(
    entity: str, 
    category: str, 
    normalizer, 
    confidence_score: float, 
    min_confidence: float,
    title: str = "",
    summary: str = "",
    content: str = "",
    reasons: list = None
) -> tuple:
    """
    Soft geographical validation checker.
    IF exists in dataset:
        Returns (True, canonical_name, 'dictionary_match')
    ELSE:
        Allows GPE/LOC to survive if:
            1. confidence_score >= min_confidence
            AND
            2. Meets soft recall criteria:
               - appears multiple times OR
               - appears in title OR
               - extracted by strong NER OR
               - context supports geography
    """
    text_lower = entity.lower()
    if reasons is None:
        reasons = []
        
    # 1. Select target dictionary map
    target_map = None
    if category == "countries":
        target_map = normalizer.countries_map
    elif category == "states":
        target_map = normalizer.states_map
    elif category == "cities":
        target_map = normalizer.cities_map

    # 2. Strict lookup check first
    if target_map and text_lower in target_map:
        return True, target_map[text_lower], "dictionary_match"
        
    # 3. Soft fallback check: if confidence is at least minimum, check soft recall criteria
    if confidence_score >= min_confidence:
        combined_text = f"{title}\n{summary}\n{content}".lower()
        
        # A. Appears multiple times
        escaped = re.escape(text_lower)
        occurrences = len(re.findall(rf"\b{escaped}\b", combined_text))
        if occurrences == 0:
            occurrences = combined_text.count(text_lower)
        appears_multiple = occurrences >= 2
        
        # B. Appears in title
        appears_in_title = text_lower in title.lower()
        
        # C. Extracted by strong NER (multi-word, or explicitly set in reasons)
        extracted_by_strong_ner = "spacy_ner_multi_word" in reasons or " " in entity
        
        # D. Context supports geography
        # Check if entity name contains any geographic keyword
        has_geo_keyword = any(kw in text_lower for kw in GEOGRAPHIC_KEYWORDS)
        
        # Check if surrounded by geographical prepositions in the text
        # e.g., "in Strait of Hormuz", "at Rafah", "from Gaza Strip"
        preposition_patterns = [
            rf"\b(?:in|at|from|to|near|off|across|into|through|bordering|inside|outside|around)\s+{escaped}\b",
            rf"\b{escaped}\s+(?:border|region|port|coast|valley|river|strait|gulf|island|city|town|district|province)\b"
        ]
        has_geo_prepositions = False
        for pattern in preposition_patterns:
            if re.search(pattern, combined_text):
                has_geo_prepositions = True
                break
                
        context_supports = has_geo_keyword or has_geo_prepositions
        
        if appears_multiple or appears_in_title or extracted_by_strong_ner or context_supports:
            formatted = format_entity_name(entity)
            return True, formatted, "recall_allowance"
            
    return False, "", "low_confidence_no_dictionary_match"
