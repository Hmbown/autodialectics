import re

def normalize_text(text: str) -> str:
    """Strip whitespace, collapse multiple spaces/newlines."""
    text = text.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()

def keyword_set(text: str) -> set[str]:
    """Extract lowercase words longer than 3 chars as a set."""
    return {w.lower() for w in text.split() if len(w) > 3}

def unique_nonempty(items: list[str]) -> list[str]:
    """Deduplicate preserving order, filter empty strings."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        stripped = item.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            result.append(stripped)
    return result

def words(text: str) -> list[str]:
    """Split text on whitespace."""
    return text.split()

def chunk_text(text: str, size: int = 1400, overlap: int = 180) -> list[str]:
    """Sliding window chunker for text."""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += size - overlap
    return chunks

def overlap_score(a: str, b: str) -> float:
    """Jaccard-like token overlap between two strings."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)

def repeated_sentence_ratio(text: str) -> float:
    """Ratio of sentences that appear more than once."""
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip().lower() for s in sentences if s.strip()]
    if not sentences:
        return 0.0
    from collections import Counter
    counts = Counter(sentences)
    repeated = sum(1 for s, c in counts.items() if c > 1)
    return repeated / len(sentences)

def trigram_repetition_ratio(text: str) -> float:
    """Ratio of trigrams that repeat."""
    tokens = text.lower().split()
    if len(tokens) < 3:
        return 0.0
    trigrams = [tuple(tokens[i:i+3]) for i in range(len(tokens) - 2)]
    from collections import Counter
    counts = Counter(trigrams)
    repeated = sum(1 for t, c in counts.items() if c > 1)
    return repeated / len(trigrams) if trigrams else 0.0
