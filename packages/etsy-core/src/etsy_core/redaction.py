"""F3 secret redaction — the defensive layer that prevents tokens and PII
from leaking through logs, error envelopes, or tool responses.

Named "F3" after the pattern established in godaddy-mcp-context/09-security-notes.md.

Critical rule: every log path, every error envelope, every tool response must
run user-controlled data through redact_sensitive() before emission. This is
defense-in-depth — the primary protection is never logging secrets in the
first place, but when that fails (and it will), redaction catches it.
"""

from __future__ import annotations

from typing import Any

#: Fields that should be redacted in all log output, error responses, and
#: tool envelopes. Expanded beyond godaddy-mcp's set to include OAuth tokens
#: and buyer PII specific to Etsy's transaction data.
#:
#: Additions vs godaddy-mcp:
#: - OAuth: access_token, refresh_token, shared_secret, keystring, client_secret
#: - PII from Etsy receipts: email, first_name, last_name, name
#: - User identifier: etsy_user_id
SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        # OAuth credentials and tokens
        "access_token",
        "refresh_token",
        "shared_secret",
        "keystring",
        "client_secret",
        "client_id",  # not sensitive alone but combined with secret is
        "Authorization",
        "x-api-key",
        # Buyer PII from receipts and transactions
        "email",
        "first_name",
        "last_name",
        "name",
        # User identifiers
        "etsy_user_id",
        "user_id",
        # Legacy from godaddy-mcp — harmless to include
        "authCode",
    }
)

REDACTED_PLACEHOLDER = "[REDACTED — sensitive field]"


def redact_sensitive(data: Any, *, sensitive_fields: frozenset[str] = SENSITIVE_FIELDS) -> Any:
    """Recursively redact sensitive fields from a nested data structure.

    Handles dicts, lists, and tuples. Returns a new structure — does not
    mutate the input. Non-container values are returned as-is.

    Args:
        data: The data to redact (dict, list, tuple, or primitive)
        sensitive_fields: Set of field names to redact. Defaults to SENSITIVE_FIELDS.

    Returns:
        A new structure with sensitive field values replaced by
        REDACTED_PLACEHOLDER. The structure is otherwise identical.

    Example:
        >>> redact_sensitive({"shop_id": 123, "access_token": "secret"})
        {"shop_id": 123, "access_token": "[REDACTED — sensitive field]"}
    """
    if isinstance(data, dict):
        return {
            key: (
                REDACTED_PLACEHOLDER
                if key in sensitive_fields and value is not None
                else redact_sensitive(value, sensitive_fields=sensitive_fields)
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact_sensitive(item, sensitive_fields=sensitive_fields) for item in data]
    if isinstance(data, tuple):
        return tuple(redact_sensitive(item, sensitive_fields=sensitive_fields) for item in data)
    return data


def redact_string(text: str, *, replacements: dict[str, str] | None = None) -> str:
    """Redact known sensitive strings from a free-form text.

    Useful for log messages where the structured data has already been
    flattened to a string (e.g., f-string interpolation of a dict).

    Args:
        text: The string to scan
        replacements: Mapping of sensitive strings to their redacted forms.
            If None, this function is a no-op. Callers should build this
            mapping explicitly from known secrets at call time.

    Returns:
        The string with all sensitive strings replaced.
    """
    if not replacements:
        return text
    for secret, placeholder in replacements.items():
        if secret and secret in text:
            text = text.replace(secret, placeholder)
    return text
