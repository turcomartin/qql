from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database
    db_dsn: str = (
        "postgresql://qql_readonly:someStrongProdPassword@localhost:5435/qql_db"
    )
    max_query_rows: int = 200
    query_timeout_seconds: int = 30

    # LLM provider selector — set in .env to swap providers
    llm_provider: Literal["ollama", "openai", "bedrock", "vertex"] = "ollama"

    # Universal model selector — overrides whichever provider is active.
    # Set LLM_MODEL=llama3.2:3b to switch Ollama models, or to any model ID
    # supported by the active provider (e.g. gemini-2.0-flash for Vertex).
    llm_model: str = ""

    # Ollama
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1:8b"  # fallback when llm_model is unset

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"  # fallback when llm_model is unset

    # AWS Bedrock — requires: pip install boto3
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"  # fallback

    # Google Vertex AI — requires: pip install google-cloud-aiplatform
    gcp_project: str = ""
    gcp_location: str = "us-central1"
    vertex_model: str = "gemini-1.5-pro"  # fallback when llm_model is unset

    # Agent / context
    max_sql_retries: int = 3
    max_context_tokens: int = 4096

    # CORS — comma-separated string, e.g. "http://localhost:5173,http://localhost:8080"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # EDA agent
    eda_context_path: str = "/app/data_context.md"
    eda_max_age_hours: int = 24
    skill_path: str = "/app/skill.md"
    eda_top_n_values: int = 30  # max values for medium-cardinality text columns
    eda_max_numeric_pairs: int = 3  # max numeric column pairs to cross-analyze

    # Model used exclusively for EDA skill / acronym inference.
    # Set to a fast local model (e.g. qwen3:8b) so skill inference doesn't
    # compete with the main chat model.  Uses Ollama regardless of the active
    # LLM_PROVIDER.  Leave blank to fall back to the globally active model.
    eda_skill_model: str = "qwen3:8b"

    @property
    def active_model(self) -> str:
        """The model ID actually in use: LLM_MODEL override, or the provider-specific default."""
        if self.llm_model:
            return self.llm_model
        return {
            "ollama": self.ollama_model,
            "openai": self.openai_model,
            "bedrock": self.bedrock_model_id,
            "vertex": self.vertex_model,
        }.get(self.llm_provider, self.ollama_model)


settings = Settings()
