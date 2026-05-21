import re
from typing import Dict, List, Set, Any

# Category Base Priorities
BASE_PRIORITY = {
    "political_parties": 50,
    "people": 40,
    "countries": 30,
    "states": 25,
    "cities": 20,
    "organizations": 10
}

# Contextual keywords for boosting
CONTEXT_KEYWORDS = {
    "political_parties": [
        "party", "alliance", "front", "coalition", "opposition", 
        "elections", "polls", "candidate", "voted", "seats"
    ],
    "people": [
        "said", "announced", "visited", "stated", "claimed", 
        "spoke", "criticized", "supported", "welcomed", "warned"
    ],
    "organizations": [
        "ministry", "department", "limited", "corp", "inc", "co", 
        "association", "commission", "agency", "board", "bank", 
        "company", "authority", "court", "forces", "union"
    ],
    "geography": [
        "in", "at", "from", "to", "visit", "travel to", "bordering", 
        "region", "port", "river", "strait", "gulf", "island", "city", 
        "town", "district", "province"
    ]
}

def resolve_category_conflicts(
    validated: dict, 
    normalizer=None, 
    title: str = "", 
    summary: str = "", 
    content: str = ""
) -> dict:
    """
    If the same entity exists in multiple categories (e.g. 'Trump' in people 
    and organizations, or 'Labour' in political_parties and organizations), 
    we resolve it based on category priorities:
    political_parties > people > geography (countries/states/cities) > organizations.
    
    It resolves the conflict by calculating a category confidence score:
    1. Base priority score.
    2. Dictionary match boost (+100) if entity exists in the category dictionary.
    3. Contextual word boost (+15) if nearby keywords or article text supports the category.
    """
    combined_text = f"{title}\n{summary}\n{content}".lower()
    
    # Build list of all categories to check
    categories = ["political_parties", "people", "countries", "states", "cities", "organizations"]
    
    # Identify all unique entity texts (lowercased) and which categories they currently appear in
    entity_to_categories = {} # entity_lower -> set of categories
    entity_to_original = {}   # entity_lower -> original cased name
    
    for category in categories:
        if category not in validated:
            continue
        for entity in validated[category]:
            entity_lower = entity.lower()
            if entity_lower not in entity_to_categories:
                entity_to_categories[entity_lower] = set()
            entity_to_categories[entity_lower].add(category)
            # Keep the longest original cased version (e.g. capitalized)
            existing = entity_to_original.get(entity_lower, "")
            if not existing or len(entity) > len(existing):
                entity_to_original[entity_lower] = entity
                
    # Now resolve each entity to exactly one category
    resolved = {cat: [] for cat in validated.keys()}
    if "topics" in validated:
        resolved["topics"] = list(validated["topics"])
        
    for entity_lower, cats in entity_to_categories.items():
        original_name = entity_to_original[entity_lower]
        if len(cats) == 1:
            # No conflict
            cat = list(cats)[0]
            resolved[cat].append(original_name)
            continue
            
        # Conflict exists! Resolve it using the scoring system.
        scores = {}
        for category in cats:
            # A. Base Priority Score
            score = BASE_PRIORITY.get(category, 0)
            
            # B. Dictionary Match Boost (+100)
            if normalizer:
                is_dict_match = False
                if category == "political_parties" and entity_lower in normalizer.parties_map:
                    is_dict_match = True
                elif category == "people" and entity_lower in normalizer.politicians_map:
                    is_dict_match = True
                elif category == "countries" and entity_lower in normalizer.countries_map:
                    is_dict_match = True
                elif category == "states" and entity_lower in normalizer.states_map:
                    is_dict_match = True
                elif category == "cities" and entity_lower in normalizer.cities_map:
                    is_dict_match = True
                elif category == "organizations" and (
                    entity_lower in normalizer.ministries_map or 
                    entity_lower in normalizer.abbreviations_map
                ):
                    is_dict_match = True
                    
                if is_dict_match:
                    score += 100
                    
            # C. Contextual Word Boost (+15)
            # Check for nearby keywords in combined text
            kws = CONTEXT_KEYWORDS.get(category, [])
            if not kws and category in ["countries", "states", "cities"]:
                kws = CONTEXT_KEYWORDS.get("geography", [])
                
            # Look for matches of any of the keywords in the text
            for kw in kws:
                if kw in combined_text:
                    score += 15
                    break
                    
            scores[category] = score
            
        # Select the category with the highest score
        best_cat = max(scores, key=scores.get)
        resolved[best_cat].append(original_name)
        
    # Re-sort lists
    for cat in resolved:
        if cat != "topics":
            resolved[cat] = sorted(list(set(resolved[cat])))
            
    return resolved
