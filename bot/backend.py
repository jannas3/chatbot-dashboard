from __future__ import annotations

import logging
from typing import Any, Mapping

import requests

logger = logging.getLogger(__name__)


def send_screening(url: str, shared_secret: str, payload: Mapping[str, Any]) -> bool:
    try:
        logger.debug("sending_payload", extra={"event": "backend_payload", "payload": payload})
        logger.info(f"Enviando para: {url}")
        logger.debug(f"Secret configurado: {'Sim' if shared_secret else 'Não'}")
        
        response = requests.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-Bot-Secret": shared_secret,
            },
            timeout=6,
        )
        
        logger.info(f"Screening POST status: {response.status_code}")
        
        if not response.ok:
            # Log detalhes do erro de forma mais visível
            try:
                error_body = response.json()
                logger.error(
                    f"❌ Backend retornou erro {response.status_code}: {error_body}"
                )
                logger.error(
                    "Backend retornou erro",
                    extra={
                        "event": "backend_post_error",
                        "status_code": response.status_code,
                        "error": error_body,
                    },
                )
            except:
                error_text = response.text[:500]
                logger.error(
                    f"❌ Backend retornou erro {response.status_code} (sem JSON): {error_text}"
                )
                logger.error(
                    "Backend retornou erro (sem JSON)",
                    extra={
                        "event": "backend_post_error",
                        "status_code": response.status_code,
                        "text": error_text,
                    },
                )
        else:
            logger.info("✅ Triagem enviada com sucesso para o backend")
        
        return response.ok
    except requests.exceptions.ConnectionError as exc:
        logger.error(f"❌ ERRO DE CONEXÃO: Não foi possível conectar ao backend em {url}")
        logger.error(f"   Detalhes: {exc}")
        logger.error(
            "Screening POST failed - Connection Error",
            extra={"event": "backend_post_error", "error": str(exc), "url": url},
        )
        return False
    except requests.exceptions.Timeout as exc:
        logger.error(f"❌ TIMEOUT: O backend demorou mais de 6 segundos para responder")
        logger.error(f"   URL: {url}")
        logger.error(
            "Screening POST failed - Timeout",
            extra={"event": "backend_post_error", "error": str(exc), "url": url},
        )
        return False
    except requests.RequestException as exc:
        logger.error(f"❌ ERRO NA REQUISIÇÃO: {exc}")
        logger.error(f"   URL: {url}")
        logger.error(
            "Screening POST failed",
            extra={"event": "backend_post_error", "error": str(exc), "url": url},
        )
        return False

