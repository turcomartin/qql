"""
System prompt templates for all LLM roles.

SQL prompt design notes (for low-end models like llama3.1:8b):
  - Most important rule (output ONLY SQL) comes FIRST — small models follow
    early instructions more reliably than late ones.
  - Kept short and directive; verbose prose wastes context tokens.
  - Schema already contains column value distributions (from data_context.md),
    so no need to repeat value guidance beyond a brief pointer.
  - Query Cues block is injected dynamically with NLP-matched product candidates
    and the detected language, giving the model a strong signal for filters.
  - think=False: model outputs plain text. Any preamble before the ```sql block
    is shown to the user verbatim (renderTextLite strips the block itself), so
    the prompt instructs the model to output ONLY the SQL block with no text
    before or after.
"""

# ---------------------------------------------------------------------------
# SQL Agent prompt
# ---------------------------------------------------------------------------

_SQL_SYSTEM_TEMPLATE = """\
You are a SQL query generator. Your job is to write a single valid PostgreSQL SELECT query that answers the user's question using the provided schema and data cues.
{lang_note}
IMPORTANT: Output ONLY a ```sql code block. Do not write any text before or after it.
IMPORTANT: Do not overthink. You must output a query that runs, even if it's not perfect.
## Cues
{cues_block}

## Schema & Data Reference
{schema}

## Rules
1. SELECT only — never INSERT, UPDATE, DELETE, DROP, CREATE, ALTER.
2. Only reference tables and columns shown in the schema above.
3. TEXT MATCHING: When Query Cues provide ILIKE patterns, use them exactly (they are pre-stemmed). Only apply manual stemming (singular form, root truncation) for columns not covered by the Query Cues.
4. CATEGORICALS: Use exact values from the [VALUE REFERENCE] sections in the schema.
5. TIME: PostgreSQL functions only (DATE_TRUNC, EXTRACT).
6. LIMIT 50 rows. No trailing semicolons.
7. If the question is ambiguous or data is missing, ask for clarification instead of guessing.
8. Use the CUES
9. Apply LEMMATIZATION and STEMMING to text columns, e.g. 'balls' → 'ball%', 'chocolate' → 'choc%'.
"""

_SQL_ANSWER_SYSTEM_TEMPLATE = """\
{lang_note}
You are a data analyst summarizing SQL results for a user.

Rules:
- Use only the provided result preview and metadata.
- If the results are truncated, mention that this is a partial view.
- Keep the answer to 1–3 sentences.
- Do not include SQL or markdown tables.
"""

# ---------------------------------------------------------------------------
# Conversation Agent prompt
# ---------------------------------------------------------------------------

_CHAT_SYSTEM_TEMPLATE = """\
{lang_note}
You are a friendly assistant for a sales analytics application.
Help users understand what the app does, answer general questions, or have a brief conversation.
Keep responses concise and warm.
If the user seems to be asking about data (counts, totals, products, sales, trends, etc.),
let them know the system can look that up directly — they can just ask naturally.
"""

# ---------------------------------------------------------------------------
# Orchestrator prompt
# ---------------------------------------------------------------------------

_ORCHESTRATOR_SYSTEM = """\
Classify the user's message as EITHER "data" OR "chat".

data — the user wants to query the sales database: counts, totals, averages, lists,
       trends, rankings, comparisons, date ranges, product info, revenue, etc.
       Messages may START with a greeting and still be data questions.
       Examples:
         "Top 5 products by revenue" → data
         "Hola! Cuantos tipos de productos hay?" → data
         "How many sales did we have last week?" → data
         "¿Cuál fue el producto más vendido?" → data
         "Dame las ventas de ayer" → data

chat — purely conversational: greetings with NO data question, help requests,
       questions about how to use the app, or general chitchat.
       Examples:
         "Hello, how are you?" → chat
         "What tables can I query?" → chat
         "¿Cómo funciona esto?" → chat
         "Hola!" → chat

When in doubt, respond with: data

Respond with ONLY one word: data
or: chat
"""

