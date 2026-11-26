from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://controlplane:change-me@localhost:5432/controlplane"
    redis_url: str = "redis://localhost:6379/0"
    internal_api_token: str = "change-me"
    email_queue_name: str = "email:jobs"
    # Portfolio roll-up: instance registry is DB-backed; this is the poll cadence.
    portfolio_poll_seconds: int = 300
    scheduler_enabled: bool = True

    model_config = {"env_file": ".env"}


settings = Settings()
