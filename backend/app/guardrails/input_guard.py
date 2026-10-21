"""Fast deterministic input checks; do not block ordinary business vocabulary."""

import re
import unicodedata
from pydantic import BaseModel


class GuardrailOutcome(BaseModel):
    is_safe: bool
    sanitized_text: str
    rejection_reason: str | None = None


RULES = [
    r"<\s*/?\s*(?:system|developer|instruction|admin_override)\s*>",
    r"\b(?:ignore|bypass|override|disregard)\b.{0,100}\b(?:instructions|guardrails|system prompt)\b",
    r"\b(?:act as|you are now|pretend to be)\b.{0,80}\b(?:DAN|root|unrestricted|bash|jailbreak)\b",
    r"(?:\.env\b|\b(?:DATABASE_URL|GEMINI_API_KEY|GROQ_API_KEY|LLM_API_KEY|AWS_SECRET_ACCESS_KEY|service_role)\b)",
    r";\s*(?:DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE)\b",
    r"\b(?:reveal|print|show|dump)\b.{0,80}\b(?:system prompt|password|credentials|api keys?|secrets)\b",
    r"\b(?:sudo|rm\s+-rf|/bin/bash|/bin/sh)\b",
    r"\b(?:decode|base64)\b.{0,80}\b(?:execute|run)\b",
]
PATTERN = re.compile("|".join(RULES), re.IGNORECASE | re.DOTALL)


def sanitize_user_input(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKC", text) if c.isprintable() or c in "\n\t"
    ).strip()


def sanitize_and_validate_input(text: str) -> GuardrailOutcome:
    cleaned = sanitize_user_input(text) if isinstance(text, str) else ""
    safe = bool(cleaned) and len(cleaned) <= 4000 and PATTERN.search(cleaned) is None
    return GuardrailOutcome(
        is_safe=safe,
        sanitized_text=cleaned,
        rejection_reason=None
        if safe
        else "Please ask a business question without system commands or requests for secrets.",
    )
