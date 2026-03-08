# QQL — Natural Language Interface for PostgreSQL

A natural-language interface to a PostgreSQL database, powered by a locally-hosted LLM. Ask questions in plain language and get SQL-backed answers — without writing a single query.

```
"What were the top 5 products by revenue last month?"
  → EDA context → consultant probes data → analyst reasons → SQL generated → verified → executed → table shown
```

The system is designed as a **tool, not a chatbot**. The model is not expected to have all the answers. User expertise combined with the tool produces better results than either alone — the interface is a force multiplier, not a replacement.

---

## Table of Contents

- [Architecture](#architecture)
- [Design Philosophy: Semi-Structured Data](#design-philosophy-semi-structured-data)
- [EDA Agent](#eda-agent)
- [Agent Pipeline](#agent-pipeline)
- [Skill System](#skill-system)
- [SQL Safety](#sql-safety)
- [SSE Streaming Events](#sse-streaming-events)
- [Query Modes](#query-modes)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Platform Notes](#platform-notes)
- [Configuration Reference](#configuration-reference)
- [Switching LLM Providers](#switching-llm-providers)
- [Adding a New LLM Provider](#adding-a-new-llm-provider)
- [Rate Limiting](#rate-limiting)
- [Development Setup](#development-setup)
- [Known Limitations & Future Work](#known-limitations--future-work)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  docker-compose                                                           │
│                                                                           │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────────┐  │
│  │  PostgreSQL  │   │    Ollama    │   │          FastAPI             │  │
│  │  port 5435   │   │  port 11434  │◄──│  LangGraph pipeline          │  │
│  │  (sales DB)  │   │  (LLM server)│   │  EDA agent (startup)         │  │
│  └──────────────┘   └──────────────┘   │  NLP preprocessor            │  │
│         ▲                              │  SQL verifier + runner       │  │
│         └──────────────────────────────└──────────────┬───────────────┘  │
│                                                        │                  │
│                                         ┌──────────────▼──────────────┐  │
│                                         │   React + Vite (nginx)      │  │
│                                         │   port 8080                 │  │
│                                         └─────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

**LangGraph agent pipeline:**

```
User message
     │
     ▼
Orchestrator ─── classifies intent ───► "chat" ──► Conversation Agent ──► response
     │
     ▼ "data"
EDA Consultant ─── probes data availability with lightweight SQL
     │
     ├── data exists → Analyst (business reasoning: angle / challenge / approach)
     │                      │
     │                      ▼
     │               SQL Agent (up to MAX_SQL_RETRIES)
     │                 ├── 1. Generate SQL  (LLM + full schema + cues)
     │                 ├── 2. Verify SQL    (sqlglot AST — SELECT-only, allowlisted tables)
     │                 ├── 3. Execute       (asyncpg, read-only, statement_timeout)
     │                 └── error → feed error back → retry
     │
     └── data unavailable → explain why → ask user for clarification
```

---

## Design Philosophy: Semi-Structured Data

In an ideal world, the sales table would have a product ID with proper dimension tables describing each product. That's not the case here — we're working with **semi-structured data**, where product identity lives entirely in a free-text `product_name` column.

This creates a core problem: queries may return incomplete results if the model generates filters that don't match all spelling variants, abbreviations, or naming conventions used in the data. A user asking for "alfajor sales" might get only a fraction of the actual alfajor transactions if the model misses "Alf. 150 aniv." or "Alfajor Super DDL".

This is an intentional design constraint — not a bug. The EDA, NLP preprocessing, and skill systems exist specifically to mitigate it.

**Why not restructure the data?** You could. But when deploying this product to a real client, their data team may need to carry out restructuring, or it might not be feasible at all. A text-to-SQL tool should adapt to the client's existing workflows — not the other way around.

**Why not use a vector database for product search?** It would help. But the same constraint applies: very likely no client will adapt their infrastructure to our product. The system is designed to work with a standard PostgreSQL stack that any existing system already has.

The practical consequence is that **results should be treated as estimates** when text filtering is involved. The system surfaces this uncertainty by showing exactly what SQL was run and what it matched.

---

## EDA Agent

The EDA (Exploratory Data Analysis) agent runs at startup and on demand to build a rich context document (`data_context.md`) that is injected into every SQL generation prompt. Without this, an 8B model has no idea what the table contains and is forced to guess — the EDA front-loads the knowledge so the model can reason accurately.

### Four-phase pipeline

```
Phase 1: Schema Discovery    — information_schema → column names, types, nullable flags
Phase 2: Column Profiling    — adaptive SQL per column type:
                                 Numeric:  MIN, MAX, AVG, STDDEV, PERCENTILE_CONT (P25/P50/P75)
                                 Text:     distinct counts, top-N by frequency, or prefix sampling
                                 Temporal: date range, day-of-week distribution
Phase 3: Cross-Column        — products of numeric column pairs (up to EDA_MAX_NUMERIC_PAIRS)
Phase 4: LLM Interpretation  — single LLM call → semantic sections below
```

If Phase 4 fails (LLM unreachable), the output falls back to template-only (Phases 1–3 only) — the system stays functional with reduced SQL quality.

### Output: `data_context.md`

`data_context.md` is **auto-generated by the EDA agent** at startup and whenever you call `POST /eda/refresh` (or run `./start.sh --reset-eda`). It will be regenerated as the data changes; only the `## Notes` section is preserved across runs.

```markdown
## Business Domain       ← LLM: what this table stores, business context
## Column Guide          ← LLM: one line per column, units, format, domain meaning
## Taxonomy              ← LLM: text values grouped into categories
## Key Metrics           ← LLM: 3-5 reference facts with actual numbers
## Business Rules        ← LLM: actionable SQL filter patterns (e.g. quantity < 0 for returns)
## Data Quality Notes    ← LLM: null rates, suspicious values, IS NOT NULL guidance

---

## Dataset Overview      ← template: row count, date range
## Column Overview       ← template: compact table — all columns, type, distinct, null%, range/σ
## Value Reference       ← template: exact values for low-cardinality columns (copy verbatim in SQL)
## Statistics            ← template: Range, Avg, Stddev, Median, P25/P75, Distinct, Nulls per numeric column
                                     Date Ranges subsection for temporal columns

---
## Notes                 ← user-owned: never overwritten across regenerations
```

The LLM sections and template sections serve different roles: LLM sections give the model *semantic understanding* (what does `quantity < 0` mean?). Template sections give it *exact values* (what string should I use in an ILIKE?). Both are necessary.

### Output: `skill.md`

After profiling, the EDA agent also runs a lightweight LLM call to infer **acronym mappings** from product names:

```markdown
## Acronym Mappings
| Acronym | Expansion    |
|---------|--------------|
| DDL     | Dulce de Leche |
| ALF     | Alfajor      |
```

These mappings are loaded by the NLP preprocessor and used to expand user queries before product name matching — see [Skill System](#skill-system).

Both files are bind-mounted from the repo root into the container. They are human-readable and editable; changes persist across EDA regenerations (via the `## Notes` sections).

### Managing EDA state

```bash
# Reset and regenerate (wipes both files, triggers fresh EDA if backend is running)
./start.sh --reset-eda

# Force refresh via API (no restart needed)
curl -X POST http://localhost:8000/eda/refresh

# Check EDA status
curl http://localhost:8000/eda/status
```

---

## Agent Pipeline

### Orchestrator

Every message is classified as `data` (SQL needed) or `chat` (general conversation). This is a single cheap LLM call with no schema injected. When in doubt, it defaults to `data`.

### EDA Consultant

For data questions, the Consultant runs **before** SQL generation to check whether the requested data actually exists. It generates 1–2 lightweight diagnostic SQL queries (`COUNT` or date range checks) and runs them.

- **Data found** → pass findings (e.g. "found 15 matching products") to the Analyst
- **Data not found** → explain why in natural language and optionally ask the user a clarifying question with option chips

This prevents the SQL Agent from generating plausible-looking queries that return zero rows because the product name was spelled differently.

### Business Analyst

A brief reasoning step between the Consultant and the SQL Agent. Given the user's question and the Consultant's findings, the Analyst produces three sentences:

- **Business Angle** — what the user is really asking for
- **SQL Challenge** — what makes this query non-trivial
- **Approach** — how to structure the SQL

This "thinking out loud" step significantly improves SQL quality on complex queries, especially for 8B models that struggle with multi-step reasoning.

### SQL Agent

The core loop. Runs up to `MAX_SQL_RETRIES` attempts:

1. **Generate** — LLM with full schema (structural schema + `data_context.md`), Query Cues (NLP-matched product names), Analyst notes, Consultant findings, and previous error on retries
2. **Verify** — sqlglot AST check (see [SQL Safety](#sql-safety))
3. **Execute** — asyncpg with `statement_timeout` and read-only user
4. **On error** — retry with the error message in context
5. **On timeout** — non-retryable; emit terminal error

### Context management

Conversation history is trimmed to `MAX_CONTEXT_TOKENS * 0.6`, reserving 40% for system prompt + schema + response. Token count is estimated as `len(text) // 4`.

In **one-shot mode**, no history is sent — maximizing context for complex queries.

### Thinking mode

Models that support native chain-of-thought (`think: true` in the Ollama API, e.g. Qwen3, DeepSeek-R1, QwQ) will stream their reasoning as `thinking` SSE events. The frontend shows these as a collapsible "thinking" block with animated dots while reasoning is in progress.

---

## Skill System

The Skill file (`skill.md`) is a persistent, user-editable knowledge base that augments the NLP preprocessor.

**Acronym expansion:** When a user types "DDL alfajores", the preprocessor expands "DDL" → "Dulce de Leche" before running product name matching, generating better ILIKE patterns for the SQL agent.

**Editing the skill file:** Open the Skill panel from the header (⚙ icon). The editor shows the current `skill.md` content and a parsed table of all active acronym mappings. Changes are saved immediately via `PUT /eda/skill` and take effect on the next request — no restart required.

**Re-inference:** The "Re-infer" button re-runs the LLM acronym extraction against the current product name list and merges new findings with existing entries. User-added mappings are never overwritten.

---

## SQL Safety

`SQLVerifier` (`backend/sql/verifier.py`) uses [sqlglot](https://github.com/tobymao/sqlglot) to perform AST-level validation — not regex, which can be bypassed.

Four checks run in order:

1. **Parseable** — reject anything sqlglot can't parse as valid PostgreSQL.
2. **SELECT only** — top-level AST node must be `exp.Select`. Blocks `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `TRUNCATE`.
3. **Full AST walk** — every node in the tree is checked, catching DML inside subqueries, CTEs, or function calls.
4. **Table allowlist** — every table reference must be in the known-tables set, which is populated dynamically by the EDA agent at startup (`set_known_tables()`).

Queries that pass all checks are normalized by sqlglot (consistent formatting, no trailing semicolons) before execution.

All queries run as `qql_readonly` (PostgreSQL `SELECT`-only user) — a second, independent layer of defense.

---

## SSE Streaming Events

`POST /chat/stream` returns `text/event-stream`. Each event is a JSON object:

| Type | Payload | UI action |
|------|---------|-----------|
| `thinking` | `{ content: "..." }` | Append to collapsible reasoning block (animated dots) |
| `thinking_done` | — | Collapse reasoning block |
| `consulting` | `{ content: "..." }` | Show EDA consultant status message |
| `question` | `{ content: "...", options: [...] }` | Show clarifying question with option chips |
| `text` | `{ content: "..." }` | Append to streaming response bubble |
| `sql` | `{ content: "SELECT ..." }` | Add syntax-highlighted code block with copy button |
| `table` | `{ columns, rows, row_count, truncated }` | Render results table |
| `error` | `{ content: "..." }` | Render red error card |
| `done` | — | Unlock input, save to history |

The frontend uses `fetch()` with `ReadableStream` (not `EventSource`) to support POST with a request body.

### Why a custom queue instead of LangGraph streaming?

LangGraph's `astream()` / `astream_events()` offers two modes: full state snapshots after each node completes, or token-level streaming — but only if you use LangChain's `ChatModel` abstraction (which this project deliberately avoids in favour of its own `LLMProvider` ABC).

Neither mode covers what the UI actually needs: **mixed fine-grained events emitted from inside a single node**, interleaved as things happen:

| Event | Emitted from | LangGraph streaming? |
|-------|-------------|----------------------|
| `consulting` — data probe running | mid-node, before LLM starts | ❌ |
| `thinking` tokens — analyst reasoning | per-token, inside LLM loop | ❌ |
| `sql_thinking` tokens — SQL reasoning | per-token, separate stream | ❌ |
| `question` — dynamic options from DB results | mid-node, after query | ❌ |
| `table` — query result payload | mid-node, after execution | ❌ |
| `done` — after the whole chain finishes | end of node | ❌ |

The solution is a `ContextVar`-backed `asyncio.Queue` in `backend/streaming.py`. At request time the route handler binds a fresh queue to the current async context. Any agent node anywhere in the call stack can then call `await emit(event)` without needing a queue reference threaded through every function signature. The route handler drains the queue into SSE line by line.

This is effectively what LangGraph would have to do internally if it supported this use case — just without the abstraction overhead.

---

## Query Modes

Toggled via the UI switch in the top-right corner, or via `mode` in the API request body.

### Conversational (default)
Rolling conversation history. Each turn is appended to `history[]` and sent with subsequent requests. Good for follow-up questions: `"Now group that by waiter"`.

### One-shot
No history sent. Only system prompt, schema, and current message. Maximizes available context for complex or long queries. The UI still shows the full conversation locally, but the model has no memory of prior turns.

---

## Project Structure

```
qql/
├── start.sh                         # Platform-aware startup (--stop, --reset-eda)
├── docker-compose.yml               # Core services: postgres, backend, frontend
├── docker-compose.nvidia.yml        # NVIDIA GPU overlay
├── Dockerfile                       # PostgreSQL image with preloaded sales data
├── .env                             # Environment config (gitignored)
├── data_context.md                  # EDA output — injected into every SQL prompt
├── skill.md                         # Acronym mappings — editable via UI
│
├── init/                            # DB init (runs once on first container start)
│   ├── 01_create_sales_tables.sql
│   ├── 02_load_sales_data.sql
│   ├── create_readonly_user.sh
│   └── data.csv                     # 24,212 rows of sales data
│
├── backend/
│   ├── main.py                      # FastAPI app + lifespan (EDA on startup)
│   ├── config.py                    # All settings via Pydantic Settings
│   ├── log_config.json              # Logging configuration for uvicorn
│   ├── requirements.txt
│   ├── Dockerfile
│   │
│   ├── eda/                         # EDA agent — profiles DB, writes data_context.md
│   │   ├── profiler.py              # Pure-SQL profiling: stats, distributions, stddev
│   │   ├── interpreter.py           # LLM call: semantic sections from raw profiles
│   │   ├── renderer.py              # Renders data_context.md (interpreted + fallback)
│   │   ├── agent.py                 # Orchestrates pipeline, manages caches, skill.md
│   │   └── __init__.py
│   │
│   ├── nlp/                         # NLP preprocessing for query term extraction
│   │   ├── preprocessor.py          # Language detect + spaCy lemmatize + candidate matching
│   │   └── variations.py            # Term variations: acronyms, diacritics, compound splits
│   │
│   ├── llm/                         # Swappable LLM provider layer
│   │   ├── base.py                  # LLMProvider ABC (stream_completion, health_check)
│   │   ├── ollama_provider.py       # Ollama — supports thinking mode (think=True)
│   │   ├── openai_provider.py
│   │   ├── bedrock_provider.py      # AWS Bedrock Converse API
│   │   ├── vertex_provider.py       # Google Vertex AI / Gemini
│   │   └── __init__.py              # get_llm_provider() factory
│   │
│   ├── agents/                      # LangGraph pipeline
│   │   ├── graph.py                 # Graph definition and routing logic
│   │   ├── state.py                 # AgentState TypedDict
│   │   ├── orchestrator.py          # Intent classifier (data vs. chat)
│   │   ├── consultant.py            # EDA consultant — data availability probe
│   │   ├── analyst.py               # Business analyst — reasoning step before SQL
│   │   ├── sql_agent.py             # SQL generation + verify + execute loop
│   │   ├── conversation_agent.py    # General chat fallback
│   │   └── context.py               # Token budget trimming for history
│   │
│   ├── chat/
│   │   └── prompts.py               # All system prompt templates
│   │
│   ├── db/
│   │   ├── connection.py            # asyncpg connection pool
│   │   ├── runner.py                # QueryRunner with statement_timeout
│   │   └── schema_inspector.py      # Structural schema (cached) + data_context.md injection
│   │
│   ├── sql/
│   │   └── verifier.py              # sqlglot AST safety verifier + dynamic table allowlist
│   │
│   └── api/
│       ├── routes/
│       │   ├── chat.py              # POST /chat/stream (SSE)
│       │   ├── eda.py               # GET|POST /eda/* (context, skill, refresh, status)
│       │   ├── tables.py            # GET /tables (onboarding — EDA-derived descriptions)
│       │   └── health.py            # GET /health
│       └── middleware/
│           └── rate_limiter.py      # Stub — see Rate Limiting
│
└── frontend/
    ├── Dockerfile                   # Multi-stage: node build → nginx serve
    ├── package.json
    ├── vite.config.js               # Proxies /chat, /eda, /health to backend in dev
    └── src/
        ├── App.jsx
        ├── i18n.js                  # react-i18next init (English only)
        ├── hooks/useChat.js         # SSE streaming + state management
        └── components/
            ├── OnboardingFlow.jsx   # Onboarding: table selection
            ├── ChatWindow.jsx
            ├── MessageBubble.jsx
            ├── AnalystBlock.jsx     # Collapsible thinking/reasoning display
            ├── SqlBlock.jsx         # Syntax-highlighted SQL + copy button
            ├── ResultTable.jsx      # Query results table
            ├── SuggestionChips.jsx  # Clickable example query chips
            ├── SkillPanel.jsx       # Skill file editor + re-inference UI
            ├── WelcomeCard.jsx      # First-run onboarding card
            ├── ErrorCard.jsx
            ├── InputBar.jsx
            └── ModeToggle.jsx       # Conversational / One-shot toggle
```

---

## Quick Start

### Recommended: use the startup script

```bash
./start.sh              # start
./start.sh --stop       # stop
./start.sh --reset-eda  # wipe data_context.md + skill.md and re-run EDA
```

The script detects your platform and handles everything automatically — see [Platform Notes](#platform-notes).

### Manual startup

**macOS (Apple Silicon):**
```bash
# 1. Start Ollama natively (required for Metal GPU)
brew install ollama && ollama serve &
ollama pull llama3.1:8b

# 2. Start the rest, pointing backend at native Ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434 \
    docker compose up -d postgres backend frontend
```

**Linux (NVIDIA GPU):**
```bash
docker compose -f docker-compose.yml -f docker-compose.nvidia.yml up -d
docker exec qql_ollama ollama pull llama3.1:8b
```

**Linux (CPU-only):**
```bash
docker compose up -d
docker exec qql_ollama ollama pull llama3.1:8b
```

### Rebuilding after code changes

```bash
docker compose up -d --build backend    # rebuild only backend
docker compose up -d --build frontend   # rebuild only frontend
docker compose up -d --build            # rebuild everything
```

> **Tip:** Ollama model data lives in the `ollama_data` Docker volume and is never affected by rebuilds.

### First-run checklist

1. Copy `.env.example` to `.env` and set a strong `QQL_READONLY_PASSWORD`
2. Run `./start.sh`
3. Open **http://localhost:8080**
4. Complete the onboarding (language selection → table selection)
5. EDA will have run automatically at startup — check `data_context.md` to see what was profiled

---

## Platform Notes

### Why Ollama runs differently on macOS

Docker on macOS runs inside a Linux VM and **cannot access the Metal GPU**. Running Ollama inside Docker on Apple Silicon means CPU-only inference (~2–5 tokens/sec for an 8B model).

The startup script solves this by running Ollama as a native macOS process (full Metal GPU acceleration, ~30–50 tokens/sec). Only postgres, backend, and frontend run in Docker.

| Platform | Ollama runs | GPU acceleration |
|----------|-------------|-----------------|
| macOS (Apple Silicon) | Natively (via `start.sh`) | Metal ✓ |
| Linux + NVIDIA | Inside Docker | CUDA ✓ |
| Linux (CPU-only) | Inside Docker | None |

---

## Configuration Reference

All settings are in `.env`, read by `backend/config.py` via Pydantic Settings.

```bash
# ── Database ──────────────────────────────────────────────────────────────────
QQL_READONLY_PASSWORD=         # Password for the read-only DB user (required)

# ── LLM provider ──────────────────────────────────────────────────────────────
LLM_PROVIDER=ollama            # ollama | openai | bedrock | vertex
LLM_MODEL=                     # Universal override — takes priority over provider-specific model

# ── Ollama ────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.1:8b       # Any model pulled in your Ollama instance

# ── OpenAI ────────────────────────────────────────────────────────────────────
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o

# ── AWS Bedrock ───────────────────────────────────────────────────────────────
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

# ── Google Vertex AI ──────────────────────────────────────────────────────────
GCP_PROJECT=
GCP_LOCATION=us-central1
VERTEX_MODEL=gemini-1.5-pro
GOOGLE_APPLICATION_CREDENTIALS=  # Path to service account JSON, or use ADC

# ── Query tuning ──────────────────────────────────────────────────────────────
MAX_QUERY_ROWS=200             # Rows returned before truncation
QUERY_TIMEOUT_SECONDS=30       # PostgreSQL statement_timeout (kills long queries server-side)
MAX_SQL_RETRIES=3              # SQL Agent retry attempts on error

# ── Context window ────────────────────────────────────────────────────────────
MAX_CONTEXT_TOKENS=4096        # Token budget for conversation history
                               # Increase for large-context models, decrease for small/fast ones

# ── EDA agent ─────────────────────────────────────────────────────────────────
EDA_MAX_AGE_HOURS=24           # Hours before data_context.md is considered stale
EDA_TOP_N_VALUES=30            # Max values to list for medium-cardinality text columns
EDA_MAX_NUMERIC_PAIRS=3        # Max cross-column numeric pair analyses
```

---

## Switching LLM Providers

Change one line in `.env` and restart. No code changes needed.

### → Ollama (default)
```bash
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.1:8b   # or qwen3:8b, qwen2.5-coder:7b, deepseek-r1:8b, etc.
```
Models with thinking support (Qwen3, DeepSeek-R1, QwQ) will automatically stream chain-of-thought reasoning to the UI.

### → OpenAI
```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```
Uncomment `openai` in `backend/requirements.txt` and rebuild.

### → AWS Bedrock
```bash
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
```
Uses the [Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html). Uncomment `boto3` in `requirements.txt` and rebuild. In production, prefer IAM roles over static credentials.

### → Google Vertex AI
```bash
LLM_PROVIDER=vertex
GCP_PROJECT=my-project-id
VERTEX_MODEL=gemini-2.0-flash
```
Uncomment `google-cloud-aiplatform` in `requirements.txt` and rebuild. Auth via `GOOGLE_APPLICATION_CREDENTIALS`, `gcloud auth application-default login`, or instance service account.

---

## Adding a New LLM Provider

The `LLMProvider` ABC (`backend/llm/base.py`) defines the contract. Three steps:

**Step 1 — Implement** in `backend/llm/<name>_provider.py`:
```python
from typing import AsyncIterator
from .base import LLMProvider, THINKING_PREFIX

class MyProvider(LLMProvider):
    async def stream_completion(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        think: bool = False,   # ignored unless the provider supports native thinking
    ) -> AsyncIterator[str]:
        # yield text chunks; prefix thinking tokens with THINKING_PREFIX ("\x00")
        ...

    async def health_check(self) -> bool:
        ...
```

**Step 2 — Register** in `backend/llm/__init__.py`:
```python
if settings.llm_provider == "myprovider":
    from .my_provider import MyProvider
    return MyProvider()
```

**Step 3 — Add config** in `backend/config.py` and `.env`.

> **Note on sync SDKs:** boto3 and the Vertex AI SDK are synchronous. Use the thread + asyncio queue pattern from `bedrock_provider.py` to wrap sync streaming in an async generator.

---

## Rate Limiting

`RateLimiterMiddleware` (`backend/api/middleware/rate_limiter.py`) is a stub that passes all requests through. In a production deployment — especially one sold or limited by usage — this should be replaced.

The file includes inline instructions for two drop-in implementations:

- **Redis sliding window** (self-hosted): add Redis to docker-compose, implement in `dispatch()`
- **Upstash** (serverless Redis): zero-infra, follows the Upstash Rate Limit SDK

---

## Development Setup

Run backend and frontend locally with hot reload, without rebuilding Docker images.

**Prerequisites:** Python 3.12+, Node 20+, Docker (for Postgres), Ollama

```bash
# 1. Start only Postgres (and Ollama if on Linux)
docker compose up -d postgres          # macOS (run: ollama serve)
docker compose up -d postgres ollama   # Linux

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
uvicorn main:app --reload --port 8000 --log-config log_config.json

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev   # http://localhost:5173 (proxied to localhost:8000)
```

---

## Known Limitations & Future Work

### Current limitations

**Hallucinations** — The model may generate confident-sounding SQL that is semantically wrong. The retry loop catches syntax errors and execution failures, but cannot detect logically incorrect queries. Showing the raw SQL and results table gives users the means to spot this.

**Reasoning loops** — On rare occasions, especially with smaller models, the agent may enter a loop of retrying the same failed SQL approach. `MAX_SQL_RETRIES` bounds this, but the terminal error message could be more informative about *why* the loop happened.

**Excessive thinking** — Models with native thinking mode (Qwen3, etc.) can sometimes over-reason on simple queries, wasting tokens and time. The `think` parameter can be set to `False` per-agent to disable thinking for specific pipeline stages.

**Incomplete results on text filtering** — Because product identity lives in a free-text column, queries involving product name matching may miss items due to abbreviations or spelling variants not covered by the skill file. Results should be validated by users with domain knowledge.

### Planned improvements

- **Monitoring & tracing** — Sentry / New Relic / LangSmith integration for production observability
- **Guardrails** — Input/output filtering to prevent unintended tool use in production deployments
- **Query kill switch** — A per-session mechanism to cancel in-flight queries beyond `statement_timeout` (currently the timeout is server-side only; there's no way to cancel from the client mid-query)
- **Richer skill system** — Expanding `skill.md` to capture user-defined business rules and query patterns beyond acronym mappings
- **Multi-table support** — Dynamic allowlist already exists (`set_known_tables()`); the EDA and SQL agents would need to handle JOIN reasoning across schemas
