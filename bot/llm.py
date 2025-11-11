from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, Iterable, Optional

import google.generativeai as genai

from .config import get_settings
from .models import ClassifyOut, TriageOut, safe_parse
from .prompts import CLASSIFY_PROMPT, RELATORIO_PROMPT, TRIAGE_PROMPT

logger = logging.getLogger(__name__)

_settings = get_settings()

if _settings.gemini_api_key:
    genai.configure(api_key=_settings.gemini_api_key)
    _json_model = genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json"},
    )
    _text_model = genai.GenerativeModel("gemini-2.5-flash")
else:
    logger.warning("Gemini API key ausente; utilizando apenas fallbacks seguros.")
    _json_model = None
    _text_model = None

JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def _extract_text(response: Any) -> str:
    if response is None:
        return ""
    if hasattr(response, "text") and response.text:
        return str(response.text)
    if hasattr(response, "candidates"):
        for candidate in response.candidates or []:
            parts = getattr(candidate, "content", getattr(candidate, "parts", None))
            if parts:
                try:
                    return "".join(getattr(part, "text", str(part)) for part in parts)
                except TypeError:
                    continue
    return str(response)


def _extract_first_json_block(text: str) -> str:
    if not text:
        return "{}"
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)
    match = JSON_BLOCK_PATTERN.search(text)
    if match:
        return match.group(0)
    return "{}"


async def _invoke_json(prompt: str) -> Optional[Dict[str, Any]]:
    if not _json_model:
        return None
    try:
        response = await asyncio.to_thread(_json_model.generate_content, prompt)
        raw_text = _extract_text(response)
        json_payload = _extract_first_json_block(raw_text)
        return json.loads(json_payload or "{}")
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Gemini JSON call failed: %s", exc)
        return None


async def _invoke_text(prompt: str) -> str:
    if not _text_model:
        return ""
    try:
        response = await asyncio.to_thread(
            _text_model.generate_content,
            prompt,
            generation_config={"response_mime_type": "text/plain"},
        )
        return _extract_text(response).strip()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Gemini text call failed: %s", exc)
        return ""


async def classify_msg(message: str, history: Iterable[str]) -> ClassifyOut:
    prompt = (
        f"{CLASSIFY_PROMPT}\n\n"
        f"Histórico recente: {list(history)[-6:]}\n"
        f"Mensagem atual: {message}\n"
        "Responda apenas com o JSON especificado."
    )
    payload = await _invoke_json(prompt)
    default = ClassifyOut()
    if payload is None:
        return default
    return safe_parse(ClassifyOut, payload, default)


async def triage_summary(
    dados_pessoais: Dict[str, str],
    phq9_respostas: Iterable[int],
    gad7_respostas: Iterable[int],
    texto_livre: Iterable[str],
) -> TriageOut:
    prompt = (
        f"{TRIAGE_PROMPT}\n\n"
        f"DADOS: {dados_pessoais}\n"
        f"PHQ9: {list(phq9_respostas)}\n"
        f"GAD7: {list(gad7_respostas)}\n"
        f"RELATO: {list(texto_livre)[-6:]}\n"
        "Responda apenas com o JSON especificado."
    )
    payload = await _invoke_json(prompt)
    default = TriageOut()
    if payload is None:
        return default
    return safe_parse(TriageOut, payload, default)


async def gen_report_text(contexto: str) -> str:
    prompt = (
        f"{RELATORIO_PROMPT}\n\n"
        f"Contexto estruturado:\n{contexto}\n"
        "Produza apenas o texto solicitado, sem JSON."
    )
    text = await _invoke_text(prompt)
    if not text:
        return (
            "Triagem registrada. Recomenda-se buscar apoio profissional. "
            "A equipe fará contato o quanto antes."
        )
    return text[:1200]

