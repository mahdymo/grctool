import pytest

from app.jobs import idempotency_key, validate_job
from app.renderer import Renderer

CONTEXT = {
    "recipient_name": "Alice",
    "role": "Control Owner",
    "customer_name": "Gulf Coverage",
    "invite_url": "https://example.com/invite?token=abc",
}


def test_renderer_escapes_user_data_in_html():
    renderer = Renderer("templates")
    malicious = {**CONTEXT, "recipient_name": '<script>alert(1)</script>'}
    rendered = renderer.render("user_invite", "en", malicious)
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html
    # plain-text fallback keeps the raw value (no markup context)
    assert "<script>" in rendered.text


def test_renderer_produces_subject_and_text_fallback():
    renderer = Renderer("templates")
    rendered = renderer.render("user_invite", "en", CONTEXT)
    assert rendered.subject
    assert rendered.text.strip()
    assert "Gulf Coverage" in rendered.text


def test_strict_undefined_rejects_missing_variables():
    renderer = Renderer("templates")
    with pytest.raises(Exception):
        renderer.render("user_invite", "en", {})


def test_idempotency_key_stable_per_event_entity_recipient_day():
    job = {"event": "task_assignment", "to": "Owner@Example.com", "entity_id": "REM-014"}
    assert idempotency_key(job) == idempotency_key(dict(job))
    other = {**job, "entity_id": "REM-015"}
    assert idempotency_key(job) != idempotency_key(other)


def test_validate_job_rejects_unknown_event():
    with pytest.raises(ValueError):
        validate_job({"event": "marketing_blast", "to": "x@example.com"})
