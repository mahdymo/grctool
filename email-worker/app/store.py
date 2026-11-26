"""Persistence: send log (idempotency), suppressions, dead letters.

All state lives in the emailworker Postgres database — the worker is the
only writer. Audit-friendly: rows are append-only except suppression review
flags (spec §4.4.4).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    update,
)

metadata = MetaData()

send_log = Table(
    "send_log",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("idempotency_key", String(255), unique=True, nullable=False, index=True),
    Column("event", String(64), nullable=False),
    Column("recipient", String(320), nullable=False),
    Column("entity_id", String(128)),
    Column("resend_email_id", String(128)),
    Column("status", String(32), nullable=False),  # sent / failed / suppressed / duplicate
    Column("created_at", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
)

suppressions = Table(
    "suppressions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(320), unique=True, nullable=False, index=True),
    Column("reason", String(32), nullable=False),  # bounced / complained
    Column("reviewed", Boolean, default=False),
    Column("created_at", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
)

dead_letters = Table(
    "dead_letters",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("job_json", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("last_error", Text),
    Column("created_at", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
)


class Store:
    def __init__(self, database_url):
        self.engine = create_engine(database_url, pool_pre_ping=True)
        metadata.create_all(self.engine)

    def already_sent(self, key: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(send_log.c.id).where(send_log.c.idempotency_key == key)
            ).first()
        return row is not None

    def is_suppressed(self, email: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(suppressions.c.id).where(
                    suppressions.c.email == email.lower(),
                    suppressions.c.reviewed.is_(False),
                )
            ).first()
        return row is not None

    def record_send(self, key: str, event: str, recipient: str, entity_id: str | None,
                    resend_email_id: str | None, status: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                insert(send_log).values(
                    idempotency_key=key,
                    event=event,
                    recipient=recipient.lower(),
                    entity_id=entity_id,
                    resend_email_id=resend_email_id,
                    status=status,
                )
            )

    def suppress(self, email: str, reason: str) -> None:
        with self.engine.begin() as conn:
            exists = conn.execute(
                select(suppressions.c.id).where(suppressions.c.email == email.lower())
            ).first()
            if not exists:
                conn.execute(
                    insert(suppressions).values(email=email.lower(), reason=reason)
                )

    def dead_letter(self, job_json: str, attempts: int, last_error: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                insert(dead_letters).values(
                    job_json=job_json, attempts=attempts, last_error=last_error
                )
            )
