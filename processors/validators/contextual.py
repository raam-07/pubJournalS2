from typing import List

# Let's define the keywords for the article-level context classifier
CONTEXTS = {
    "politics": [
        "parliament", "congress", "ministry", "minister", "election", 
        "campaign", "government", "politician", "political", "candidate", 
        "coalition", "opposition", "assembly", "cabinet", "pm", "cm", "bjp", "inc"
    ],
    "war": [
        "war", "military", "army", "attack", "conflict", "defense", 
        "strike", "weapon", "battle", "civilian", "troops", "soldier", 
        "casualties", "forces", "air assault", "ceasefire", "fighting", "shelling"
    ],
    "entertainment": [
        "film", "movie", "actor", "actress", "cinema", "entertainment", 
        "drama", "music", "album", "director", "hollywood", "bollywood", "pop", "star"
    ],
    "finance": [
        "finance", "budget", "economy", "gdp", "inflation", "tax", 
        "market", "bank", "revenue", "fiscal", "company", "stock", 
        "trade", "profit", "corporate", "share", "investment", "business"
    ],
    "crime": [
        "crime", "arrest", "police", "jail", "murder", "theft", 
        "fraud", "suspect", "victim", "criminal", "court", "case", "charge"
    ],
    "sports": [
        "sports", "match", "cricket", "football", "game", "tournament", 
        "win", "player", "team", "champion", "league", "cup", "stadium"
    ],
    "diplomacy": [
        "diplomacy", "foreign", "bilateral", "summit", "embassy", 
        "ambassador", "treaty", "ties", "relations", "external affairs", "un"
    ],
    "elections": [
        "election", "elections", "vote", "votes", "voting", "polling", 
        "polls", "ballot", "candidate", "constituency", "by-poll"
    ]
}

def classify_article_context(title: str, summary: str, content: str) -> List[str]:
    """
    Detects article-level contexts: politics, war, entertainment, finance, crime, sports, diplomacy, elections.
    """
    combined = f"{title}\n{summary}\n{content}".lower()
    detected = []
    for context, keywords in CONTEXTS.items():
        # Count keyword matches
        match_count = 0
        for kw in keywords:
            if kw in combined:
                match_count += 1
        # If at least 2 distinct keywords match
        if match_count >= 2:
            detected.append(context)
    return detected

def resolve_contextual_entities(
    validated: dict, 
    topics: List[str], 
    normalizer, 
    title: str = "", 
    summary: str = "", 
    content: str = ""
) -> dict:
    """
    Article-level context classifier and resolver.
    Uses detected context to help map and validate ambiguous entities.
    
    Example:
    If article topic = politics/elections, then "Congress" -> political_party 'Indian National Congress'
    If article topic = finance, "Congress" -> remains organization or is rejected/modified.
    """
    # Classify context dynamically
    detected_contexts = classify_article_context(title, summary, content)
    
    # Merge detected contexts into topics to help validation downstream
    all_topics = set(topics)
    for ctx in detected_contexts:
        # Capitalize first letter to match style
        all_topics.add(ctx.capitalize())
    validated["topics"] = sorted(list(all_topics))
    
    is_politics = "politics" in detected_contexts or "elections" in detected_contexts or any(
        t.lower() in ["politics", "elections"] for t in topics
    )
    is_finance = "finance" in detected_contexts or any("finance" in t.lower() or "budget" in t.lower() for t in topics)
    
    # 1. Contextual Resolution: "Congress" -> Indian National Congress (in Politics context)
    orgs = validated.get("organizations", [])
    parties = validated.get("political_parties", [])
    
    # If "Congress" is in organizations, check context
    if "Congress" in orgs:
        if is_politics:
            orgs.remove("Congress")
            if "Indian National Congress" not in parties:
                parties.append("Indian National Congress")
            validated["political_parties"] = sorted(parties)
            validated["organizations"] = sorted(orgs)
            
    # 2. Contextual Resolution: Standard NER misclassified parties in organizations
    # If the organization name is a known party alias and we are in a politics context, move it.
    if is_politics:
        orgs_copy = list(validated.get("organizations", []))
        for org in orgs_copy:
            org_lower = org.lower()
            if org_lower in normalizer.parties_map:
                if org in validated["organizations"]:
                    validated["organizations"].remove(org)
                canonical_party = normalizer.parties_map[org_lower]
                parties = validated.get("political_parties", [])
                if canonical_party not in parties:
                    parties.append(canonical_party)
                    validated["political_parties"] = sorted(parties)
                validated["organizations"] = sorted(validated["organizations"])
                
    return validated
