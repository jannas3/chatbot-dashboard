from bot.llm import _extract_first_json_block  # type: ignore[attr-defined]
from bot.models import ClassifyOut, safe_parse


def test_extract_first_json_block_with_fence():
    text = """Algum texto
```json
{"emocao_principal":"tristeza","intensidade":5,"possivel_crise":false,"resposta_empatica":"Oi"}
```
"""
    extracted = _extract_first_json_block(text)
    assert extracted.startswith("{") and extracted.endswith("}")


def test_extract_first_json_block_with_inline_json():
    text = "Resposta: {\"emocao_principal\":\"neutra\",\"intensidade\":0,\"possivel_crise\":false,\"resposta_empatica\":\"Oi\"}"
    extracted = _extract_first_json_block(text)
    assert extracted.startswith("{") and extracted.endswith("}")


def test_safe_parse_returns_default_on_invalid_payload():
    default = ClassifyOut()
    parsed = safe_parse(ClassifyOut, {"emocao_principal": "desconhecida"}, default)
    assert parsed == default