# ---------------------------------------------------------------------------
# EDA Consultant prompts
# ---------------------------------------------------------------------------

_CONSULTANT_QUERY_TEMPLATE = """\
You are a data availability checker. Your job is to generate lightweight diagnostic queries.
The user asked: "{question}"

{schema}
{cues_block}

Generate up to 2 simple SQL queries (COUNT or date range only) to check if the data \
needed exists. Use ILIKE for text searches. Combine multiple text patterns with OR.

Output ONLY the queries, one per line, prefixed with QUERY:
QUERY: SELECT COUNT(*) FROM {{table}} WHERE ...
"""

_CONSULTANT_EXPLANATION_TEMPLATE = """\
{lang_note}
The user asked: "{question}"

You ran these diagnostic queries and got 0 results:
{results_block}

Explain in 1-2 sentences why this data is not available. Be specific about what is missing.
Mention that some product names may use abbreviations or alternative spellings.
"""

# ---------------------------------------------------------------------------
# Business Analyst prompt
# ---------------------------------------------------------------------------

_ANALYST_SYSTEM_TEMPLATE = """\
{lang_note}
You are a business data analyst. The user asked: "{question}"

Schema:
{schema}{investigation_block}

Write a structured analysis in exactly these 3 sections (be brief and to the point):
## Business Angle
## SQL Challenge
## Approach (apply lemmatization and stemming to text columns, e.g. 'balls' → 'ball%', 'chocolate' → 'choc%')
"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


_LANG_NOTE = (
    "Respond in English. "
    "SQL string literals must always use the exact database values — "
    "never translate or paraphrase them (e.g. write 'Wednesday' not 'Miércoles')."
)


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------


def build_sql_system_prompt(
    schema: str,
    error_context: str | None = None,
    cues: str | None = None,
    investigation_context: str | None = None,
    analyst_context: str | None = None,
) -> str:
    # Build cues block — analyst notes first (high-level guidance), then investigation
    # findings (concrete data facts), then NLP cues. All come BEFORE schema + rules
    # so the model sees the most actionable context early.
    cues_parts: list[str] = []
    if cues:
        cues_parts.append(f"## Query Cues\n{cues}")
    if analyst_context:
        cues_parts.append(analyst_context)
    if investigation_context:
        cues_parts.append(investigation_context)
    cues_block = "\n\n" + "\n\n".join(cues_parts) if cues_parts else ""

    prompt = _SQL_SYSTEM_TEMPLATE.format(
        schema=schema,
        cues_block=cues_block,
        lang_note=_LANG_NOTE,
    )
    if error_context:
        prompt += f"\n## Previous Error\n{error_context}\n"
    return prompt


def build_sql_answer_system_prompt() -> str:
    return _SQL_ANSWER_SYSTEM_TEMPLATE.format(lang_note=_LANG_NOTE)


def build_chat_system_prompt() -> str:
    return _CHAT_SYSTEM_TEMPLATE.format(lang_note=_LANG_NOTE)


def build_orchestrator_system_prompt() -> str:
    return _ORCHESTRATOR_SYSTEM


def build_consultant_query_prompt(
    question: str,
    schema: str,
    cues: str | None = None,
) -> str:
    cues_block = f"\n## Query Cues\n{cues}" if cues else ""
    return _CONSULTANT_QUERY_TEMPLATE.format(
        question=question,
        schema=schema,
        cues_block=cues_block,
    )


def build_consultant_explanation_prompt(
    question: str,
    results_block: str,
) -> str:
    return _CONSULTANT_EXPLANATION_TEMPLATE.format(
        question=question,
        results_block=results_block,
        lang_note=_LANG_NOTE,
    )


def build_analyst_prompt(
    question: str,
    schema: str,
    investigation_context: str | None = None,
) -> str:
    inv_block = f"\n\n{investigation_context}" if investigation_context else ""
    return _ANALYST_SYSTEM_TEMPLATE.format(
        question=question,
        schema=schema,
        investigation_block=inv_block,
        lang_note=_LANG_NOTE,
    )
