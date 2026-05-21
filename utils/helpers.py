import re
import time
import random
import logging
from functools import wraps
from gspread.exceptions import APIError

logger = logging.getLogger(__name__)

# List of abbreviations that must remain uppercase during normalizations
UPPERCASE_ABBREVIATIONS = {
    "BJP", "INC", "AAP", "CM", "PM", "MEA", "MHA", "MP", "MLA", "DMK", "AIADMK", "TMC", 
    "BSP", "SP", "NCP", "CPI", "CPIM", "JD", "JDU", "JDS", "RJD", "LJP", "SAD", "SS", 
    "TRS", "YSRCP", "TDP", "BJD", "TRS", "BRS", "NDA", "UPA", "UP", "MP", "HP", "AP", "JK"
}

def clean_text(text: str) -> str:
    """
    Cleans raw text of surrounding whitespace, double spaces, and standardizes punctuation.
    """
    if not text:
        return ""
    # Standardize whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove smart quotes
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return text.strip()

def preserve_abbreviation_casing(word: str) -> str:
    """
    Standardizes casing but preserves known political abbreviations in uppercase.
    """
    upper_word = word.upper().replace(".", "")
    if upper_word in UPPERCASE_ABBREVIATIONS:
        return upper_word
    # Fallback to standard capitalization if not in abbreviations
    return word.capitalize()

def format_entity_name(name: str) -> str:
    """
    Cleans and standardizes casing for entity names while preserving abbreviations.
    Example: "pm modi" -> "PM Modi", "bjp leader" -> "BJP Leader"
    """
    cleaned = clean_text(name)
    if not cleaned:
        return ""
    
    words = cleaned.split(" ")
    formatted_words = []
    for word in words:
        # Standardize words that have trailing dots or punctuation
        core_word = re.sub(r"[^\w\.]", "", word)
        punctuation = word[len(core_word):]
        prefix_punctuation = word[:word.find(core_word)] if core_word in word else ""
        
        if core_word:
            formatted_word = preserve_abbreviation_casing(core_word)
            formatted_words.append(f"{prefix_punctuation}{formatted_word}{punctuation}")
        else:
            formatted_words.append(word)
            
    return " ".join(formatted_words)

def google_api_retry(max_retries: int = 5, initial_delay: float = 1.0, backoff_factor: float = 2.0):
    """
    Decorator that catches Google Sheets API 429 rate limit exceptions and retries
    with exponential backoff and random jitter.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except APIError as e:
                    last_exception = e
                    status_code = e.response.status_code if hasattr(e.response, 'status_code') else None
                    
                    # 429 is the rate limit error code
                    if status_code == 429 or "RESOURCE_EXHAUSTED" in str(e):
                        # Jittered delay to prevent stampeding Herd problem
                        jitter = random.uniform(0, 0.5 * delay)
                        sleep_time = delay + jitter
                        
                        logger.warning(
                            f"Google API rate limit hit (429) during '{func.__name__}'. "
                            f"Retrying in {sleep_time:.2f}s (Attempt {attempt}/{max_retries})..."
                        )
                        time.sleep(sleep_time)
                        delay *= backoff_factor
                    else:
                        # Reraise other non-rate-limit APIErrors immediately
                        logger.error(f"Google Sheets APIError in '{func.__name__}': {e}")
                        raise e
                except Exception as e:
                    # Reraise any other unexpected exceptions immediately
                    logger.error(f"Unexpected error in '{func.__name__}': {e}")
                    raise e
            
            logger.error(f"Max retries ({max_retries}) exceeded for '{func.__name__}' due to API rate limits.")
            raise last_exception
            
        return wrapper
    return decorator

def strip_title_source(title: str) -> str:
    """
    Cleans titles aggressively by stripping publisher suffixes, category suffixes, 
    RSS markers, and live update tags to prevent NER poisoning.
    """
    if not title:
        return ""
        
    cleaned = title.strip()
    
    # 1. Remove prefixes like "LIVE:", "LIVE Updates:", "Breaking:"
    prefixes_to_strip = [
        r"^live\s*updates?:?\s*",
        r"^live\s*blog?:?\s*",
        r"^breaking\s*(news)?:?\s*",
        r"^live\s*:\s*",
        r"^updates\s*:\s*",
        r"^exclusive\s*:\s*"
    ]
    for pattern in prefixes_to_strip:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        
    # 2. Clean tail publisher metadata suffixes
    # Matches a separator ( - or | or • or : ) followed by typical news site words or domain extensions
    tail_regexes = [
        # Match vertical bar or hyphen followed by standard publisher terms
        r"\s+[-|•:]\s+.*(?:hindu|guardian|bbc|dawn|toi|times|reuters|al\s*jazeera|independent|financial\s*times|bloomberg|ap|afp|pti|news|report|live|updates|com|org|net|co\.uk).*$",
        # Match standard brackets ending with news source
        r"\s*\([^)]*(?:hindu|guardian|bbc|toi|times|reuters|al\s*jazeera|news|ap|afp|pti)[^)]*\)$",
        # Generic vertical bar tail strip (vertical bars are almost exclusively used for source branding)
        r"\s+\|\s+[^|]+$",
        # Generic hyphen tail strip if it contains domain extensions
        r"\s+-\s+[\w\d.-]+\.(?:com|org|net|in|co|gov|edu|info|io)(?:/.*)?$"
    ]
    
    for pattern in tail_regexes:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        
    return cleaned.strip()
