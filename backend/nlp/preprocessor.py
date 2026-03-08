"""
NLP Preprocessor — extracts search-relevant terms from a user message and
maps them to candidate product names using lightweight string matching.

No vector search or BM25 required. Strategy:
  1. Language detection (English / Spanish) via langdetect + Spanish keyword heuristic.
  2. Tokenise + lemmatise with spaCy (en_core_web_sm or es_core_news_sm), keeping
     only content-bearing tokens (NOUN, PROPN, ADJ, NUM) with length ≥ 3.
  3. Generate ALL variations per term (acronyms, diacritics, compound splits) via
     variations.py — produces broad ILIKE patterns that start general and narrow.
  4. Match product list against ALL variations using prefix/substring/similarity.

The result is injected as a "Query Cues" block in the SQL system prompt so
the LLM can write accurate ILIKE filters without guessing at product names.

Graceful degradation: if spaCy is not installed (e.g. local dev without the
models), the preprocessor falls back to simple whitespace tokenisation.
"""

import re
from difflib import SequenceMatcher

from .variations import build_ilike_patterns, generate_variations

# ---------------------------------------------------------------------------
# Spanish function words used as a fast language heuristic for short texts.
# These are unambiguously Spanish and not common English words.
# ---------------------------------------------------------------------------
_ES_MARKERS = frozenset([
    "de", "la", "el", "los", "las", "en", "del", "con", "por", "una",
    "para", "que", "se", "al", "su", "un", "es", "son", "hay", "más",
    "cuánto", "cuántas", "cuáles", "mostrar", "muéstrame", "dame",
    "ventas", "productos", "precio", "semana", "día", "mes",
])

# ---------------------------------------------------------------------------
# Lazy-loaded spaCy models — loaded on first use, reused thereafter.
# ---------------------------------------------------------------------------
_nlp_cache: dict = {}


def _get_nlp(lang: str):
    """Return a cached spaCy model for *lang* ('en' or 'es')."""
    if lang not in _nlp_cache:
        try:
            import spacy  # noqa: PLC0415

            model = "es_core_news_sm" if lang == "es" else "en_core_web_sm"
            # Disable unused pipeline components to keep it fast
            _nlp_cache[lang] = spacy.load(model, disable=["parser", "ner"])
        except Exception:
            _nlp_cache[lang] = None  # Mark as unavailable; fall back below
    return _nlp_cache[lang]


def reload_models() -> None:
    """Clear the spaCy model cache — useful after a hot-reload in development."""
    _nlp_cache.clear()


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """
    Return 'en' or 'es'.

    Strategy:
      1. Quick heuristic: if any unambiguous Spanish marker word is present,
         return 'es' immediately (fast, reliable for short queries).
      2. Fall back to langdetect for longer / ambiguous texts.
      3. Default to 'en' on any failure.
    """
    words = set(re.findall(r"\b[a-záéíóúñü]+\b", text.lower()))
    if words & _ES_MARKERS:
        return "es"
    try:
        from langdetect import DetectorFactory, detect  # noqa: PLC0415

        DetectorFactory.seed = 0  # deterministic
        lang = detect(text)
        return lang if lang in ("en", "es") else "en"
    except Exception:
        return "en"


# ---------------------------------------------------------------------------
# Term extraction
# ---------------------------------------------------------------------------

def _extract_terms_spacy(text: str, lang: str) -> list[str]:
    nlp = _get_nlp(lang)
    if nlp is None:
        return _extract_terms_fallback(text)
    doc = nlp(text)
    seen: dict[str, None] = {}
    for token in doc:
        if (
            not token.is_stop
            and not token.is_punct
            and not token.is_space
            and token.pos_ in ("NOUN", "PROPN", "ADJ", "NUM")
            and len(token.lemma_) >= 3
        ):
            seen[token.lemma_.lower()] = None  # ordered dedup via dict
    return list(seen)


def _extract_terms_fallback(text: str) -> list[str]:
    """Simple fallback when spaCy is unavailable."""
    _STOPWORDS = {
        "the", "a", "an", "of", "in", "on", "at", "for", "and", "or", "is",
        "are", "was", "were", "be", "been", "show", "me", "give", "get", "list",
        "what", "how", "many", "much", "can", "could", "would", "please",
        # Spanish
        "de", "la", "el", "los", "las", "en", "del", "con", "por", "una",
        "para", "que", "se", "al", "su", "un", "es", "son",
    }
    tokens = re.findall(r"\b\w+\b", text.lower())
    seen: dict[str, None] = {}
    for t in tokens:
        if t not in _STOPWORDS and len(t) >= 3:
            seen[t] = None
    return list(seen)


# ---------------------------------------------------------------------------
# Candidate product matching — variation-aware
# ---------------------------------------------------------------------------

_WORD_SPLIT_RE = re.compile(r"[\s\-/]+")


def _word_tokens(product: str) -> list[str]:
    return [w.lower() for w in _WORD_SPLIT_RE.split(product) if len(w) >= 2]


def match_candidates(
    terms: list[str],
    products: list[str],
    max_results: int = 15,
) -> list[str]:
    """
    Return up to *max_results* product names that are likely relevant to *terms*.

    Uses all variations of each term (acronym expansions, diacritics, compound
    splits) for matching, so 'ddl' finds 'Alfajor DDL x un' via both the
    original term and the expansion 'dulce de leche'.

    Matching rules (any of, applied to all variants):
      • Variant (≥ 3 chars) is a prefix of a product word.
      • Variant (≥ 3 chars) is a substring of a product word.
      • SequenceMatcher similarity ≥ 0.82 between variant and a product word.
    """
    if not terms or not products:
        return []

    # Build all variants for each term upfront
    all_variants: list[str] = []
    for term in terms:
        all_variants.extend(generate_variations(term))

    matched: list[str] = []
    seen: set[str] = set()

    for product in products:
        if len(matched) >= max_results:
            break
        if product in seen:
            continue

        p_words = _word_tokens(product)
        for variant in all_variants:
            if len(variant) < 3:
                continue
            for word in p_words:
                if word.startswith(variant) or variant in word:
                    matched.append(product)
                    seen.add(product)
                    break
                if len(word) >= 3 and SequenceMatcher(None, variant, word).ratio() >= 0.82:
                    matched.append(product)
                    seen.add(product)
                    break
            if product in seen:
                break

    return matched


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preprocess(message: str, product_names: list[str]) -> dict:
    """
    Analyse *message* and return a dict with:
      - detected_language: 'en' | 'es'
      - terms: list of normalised content lemmas
      - candidate_products: list of matching product names (up to 15)
      - search_patterns: list of ILIKE patterns for all term variations
                         (e.g. ['%alfajor%', '%ddl%', '%dulce de leche%'])
    """
    lang = detect_language(message)
    terms = _extract_terms_spacy(message, lang)
    candidates = match_candidates(terms, product_names)
    patterns = build_ilike_patterns(terms)
    return {
        "detected_language": lang,
        "terms": terms,
        "candidate_products": candidates,
        "search_patterns": patterns,
    }
