from __future__ import annotations

import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)

RISK_PATTERNS: tuple[str, ...] = (
    r"morrer",
    r"morte",
    r"me\s*matar",
    r"tirar\s*a\s*vida",
    r"sem\s*vontade\s*de\s*viver",
    r"suicid",
    r"autoagress",
)

risk_regex = re.compile("|".join(RISK_PATTERNS), re.IGNORECASE)


def has_crisis_terms(message: str | None) -> bool:
    if not message:
        return False
    return bool(risk_regex.search(message))


def crisis_gate(message: str | None, llm_flag: bool) -> bool:
    triggered = has_crisis_terms(message) or bool(llm_flag)
    if triggered:
        logger.warning("crisis_gate triggered", extra={"event": "crisis", "llm_flag": llm_flag})
    return triggered


def any_crisis(messages: Iterable[str], llm_flag: bool = False) -> bool:
    return any(has_crisis_terms(msg) for msg in messages) or llm_flag


