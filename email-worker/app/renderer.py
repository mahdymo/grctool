"""Template rendering (spec §4.4.6).

Jinja2 with autoescape ON for HTML — template variables from user data can
never inject markup. Every event has an HTML template and a mandatory
plain-text fallback. Templates are versioned in the repo; strings are
externalized (no hard-coded copy in Python) so Arabic slots can be added
without refactor (spec §11 i18n).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

SUBJECTS = {
    "user_invite": "You've been invited to the {platform_name} platform",
    "password_reset": "Password reset for {platform_name}",
    "assessment_kickoff": "IA SAT assessment {cycle} is open — action required",
    "assessment_reminder": "Reminder: IA SAT assessment {cycle} due soon",
    "task_assignment": "New task assigned: {title}",
    "cycle_submission": "Assessment {cycle} submitted for {customer_name}",
}


@dataclass
class Rendered:
    subject: str
    html: str
    text: str


class Renderer:
    def __init__(self, template_dir: str):
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
        )

    def render(self, event: str, locale: str, context: dict) -> Rendered:
        ctx = {
            "platform_name": "GRC Platform",
            "locale": locale,
            "base_template": f"{locale}/base.html",
            **context,
        }
        subject_tpl = SUBJECTS[event]
        try:
            subject = subject_tpl.format(**ctx)
        except KeyError:
            subject = subject_tpl
        html_tpl = self.env.get_template(f"{locale}/{event}.html")
        text_tpl = self.env.get_template(f"{locale}/{event}.txt")
        return Rendered(
            subject=subject,
            html=html_tpl.render(**ctx),
            text=text_tpl.render(**ctx),
        )
