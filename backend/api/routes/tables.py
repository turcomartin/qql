"""
Tables endpoint — returns available tables with EDA-derived descriptions
for the frontend onboarding table selection screen.
"""

import re
from pathlib import Path

from fastapi import APIRouter

from config import settings

router = APIRouter()

# Hardcoded example queries per table (both languages).
# These are curated for quality and used as suggestion chips in the UI.
_TABLE_METADATA: dict[str, dict] = {
    "sales": {
        "label_en": "Sales Records",
        "label_es": "Registros de Ventas",
        "example_queries": {
            "en": [
                "What were the top 5 products by revenue?",
                "Show me total sales by day of the week",
                "Which waiter had the most sales last month?",
                "What is the average ticket price?",
                "Show me sales of alfajores",
            ],
            "es": [
                "¿Cuáles fueron los 5 productos más vendidos por ingresos?",
                "Mostrar ventas totales por día de la semana",
                "¿Qué mozo tuvo más ventas el último mes?",
                "¿Cuál es el precio promedio por ticket?",
                "Mostrar ventas de alfajores",
            ],
        },
    }
}


def _parse_data_context(path: Path) -> dict:
    """
    Extract stats from data_context.md: row count, date range, description.
    Falls back to defaults if parsing fails.

    Parses both the new format (with Business Domain section) and the legacy
    format so the frontend works regardless of which EDA version generated
    the file.
    """
    defaults = {
        "table_name": None,
        "rows": None,
        "date_from": None,
        "date_to": None,
        "description_en": "Data table",
        "description_es": "Tabla de datos",
    }

    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return defaults

    stats = dict(defaults)

    # Table name from header or Dataset Overview
    m = re.search(r"# Data Context:\s*(\w+)", text)
    if m:
        stats["table_name"] = m.group(1)

    # Row count
    m = re.search(r"Total rows?[:\s]+([0-9,]+)", text, re.IGNORECASE)
    if m:
        try:
            stats["rows"] = int(m.group(1).replace(",", "").replace(".", ""))
        except ValueError:
            pass

    # Date range
    m = re.search(r"Date range[:\s]+(\d{4}-\d{2}-\d{2})[^\d]+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if m:
        stats["date_from"] = m.group(1)
        stats["date_to"] = m.group(2)

    # Business Domain section → use as description (LLM writes in user's language)
    m = re.search(r"## Business Domain\n(.*?)(?=\n##|\n---)", text, re.DOTALL)
    if m:
        domain = m.group(1).strip()
        if domain:
            stats["description_en"] = domain
            stats["description_es"] = domain
    elif stats["rows"] and stats["date_from"] and stats["date_to"]:
        # Fallback: build a basic description from stats
        tbl = stats["table_name"] or "table"
        stats["description_en"] = (
            f"{stats['rows']:,} rows · "
            f"{stats['date_from']} → {stats['date_to']}"
        )
        stats["description_es"] = (
            f"{stats['rows']:,} filas · "
            f"{stats['date_from']} → {stats['date_to']}"
        )

    return stats


@router.get("/tables")
async def list_tables() -> list[dict]:
    """
    Return available tables with EDA-derived descriptions.

    If data_context.md contains a discovered table name, uses that.
    Falls back to _TABLE_METADATA for curated example queries when the
    table name matches; otherwise returns generic empty examples.

    Response shape:
    [{
      "name": "sales",
      "label_en": "Sales Records",
      "label_es": "Registros de Ventas",
      "description_en": "...",
      "description_es": "...",
      "stats": {"rows": 24212, "date_from": "2024-10-01", "date_to": "2024-11-19"},
      "example_queries": {"en": [...], "es": [...]}
    }]
    """
    context_path = Path(settings.eda_context_path)
    parsed = _parse_data_context(context_path)

    table_name = parsed.get("table_name") or "sales"
    meta = _TABLE_METADATA.get(table_name, {})

    # Labels: use curated metadata if available, otherwise derive from table name
    label_en = meta.get("label_en", table_name.replace("_", " ").title())
    label_es = meta.get("label_es", table_name.replace("_", " ").title())

    return [{
        "name": table_name,
        "label_en": label_en,
        "label_es": label_es,
        "description_en": parsed["description_en"],
        "description_es": parsed["description_es"],
        "stats": {
            "rows": parsed["rows"],
            "date_from": parsed["date_from"],
            "date_to": parsed["date_to"],
        },
        "example_queries": meta.get("example_queries", {"en": [], "es": []}),
    }]
