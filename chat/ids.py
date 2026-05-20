"""Public conversation identifiers exposed in URLs."""
from __future__ import annotations

import secrets
import string

_PUBLIC_ID_ALPHABET = string.ascii_letters + string.digits
_PUBLIC_ID_LENGTH = 16


def generate_public_id() -> str:
    return "".join(
        secrets.choice(_PUBLIC_ID_ALPHABET) for _ in range(_PUBLIC_ID_LENGTH)
    )


def assign_unique_public_id(conversation) -> None:
    if conversation.public_id:
        return
    from .models import Conversation

    for _ in range(32):
        candidate = generate_public_id()
        if not Conversation.objects.filter(public_id=candidate).exists():
            conversation.public_id = candidate
            return
    raise RuntimeError("Could not allocate a unique conversation public_id")
