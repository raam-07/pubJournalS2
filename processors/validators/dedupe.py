from typing import List

def merge_fuzzy_duplicates(names: List[str]) -> List[str]:
    """
    Merge shorter partial names into longer canonical anchors in the same article.
    e.g., 'Trump' -> 'Donald Trump'
          'Stalin' -> 'M. K. Stalin'
    """
    if not names:
        return []
        
    # Deduplicate and sort by length descending
    sorted_names = sorted(list(set(names)), key=len, reverse=True)
    merged = []
    
    for name in sorted_names:
        is_dup = False
        name_lower = name.lower()
        name_words = name_lower.split()
        
        for kept in merged:
            kept_lower = kept.lower()
            kept_words = kept_lower.split()
            
            # Case 1: The short name is a single word and is one of the words of the kept longer name
            # e.g., "Trump" is in "Donald Trump"
            if len(name_words) == 1 and name_words[0] in kept_words:
                is_dup = True
                break
                
            # Case 2: The short name consists of multiple words and all of them appear in order in the kept longer name
            # e.g., "M.K. Stalin" or "MK Stalin" matches "M. K. Stalin"
            normalized_name = "".join(name_words).replace(".", "")
            normalized_kept = "".join(kept_words).replace(".", "")
            if normalized_name in normalized_kept:
                is_dup = True
                break
                
        if not is_dup:
            merged.append(name)
            
    return sorted(merged)
