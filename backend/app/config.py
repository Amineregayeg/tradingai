from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-secret-key"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://tradingai:tradingai@localhost:5432/tradingai"
    redis_url: str = "redis://localhost:6379/0"

    oanda_api_key: str = ""
    oanda_account_id: str = ""
    oanda_environment: str = "practice"

    anthropic_api_key: str = ""
    ai_primary_model: str = "claude-sonnet-4-6"
    ai_screening_model: str = "claude-haiku-4-5"
    ai_monthly_budget_usd: float = 30.0

    finnhub_api_key: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    data_dir: str = "/data"


settings = Settings()
