"""
Term variation generator for robust product name matching.

Generates all search-worthy variants of a search term so the NLP preprocessor
can produce broad ILIKE patterns that catch acronyms, diacritics, compound words,
and common alternative spellings.

Acronym mappings are loaded dynamically from skill.md (written and maintained by
the EDA agent) so they stay in sync with the actual product catalog.

No external libraries — stdlib only (unicodedata, re, pathlib).
"""

import re
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------------------
# Skill-file-based acronym map (replaces the old hardcoded ACRONYM_MAP).
# Loaded lazily on first call to generate_variations(); invalidated after
# skill.md is written by the EDA agent or updated via PUT /eda/skill.
# ---------------------------------------------------------------------------

_acronym_cache: dict[str, list[str]] | None = None

_SKILL_SECTION_RE = re.compile(
    r"## Acronym Mappings\n(.*?)(?=\n## |\Z)", re.DOTALL
)
_SKILL_ROW_RE = re.compile(
    r"^\|\s*([^|\-][^|]*?)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE
)


def _parse_skill_file(path: Path) -> dict[str, list[str]]:
    """
    Parse the ## Acronym Mappings table from skill.md.
    Returns a dict of lowercase_acronym → [lowercase_expansion, ...].
    Returns an empty dict if the file is missing or the section is absent.
    """
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    section = _SKILL_SECTION_RE.search(content)
    if not section:
        return {}

    result: dict[str, list[str]] = {}
    for m in _SKILL_ROW_RE.finditer(section.group(1)):
        acronym = m.group(1).strip().lower()
        expansion = m.group(2).strip().lower()
        # Skip header row, separator, and placeholder rows
        if (
            not acronym
            or not expansion
            or acronym in ("acronym", "none")
            or expansion in ("expansion", "—", "-")
            or set(acronym.replace(" ", "")).issubset({"-"})
            or "(none found" in acronym
        ):
            continue
        result.setdefault(acronym, [])
        if expansion not in result[acronym]:
            result[acronym].append(expansion)
    return result


def load_acronym_map() -> dict[str, list[str]]:
    """Return the acronym map, loading from skill.md on first call."""
    global _acronym_cache
    if _acronym_cache is not None:
        return _acronym_cache
    try:
        from config import settings  # local import avoids circular deps

        path = Path(settings.skill_path)
    except Exception:
        path = Path("/app/skill.md")
    _acronym_cache = _parse_skill_file(path)
    return _acronym_cache


def invalidate_acronym_cache() -> None:
    """Clear the cached acronym map so the next call reloads from skill.md."""
    global _acronym_cache
    _acronym_cache = None


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _strip_diacritics(text: str) -> str:
    """Remove diacritical marks: azúcar → azucar, alfajor → alfajor."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _split_compound(term: str) -> list[str]:
    """
    Split a run-together compound word into likely constituent parts.
    'sinazucar' → ['sin', 'azucar']  (heuristic: common Spanish prefixes)
    Only splits if the result has at least 2 parts of length ≥ 3.
    """
    _PREFIXES = ["sin", "con", "super", "mini", "maxi", "mega", "sin", "de", "al"]
    for prefix in _PREFIXES:
        if term.startswith(prefix) and len(term) > len(prefix) + 2:
            rest = term[len(prefix):]
            if len(rest) >= 3:
                return [prefix, rest]
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_variations(term: str) -> list[str]:
    """
    Return all search-worthy variants of *term* for use in ILIKE filters.

    Variants generated (deduped, lowercased):
      - original
      - without diacritics
      - acronym expansion(s) loaded from skill.md  (ddl → dulce de leche)
      - reverse acronym lookup  (dulce de leche → ddl)
      - compound word split constituents  (sinazucar → sin, azucar)
      - first significant word (for long multi-word terms)

    All returned values are intended for use in ILIKE patterns:
        SELECT ... WHERE product_name ILIKE '%<variation>%'
    """
    term = term.lower().strip()
    if not term:
        return []

    acronym_map = load_acronym_map()

    # Build reverse map on the fly from the loaded acronym map
    reverse_map: dict[str, list[str]] = {}
    for _acronym, _expansions in acronym_map.items():
        for _exp in _expansions:
            reverse_map.setdefault(_exp, []).append(_acronym)

    seen: dict[str, None] = {}  # ordered dedup

    def _add(v: str) -> None:
        v = v.strip()
        if v and len(v) >= 2:
            seen[v] = None
            # Also add diacritic-stripped version
            stripped = _strip_diacritics(v)
            if stripped != v:
                seen[stripped] = None

    _add(term)

    # Acronym expansion (ddl → dulce de leche)
    if term in acronym_map:
        for exp in acronym_map[term]:
            _add(exp)

    # Reverse acronym lookup (dulce de leche → ddl)
    if term in reverse_map:
        for acr in reverse_map[term]:
            _add(acr)

    # Compound splitting (sinazucar → sin, azucar)
    parts = _split_compound(term)
    for part in parts:
        _add(part)

    # First significant word (if term has multiple words)
    words = re.split(r"\s+", term)
    if len(words) > 1 and len(words[0]) >= 3:
        _add(words[0])

    return list(seen)


def build_ilike_patterns(terms: list[str]) -> list[str]:
    """
    Given a list of search terms, generate all ILIKE pattern strings.
    Returns patterns like '%alfajor%', '%ddl%', '%dulce de leche%'.
    """
    patterns: dict[str, None] = {}
    for term in terms:
        for variant in generate_variations(term):
            patterns[f"%{variant}%"] = None
    return list(patterns)
