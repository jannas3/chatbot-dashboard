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
        # Timeout reduzido para 20 segundos (era 30)
        response = await asyncio.wait_for(
            asyncio.to_thread(_json_model.generate_content, prompt),
            timeout=20.0
        )
        raw_text = _extract_text(response)
        json_payload = _extract_first_json_block(raw_text)
        return json.loads(json_payload or "{}")
    except asyncio.TimeoutError:
        logger.error("Gemini JSON call timeout após 20 segundos")
        return None
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Gemini JSON call failed: %s", exc)
        return None


async def _invoke_text(prompt: str) -> str:
    if not _text_model:
        return ""
    try:
        # Timeout reduzido para 20 segundos (era 30)
        response = await asyncio.wait_for(
            asyncio.to_thread(
                _text_model.generate_content,
                prompt,
                generation_config={"response_mime_type": "text/plain"},
            ),
            timeout=20.0
        )
        return _extract_text(response).strip()
    except asyncio.TimeoutError:
        logger.error("Gemini text call timeout após 20 segundos")
        return ""
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
    from .instruments import phq9_score, gad7_score, phq9_bucket, gad7_bucket, phq9_item9_flag
    
    # Calcula scores e níveis para dar mais contexto à IA
    phq9_total = phq9_score(phq9_respostas) if phq9_respostas else 0
    gad7_total = gad7_score(gad7_respostas) if gad7_respostas else 0
    phq9_level = phq9_bucket(phq9_total)
    gad7_level = gad7_bucket(gad7_total)
    q9_positive = phq9_item9_flag(phq9_respostas) if phq9_respostas and len(list(phq9_respostas)) >= 9 else False
    
    # Identifica itens mais preocupantes
    phq9_list = list(phq9_respostas)
    gad7_list = list(gad7_respostas)
    phq9_high_items = [f"Q{i+1}({score})" for i, score in enumerate(phq9_list) if score >= 2]
    gad7_high_items = [f"Q{i+1}({score})" for i, score in enumerate(gad7_list) if score >= 2]
    
    prompt = (
        f"{TRIAGE_PROMPT}\n\n"
        f"DADOS PESSOAIS: {dados_pessoais}\n\n"
        f"PHQ-9 (Depressão):\n"
        f"  - Respostas: {phq9_list}\n"
        f"  - Score total: {phq9_total}/27 ({phq9_level})\n"
        f"  - Itens com pontuação ≥2: {', '.join(phq9_high_items) if phq9_high_items else 'Nenhum'}\n"
        f"  - ⚠️ Item 9 (pensamentos de morte/autolesão): {'POSITIVO (≥1) - RISCO CRÍTICO' if q9_positive else 'Negativo'}\n\n"
        f"GAD-7 (Ansiedade):\n"
        f"  - Respostas: {gad7_list}\n"
        f"  - Score total: {gad7_total}/21 ({gad7_level})\n"
        f"  - Itens com pontuação ≥2: {', '.join(gad7_high_items) if gad7_high_items else 'Nenhum'}\n\n"
        f"RELATOS LIVRES (últimas 6 mensagens):\n"
        f"{chr(10).join(f'  - {texto}' for texto in list(texto_livre)[-6:] if texto.strip())}\n\n"
        f"Responda apenas com o JSON especificado, sendo preciso e baseado nos dados fornecidos."
    )
    payload = await _invoke_json(prompt)
    default = TriageOut()
    if payload is None:
        return default
    return safe_parse(TriageOut, payload, default)


async def gen_report_text(contexto: str) -> str:
    prompt = (
        f"{RELATORIO_PROMPT}\n\n"
        f"DADOS DA TRIAGEM (JSON):\n{contexto}\n\n"
        "IMPORTANTE: Substitua todos os {{placeholders}} pelos valores reais dos dados fornecidos acima. "
        "Gere o relatório completo seguindo EXATAMENTE a estrutura especificada, preenchendo todas as seções. "
        "Use os dados do JSON para extrair nome, matrícula, scores, classificações, etc. "
        "Produza apenas o texto do relatório formatado, sem JSON."
    )
    text = await _invoke_text(prompt)
    if not text:
        return (
            "📌 RELATÓRIO DE TRIAGEM — PSICOFLOW\n\n"
            "Triagem registrada. Recomenda-se buscar apoio profissional. "
            "A equipe fará contato o quanto antes."
        )
    # Aumenta limite para relatório completo (até 3000 caracteres)
    return text[:3000]

