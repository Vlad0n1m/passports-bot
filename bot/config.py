from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8")

    bot_token: str
    openrouter_api_key: str
    openrouter_model: str = "google/gemini-2.5-flash"
    google_service_account_file: str = str(PROJECT_ROOT / "service_account.json")
    google_spreadsheet_id: str = ""


settings = Settings()
