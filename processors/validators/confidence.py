import re
from typing import List, Tuple

def count_occurrences(entity: str, text: str) -> int:
    """
    Case-insensitive word-bounded occurrence counter.
    """
    if not entity or not text:
        return 0
    escaped = re.escape(entity)
    try:
        return len(re.findall(rf"\b{escaped}\b", text, re.IGNORECASE))
    except re.error:
        return text.lower().count(entity.lower())

def check_casing_quality(text: str) -> float:
    """
    Evaluates casing quality. Clamped to a maximum penalty of -0.05 
    to preserve recall for OCR, RSS, and foreign names.
    """
    # 1. Abbreviations in all-caps (e.g. BJP, INC, PM, CM) are perfect
    if text.isupper() and len(text) <= 5:
        return 0.0
        
    # 2. All-lowercase proper noun extractions get a tiny penalty
    if text.islower():
        return -0.05
        
    # 3. Proper noun casing: major tokens must start with an uppercase letter
    words = [w for w in text.split() if w.lower() not in {"of", "and", "the", "in", "on", "for", "to", "by", "de"}]
    if not words:
        return -0.05
        
    capitalized_words = [w for w in words if w and w[0].isupper()]
    ratio = len(capitalized_words) / len(words)
    if ratio < 0.8:
        return -0.05
        
    return 0.0

def calculate_confidence(
    entity: str, 
    category: str, 
    title: str, 
    summary: str, 
    content: str, 
    normalizer
) -> Tuple[float, List[str], bool]:
    """
    Calculates and returns confidence score between 0.0 and 1.0, scoring reasons, 
    and whether a dictionary match occurred.
    """
    reasons = []
    text_lower = entity.lower()
    
    # 1. Check Dictionary Matches first (always high confidence 1.0)
    is_dict_match = False
    if category == "people" and text_lower in normalizer.politicians_map:
        is_dict_match = True
    elif category == "political_parties" and text_lower in normalizer.parties_map:
        is_dict_match = True
    elif category == "organizations" and (text_lower in normalizer.ministries_map or text_lower in normalizer.abbreviations_map):
        is_dict_match = True
    elif category == "states" and text_lower in normalizer.states_map:
        is_dict_match = True
    elif category == "cities" and text_lower in normalizer.cities_map:
        is_dict_match = True
    elif category == "countries" and text_lower in normalizer.countries_map:
        is_dict_match = True
        
    if is_dict_match:
        score = 1.0
        reasons.append("dictionary_match")
        return score, reasons, True

    # 2. Establish Base Score for non-dictionary spaCy extractions
    if " " in entity:
        score = 0.5
        reasons.append("spacy_ner_multi_word")
    else:
        score = 0.3
        reasons.append("spacy_ner_single_word")

    # 3. Cross-Validation: Title Presence Boost
    in_title = count_occurrences(entity, title) > 0
    if in_title:
        score += 0.3
        reasons.append("present_in_title")

    # 4. Article-wide Frequency Analysis
    combined_text = f"{title}\n{summary}\n{content}"
    occurrences = count_occurrences(entity, combined_text)
    if occurrences == 1:
        score -= 0.15
        reasons.append("appears_only_once")
    elif occurrences == 2:
        score += 0.05
        reasons.append("appears_twice")
    elif occurrences >= 3:
        score += 0.2
        reasons.append(f"appears_multiple_times_{occurrences}")

    # 5. Proper Noun Casing Analysis
    casing_penalty = check_casing_quality(entity)
    if casing_penalty < 0:
        score += casing_penalty
        reasons.append(f"poor_casing_penalty_{casing_penalty}")

    # Clamp score between 0.0 and 1.0
    final_score = max(0.0, min(1.0, round(score, 2)))
    return final_score, reasons, False
