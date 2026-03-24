from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    project_name: str = "AI Chat Prototype Starter"
    openai_api_key: str = ""
    # Optional explicitly provided service account JSON or default GCP Application Default Credentials
    google_application_credentials: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
