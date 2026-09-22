"""Validate support requests and format an email with a stable local reference."""

from datetime import datetime, timezone
import re
from typing import Dict
from uuid import uuid4


def validate_ticket(payload: Dict[str, str]) -> Dict[str, str]:
    """Validate again at the delivery boundary, including email header safety."""
    fields = {}
    for key, label, limit in (
        ("name", "your name", 100), ("email", "a reply email", 254),
        ("subject", "a brief summary", 160), ("description", "a problem description", 4000),
        ("issue", "a related issue", 300),
    ):
        value = payload.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"Please enter {label}.")
        value = value.strip()
        if not value:
            raise ValueError(f"Please enter {label}.")
        if len(value) > limit:
            raise ValueError(f"Please limit {label} to {limit:,} characters.")
        if any(ord(c) < 32 and (key != "description" or c not in "\r\n\t") for c in value):
            raise ValueError(f"Please remove control characters from {label}.")
        fields[key] = value
    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", fields["email"]):
        raise ValueError("Please enter a valid reply email address.")
    return fields


def create_ticket(payload: Dict[str, str], context: Dict[str, str]) -> Dict[str, str]:
    """Create a reference for this request, distinct from any help-desk ticket ID."""
    fields = validate_ticket(payload)
    reference = "KS-" + uuid4().hex[:12].upper()
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    details = "\n".join(f"{key}: {value}" for key, value in context.items())
    return {
        "reference": reference,
        "subject": f"[{reference}] {fields['subject']}",
        "reply_to": fields["email"],
        "body": (
            f"Request reference: {reference}\nCreated (UTC): {timestamp}\n"
            f"Contact: {fields['name']}\nReply email: {fields['email']}\n{details}\n\n"
            f"Related issue: {fields['issue']}\nSummary: {fields['subject']}\n\n"
            f"Problem description:\n{fields['description']}"
        ),
    }
