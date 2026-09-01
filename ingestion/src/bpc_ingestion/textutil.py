from __future__ import annotations

from typing import Any

from ftfy import fix_text


def repair_text(value: Any) -> Any:
    """Corrige mojibake conhecido sem alterar valores que nao sejam texto."""
    return fix_text(value) if isinstance(value, str) else value
