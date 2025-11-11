from __future__ import annotations

import logging
from typing import Any, Mapping

import requests

logger = logging.getLogger(__name__)


def send_screening(url: str, shared_secret: str, payload: Mapping[str, Any]) -> bool:
    try:
        logger.debug("sending_payload", extra={"event": "backend_payload", "payload": payload})
        response = requests.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-Bot-Secret": shared_secret,
            },
            timeout=6,
        )
        logger.info(
            "Screening POST status",
            extra={"event": "backend_post", "status_code": response.status_code},
        )
        return response.ok
    except requests.RequestException as exc:
        logger.error("Screening POST failed", extra={"event": "backend_post_error", "error": str(exc)})
        return False

