from config import settings
from .base import LLMProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider


def get_llm_provider() -> LLMProvider:
    """
    Factory: returns the active LLM provider.
    Switch providers by setting LLM_PROVIDER in .env.

    Supported values:
      ollama   — local Ollama server (default, bundled via Docker or native)
      openai   — OpenAI API (requires OPENAI_API_KEY)
      bedrock  — AWS Bedrock Converse API (requires boto3 + AWS credentials)
      vertex   — Google Vertex AI / Gemini (requires google-cloud-aiplatform + GCP credentials)
    """
    if settings.llm_provider == "ollama":
        return OllamaProvider()
    if settings.llm_provider == "openai":
        return OpenAIProvider()
    if settings.llm_provider == "bedrock":
        from .bedrock_provider import BedrockProvider
        return BedrockProvider()
    if settings.llm_provider == "vertex":
        from .vertex_provider import VertexProvider
        return VertexProvider()
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")


def get_skill_llm_provider() -> LLMProvider:
    """
    Returns the LLM provider for EDA skill / acronym inference.

    If EDA_SKILL_MODEL is set in .env (default: ``qwen3:8b``), always uses
    a local Ollama instance with that model — fast structured extraction
    without competing with the main chat model.

    If EDA_SKILL_MODEL is blank, falls back to the globally active provider
    (whatever LLM_PROVIDER + LLM_MODEL are configured).
    """
    if settings.eda_skill_model:
        return OllamaProvider(model=settings.eda_skill_model)
    return get_llm_provider()
