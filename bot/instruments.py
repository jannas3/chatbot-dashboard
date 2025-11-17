from __future__ import annotations

from typing import Iterable, Sequence

PHQ9_QUESTIONS = [
    "1. Pouco interesse ou prazer em fazer as coisas?",
    "2. Sentir-se para baixo, deprimido(a) ou sem esperança?",
    "3. Dificuldade para dormir, dormir demais ou dormir mal?",
    "4. Sentir-se cansado(a) ou com pouca energia?",
    "5. Falta de apetite ou comer em excesso?",
    "6. Sentir-se mal consigo mesmo(a) ou que é um fracasso?",
    "7. Dificuldade de concentração, como ao ler ou assistir TV?",
    "8. Mover-se ou falar muito devagar, ou estar muito agitado(a)?",
    "9. Pensamentos de que seria melhor estar morto(a) ou se machucar?",
]

GAD7_QUESTIONS = [
    "1. Sentir-se nervoso(a), ansioso(a) ou tenso(a)?",
    "2. Não conseguir parar ou controlar a preocupação?",
    "3. Preocupar-se excessivamente com diferentes coisas?",
    "4. Dificuldade em relaxar?",
    "5. Estar tão inquieto(a) que é difícil ficar parado(a)?",
    "6. Ficar facilmente irritado(a) ou aborrecido(a)?",
    "7. Sentir medo como se algo horrível fosse acontecer?",
]

VALID_SCALE = {"0", "1", "2", "3"}


PHQ9_BUCKETS = {
    range(0, 5): "Mínima",  # 0-4: Depressão mínima
    range(5, 10): "Leve",   # 5-9: Leve
    range(10, 15): "Moderada",  # 10-14: Moderada
    range(15, 20): "Moderadamente grave",  # 15-19: Moderadamente grave
    range(20, 28): "Grave",  # 20-27: Grave
}

GAD7_BUCKETS = {
    range(0, 5): "Mínima",
    range(5, 10): "Leve",
    range(10, 15): "Moderada",
    range(15, 22): "Grave",
}


def is_valid_scale_answer(answer: str | None) -> bool:
    return (answer or "").strip() in VALID_SCALE


def parse_scale_answer(answer: str | None) -> int | None:
    clean = (answer or "").strip()
    return int(clean) if clean in VALID_SCALE else None


def _score(responses: Sequence[int], expected_len: int) -> int:
    if len(responses) != expected_len:
        raise ValueError(f"Esperado {expected_len} respostas, recebido {len(responses)}.")
    if any(r not in {0, 1, 2, 3} for r in responses):
        raise ValueError("Respostas devem estar entre 0 e 3.")
    return sum(responses)


def phq9_score(responses: Sequence[int]) -> int:
    return _score(responses, len(PHQ9_QUESTIONS))


def gad7_score(responses: Sequence[int]) -> int:
    return _score(responses, len(GAD7_QUESTIONS))


def phq9_bucket(score: int) -> str:
    for bucket_range, label in PHQ9_BUCKETS.items():
        if score in bucket_range:
            return label
    raise ValueError("Pontuação PHQ-9 fora da faixa permitida (0-27).")


def gad7_bucket(score: int) -> str:
    for bucket_range, label in GAD7_BUCKETS.items():
        if score in bucket_range:
            return label
    raise ValueError("Pontuação GAD-7 fora da faixa permitida (0-21).")


def phq9_item9_flag(responses: Sequence[int]) -> bool:
    if len(responses) < len(PHQ9_QUESTIONS):
        raise ValueError("PHQ-9 incompleto.")
    return responses[8] >= 1


def to_int_list(responses: Iterable[str | int]) -> list[int]:
    output: list[int] = []
    for resp in responses:
        if isinstance(resp, int):
            value = resp
        else:
            parsed = parse_scale_answer(str(resp))
            if parsed is None:
                raise ValueError(f"Resposta inválida: {resp}")
            value = parsed
        output.append(value)
    return output


