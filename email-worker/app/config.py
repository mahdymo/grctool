from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379/0"
    # Either DATABASE_URL directly (tests use sqlite), or DB_* components —
    # components avoid URL-escaping issues with special characters in passwords.
    database_url: str | None = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "emailworker"
    db_user: str = "emailworker"
    db_password: str = "change-me"
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

    def sqlalchemy_url(self):
        if self.database_url:
            return self.database_url
        from sqlalchemy.engine import URL

        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


settings = Settings()
