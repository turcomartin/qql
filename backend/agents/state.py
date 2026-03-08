from typing import Literal, TypedDict


class AgentState(TypedDict):
    # Input
    user_message: str
    history: list[dict]                          # trimmed conversation turns
    mode: Literal["conversational", "oneshot"]
    selected_tables: list[str]                   # tables user chose to include

    # Routing
    intent: str | None                           # "data" | "chat"

    # NLP preprocessing — populated on first SQL attempt, reused on retries
    detected_language: str | None               # "en" | "es"
    candidate_products: list[str]               # matched product names from EDA context
    search_patterns: list[str]                  # ILIKE patterns incl. acronym expansions

    # EDA Consultant — populated before SQL agent runs
    investigation_log: list[dict]               # [{query, columns, rows, row_count}]
    investigation_context: str | None           # summary injected into sql_agent prompt
    consultant_verdict: str | None              # "proceed"|"partial"|"infeasible"|"question"

    # Analyst node — populated after eda_consultant when verdict is proceed/partial
    analyst_context: str | None          # compact summary injected into sql_agent prompt
    analyst_done: bool                   # True after analyst completes (success or fallback)

    # SQL Agent loop
    sql_attempts: int
    last_sql: str | None
    last_error: str | None                       # error text fed back to LLM on retry
    is_timeout: bool                             # timeout errors are non-retryable
