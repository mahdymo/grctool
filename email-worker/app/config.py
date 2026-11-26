from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql://emailworker:change-me@localhost:5432/emailworker"
    resend_api_key: str = ""
    resend_webhook_secret: str = ""
    resend_api_url: str = "https://api.resend.com"
    email_from_default: str = "GRC Platform <notifications@example.com>"
    # Phase 0 events (spec §4.3); digest/escalation are Phase 1
    queue_name: str = "email:jobs"
    dead_letter_queue: str = "email:dead"
    max_attempts: int = 5
    template_dir: str = "templates"

    model_config = {"env_file": ".env"}


settings = Settings()
