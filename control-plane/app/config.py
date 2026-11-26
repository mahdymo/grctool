from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Either set DATABASE_URL directly (tests use sqlite), or set the DB_*
    # components — components avoid URL-escaping issues with special
    # characters in passwords.
    database_url: str | None = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "controlplane"
    db_user: str = "controlplane"
    db_password: str = "change-me"
    redis_url: str = "redis://localhost:6379/0"
    internal_api_token: str = "change-me"
    email_queue_name: str = "email:jobs"
    # Portfolio roll-up: instance registry is DB-backed; this is the poll cadence.
    portfolio_poll_seconds: int = 300
    scheduler_enabled: bool = True

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
