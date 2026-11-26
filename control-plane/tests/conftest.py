import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("INTERNAL_API_TOKEN", "test-token")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
