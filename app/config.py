from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLMs
    groq_api_key: str = ""
    google_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    freetoken_base_url: str = "http://localhost:1919"

    primary_llm: Literal["groq", "gemini", "ollama", "openrouter", "freetoken"] = "groq"
    fallback_llm: Literal["groq", "gemini", "ollama", "openrouter", "freetoken"] = "ollama"
    long_context_llm: Literal["groq", "gemini", "ollama", "openrouter", "freetoken"] = "gemini"

    groq_model: str = "llama-3.3-70b-versatile"
    gemini_model: str = "gemini-2.5-flash"
    ollama_model: str = "llama3.1:8b"
    freetoken_model: str = "Qwen3.6-35B-A3B-NVFP4"

    # Datos US
    finnhub_api_key: str = ""
    fmp_api_key: str = ""
    alpha_vantage_key: str = ""

    # Crypto
    coingecko_api_key: str = ""

    # Sentimiento
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "StockBot/1.0"

    # DB
    database_url: str = "sqlite:///./stockbot.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # App
    secret_key: str = "cambia-esto-en-produccion"
    debug: bool = True
    log_level: str = "INFO"
    fastapi_port: int = 8000
    streamlit_port: int = 8501

    # SEC EDGAR
    sec_identity_name: str = "StockBot"
    sec_identity_email: str = ""


settings = Settings()
