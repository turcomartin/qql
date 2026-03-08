FROM python:3.12-slim

# Install uv for fast, deterministic dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Install spaCy language models directly (avoids internal pip invocation).
# Versions must match spacy==3.7.4 installed above.
RUN uv pip install --system --no-cache \
    "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl" \
    "https://github.com/explosion/spacy-models/releases/download/es_core_news_sm-3.7.0/es_core_news_sm-3.7.0-py3-none-any.whl"

COPY . .

# Ensure data_context.md exists as a file before the bind-mount kicks in.
# Without this, Docker would create a *directory* at that path if the host
# file doesn't exist yet, which would break the EDA agent's write.
RUN touch /app/data_context.md

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-config", "log_config.json"]
