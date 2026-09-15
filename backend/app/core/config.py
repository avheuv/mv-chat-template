from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    project_name: str = "AI Chat Prototype Starter"
    openai_api_key: str = ""
    turning_test_openai_model: str = "gpt-4o-mini"
    pangram_api_key: str = ""
    pangram_api_base_url: str = "https://text.api.pangram.com/v1"
    # Explicitly configure a model granted to your Pangram account (for example, pangram-v4).
    pangram_model: str = ""
    turning_test_evaluation_min_words: int = 50
    # Optional explicitly provided service account JSON or default GCP Application Default Credentials
    google_application_credentials: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
