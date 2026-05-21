import logging
from typing import Dict, List, Any, Tuple
from config import settings

from processors.validators.noise import clean_entity_text, is_noise
from processors.validators.confidence import calculate_confidence, check_casing_quality
from processors.validators.geography import validate_geography
from processors.validators.dedupe import merge_fuzzy_duplicates
from processors.validators.conflicts import resolve_category_conflicts
from processors.validators.contextual import resolve_contextual_entities

logger = logging.getLogger(__name__)

class EntityValidator:
    def __init__(self, normalizer):
        self.normalizer = normalizer
        # Fetch configurations
        self.debug = getattr(settings, "DEBUG", False)
        self.min_confidence = getattr(settings, "MIN_CONFIDENCE_THRESHOLD", 0.5)

    def clean_entity_text(self, text: str) -> str:
        """Wrapper for backwards compatibility in tests."""
        return clean_entity_text(text)
        
    def is_noise(self, text: str) -> Tuple[bool, str]:
        """Wrapper for backwards compatibility in tests."""
        return is_noise(text)
        
    def check_casing_quality(self, text: str) -> float:
        """Wrapper for backwards compatibility in tests."""
        return check_casing_quality(text)
        
    def merge_fuzzy_duplicates(self, names: List[str]) -> List[str]:
        """Wrapper for backwards compatibility in tests."""
        return merge_fuzzy_duplicates(names)
        
    def calculate_confidence(self, entity: str, category: str, title: str, summary: str, content: str) -> Tuple[float, List[str]]:
        """Wrapper for backwards compatibility in tests."""
        score, reasons, _ = calculate_confidence(entity, category, title, summary, content, self.normalizer)
        return score, reasons

    def validate_entities(
        self, 
        entities: Dict[str, List[str]], 
        title: str, 
        summary: str, 
        content: str, 
        source: str
    ) -> Tuple[Dict[str, List[str]], Dict[str, List[Dict[str, Any]]]]:
        """
        Orchestrates post-processing validation, strict lookups, deduplication, conflict resolution, 
        and confidence scoring across all entity lists.
        """
        validated = {
            "people": [],
            "political_parties": [],
            "countries": [],
            "states": [],
            "cities": [],
            "organizations": [],
            "topics": list(entities.get("topics", []))
        }
        
        rejected_records = {
            "people": [],
            "political_parties": [],
            "countries": [],
            "states": [],
            "cities": [],
            "organizations": []
        }
        
        # 1. First Pass: Noise filtering, absolute party strictness, soft geography lookup, and confidence checks
        for category, entities_list in entities.items():
            if category == "topics":
                continue
                
            temp_validated = []
            for raw_entity in entities_list:
                # A. Clean entity text (possessives and lonely brackets/apostrophes)
                cleaned = clean_entity_text(raw_entity)
                
                # B. Preliminary noise & blacklists filters
                noise_detected, noise_reason = is_noise(cleaned)
                if noise_detected:
                    rejected_records[category].append({
                        "entity": raw_entity,
                        "cleaned": cleaned,
                        "reason": noise_reason,
                        "confidence": 0.0
                    })
                    continue
                    
                text_lower = cleaned.lower()
                
                # C. Absolute Political Party strictness (ONLY exact matches or validated aliases allowed)
                if category == "political_parties":
                    if text_lower in self.normalizer.parties_map:
                        temp_validated.append(self.normalizer.parties_map[text_lower])
                    else:
                        rejected_records[category].append({
                            "entity": raw_entity,
                            "cleaned": cleaned,
                            "reason": "Failed political party exact matching check",
                            "confidence": 0.0
                        })
                    continue
                    
                # D. Calculate dynamic confidence score (with clamped casing penalty and title/frequency boosts)
                score, reasons, is_dict_match = calculate_confidence(
                    cleaned, category, title, summary, content, self.normalizer
                )
                
                # E. Geography soft checks (dictionary exact mapping OR soft confidence recall)
                if category in ["countries", "states", "cities"]:
                    geo_passed, geo_name, geo_reason = validate_geography(
                        cleaned, category, self.normalizer, score, self.min_confidence,
                        title=title, summary=summary, content=content, reasons=reasons
                    )
                    if geo_passed:
                        temp_validated.append(geo_name)
                    else:
                        rejected_records[category].append({
                            "entity": raw_entity,
                            "cleaned": cleaned,
                            "reason": f"Geography validation failed: {geo_reason}",
                            "confidence": score
                        })
                    continue
                    
                # F. Standard category threshold pruning (people and organizations)
                if score < self.min_confidence:
                    rejected_records[category].append({
                        "entity": raw_entity,
                        "cleaned": cleaned,
                        "reason": f"Confidence score ({score}) below threshold ({self.min_confidence}). Reasons: {', '.join(reasons)}",
                        "confidence": score
                    })
                else:
                    # Resolve to canonical politician/ministry forms if dictionary entries exist, else format standard proper noun casing
                    canonical_name = cleaned
                    if category == "people":
                        canonical_name = self.normalizer.politicians_map.get(text_lower, cleaned)
                    elif category == "organizations":
                        if text_lower in self.normalizer.ministries_map:
                            canonical_name = self.normalizer.ministries_map[text_lower]
                        elif text_lower in self.normalizer.abbreviations_map:
                            canonical_name = self.normalizer.abbreviations_map[text_lower]
                    temp_validated.append(canonical_name)
                    
            validated[category] = temp_validated

        # 2. Apply dynamic fuzzy overlap deduplication merging for people & organizations
        for cat in ["people", "organizations"]:
            validated[cat] = merge_fuzzy_duplicates(validated[cat])
            
        # 3. Apply article-level context classifier and resolution (e.g. Congress -> INC)
        validated = resolve_contextual_entities(validated, validated["topics"], self.normalizer, title, summary, content)
        
        # 4. Resolve category priority conflicts (party > people > geo > org)
        validated = resolve_category_conflicts(validated, self.normalizer, title, summary, content)
        
        return validated, rejected_records
