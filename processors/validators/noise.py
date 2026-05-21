import re
from typing import Tuple

# BLACKLIST of generic administrative terms for organizations/people
GENERIC_ADMINISTRATIVE_WORDS = {
    "cabinet", "state", "government", "prime minister", "president", 
    "parliament", "administration", "ministry", "department", "court", 
    "council", "assembly", "opposition", "coalition", "union", "center", 
    "centre", "police", "army", "military", "navy", "air force", "governor", 
    "mayor", "senator", "congressman", "spacy", "state government", "central government"
}

# Standalone source names to filter out from entities lists
NEWS_SOURCES_BLACKLIST = {
    "times of india", "toi", "bbc", "guardian", "al jazeera", "reuters", "pti", "ap"
}

def clean_entity_text(text: str) -> str:
    """
    Applies possessive and boundary cleaners to prune trailing/leading noise.
    e.g., "Trump's" -> "Trump", "Khamanei’s" -> "Khamanei"
    """
    if not text:
        return ""
    cleaned = text.strip()
    # Strip trailing possessives ('s or curly ’s)
    cleaned = re.sub(r"['’]s$", "", cleaned, flags=re.IGNORECASE)
    # Strip trailing possessive apostrophe (s' or curly s’)
    cleaned = re.sub(r"s['’]$", "s", cleaned, flags=re.IGNORECASE)
    # Strip starting/ending lonely quotes or dots
    cleaned = cleaned.strip("'\"`’‘. ")
    return cleaned

def is_noise(text: str) -> Tuple[bool, str]:
    """
    Aggressive regex-based noise detection.
    Returns (is_noise, reason).
    """
    if not text or len(text) < 2:
        return True, "Extremely short"
        
    # 1. Reject numeric and pure symbolic entities
    if text.isdigit() or re.match(r"^[\d\s.,\-+=$%]+$", text):
        return True, "Numeric/Symbolic"

    # 2. Reject mixed alphanumeric garbage (e.g., COVID19, G20 - unless dictionary matches)
    if re.search(r"\d", text) and re.search(r"[a-zA-Z]", text):
        return True, "Mixed alphanumeric garbage"

    # 3. Reject symbols indicative of broken tokenization or web URLs/emails
    if re.search(r"[#@*$<>\/\\_|~^{}\[\]+=]", text):
        return True, "Contains invalid symbols"

    # 4. Reject obvious OCR corruption: 3 or more identical characters in a row
    if re.search(r"(.)\1\1", text, re.IGNORECASE):
        return True, "Repeated characters"

    # 5. Reject malformed boundaries (unmatched brackets/quotes)
    if (text.count("(") != text.count(")")) or (text.count("[") != text.count("]")):
        return True, "Malformed boundaries/brackets"

    # 6. Reject ending with 'ss' representing casing noise/typos (e.g., Donald Trumpss, Khamaneiss)
    # unless it is a legitimate English word like Congress, press, business
    text_lower = text.lower()
    if text_lower.endswith("ss") and text_lower not in {"congress", "press", "business", "progress", "princess", "boss", "mass"}:
        return True, "Excessive casing noise (ss suffix)"

    # 7. Reject generic administrative words
    if text_lower in GENERIC_ADMINISTRATIVE_WORDS:
        return True, "Generic administrative word"

    # 8. Reject news source names
    if text_lower in NEWS_SOURCES_BLACKLIST:
        return True, "News source name"

    return False, ""
