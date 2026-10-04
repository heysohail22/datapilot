from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ensure .env is always loaded from backend/ regardless of execution CWD
BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)
load_dotenv(override=True)


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/datapilot"
    GEMINI_API_KEY: str = "placeholder_gemini_key"
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"
    GROQ_API_KEY: str = "placeholder_groq_key"
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = ""

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore")


settings = Settings()