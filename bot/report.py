from __future__ import annotations

from typing import Mapping, Sequence

from .instruments import (
    GAD7_QUESTIONS,
    PHQ9_QUESTIONS,
    gad7_bucket,
    gad7_score,
    phq9_bucket,
    phq9_score,
)


def build_deterministic_summary(
    nome: str,
    phq9_answers: Sequence[int],
    gad7_answers: Sequence[int],
    disponibilidade: str,
    observacao: str,
    free_text: Sequence[str] | None = None,
    triage: Mapping[str, object] | None = None,
) -> str:
    phq9_score_value = phq9_score(phq9_answers) if phq9_answers else 0
    gad7_score_value = gad7_score(gad7_answers) if gad7_answers else 0
    phq9_label = phq9_bucket(phq9_score_value)
    gad7_label = gad7_bucket(gad7_score_value)

    def _strip_prompt(question: str) -> str:
        return question.split(" ", 1)[1] if " " in question else question

    def _format_items(questions: Sequence[str], answers: Sequence[int]) -> str:
        if not answers:
            return "  (instrumento não respondido)"
        lines = []
        for idx, (question, score) in enumerate(zip(questions, answers), start=1):
            lines.append(f"  - Q{idx}: {score} | {_strip_prompt(question)}")
        return "\n".join(lines)

    phq9_items = _format_items(PHQ9_QUESTIONS, phq9_answers)
    gad7_items = _format_items(GAD7_QUESTIONS, gad7_answers)

    top_phq9_score = max(phq9_answers) if phq9_answers else -1
    top_gad7_score = max(gad7_answers) if gad7_answers else -1
    if top_phq9_score <= 0 and top_gad7_score <= 0:
        top_item_text = "Nenhum item pontuou acima de 0."
    else:
        if top_phq9_score >= top_gad7_score:
            idx = phq9_answers.index(top_phq9_score)
            question = _strip_prompt(PHQ9_QUESTIONS[idx])
            top_item_text = f"PHQ-9 Q{idx + 1}: {question} (pontuação {top_phq9_score})"
        else:
            idx = gad7_answers.index(top_gad7_score)
            question = _strip_prompt(GAD7_QUESTIONS[idx])
            top_item_text = f"GAD-7 Q{idx + 1}: {question} (pontuação {top_gad7_score})"

    parts = [
        f"Triagem de {nome}:",
        f"- PHQ-9 total: {phq9_score_value} ({phq9_label})",
        "  Detalhe por item:",
        phq9_items,
        f"- GAD-7 total: {gad7_score_value} ({gad7_label})",
        "  Detalhe por item:",
        gad7_items,
        f"- Item mais preocupante: {top_item_text}",
        f"- Disponibilidade: {disponibilidade or 'Não informada'}",
    ]
    if observacao:
        parts.append(f"- Observação: {observacao}")
    if free_text:
        relatos = [texto.strip() for texto in free_text if texto.strip()]
        if relatos:
            parts.append("- Relatos livres do aluno (mais recentes):")
            for snippet in relatos[-5:]:
                trecho = snippet.strip()
                if len(trecho) > 200:
                    trecho = trecho[:200].rstrip() + "…"
                parts.append(f"    • {trecho}")
    if triage:
        depressao = [str(item).strip() for item in triage.get("sinais_depressao", []) if str(item).strip()]
        ansiedade = [str(item).strip() for item in triage.get("sinais_ansiedade", []) if str(item).strip()]
        impacto = [str(item).strip() for item in triage.get("impacto_funcional", []) if str(item).strip()]
        protecao = [str(item).strip() for item in triage.get("fatores_protecao", []) if str(item).strip()]

        resumo_parts: list[str] = []
        if depressao:
            resumo_parts.append(f"sinais de humor como {', '.join(depressao[:3])}")
        if ansiedade:
            resumo_parts.append(f"sinais de ansiedade como {', '.join(ansiedade[:3])}")
        if impacto:
            resumo_parts.append(f"impactos no dia a dia ({', '.join(impacto[:2])})")
        if protecao:
            resumo_parts.append(f"e fatores de proteção percebidos ({', '.join(protecao[:2])})")

        if resumo_parts:
            resumo_texto = "; ".join(resumo_parts[:-1]) + (" " if len(resumo_parts) > 1 else "")
            resumo_texto += resumo_parts[-1]
            insight_text = (
                "A análise automática identificou "
                f"{resumo_texto}. Recomendamos acolhimento próximo e acompanhamento profissional."
            )
            parts.append("- Insight IA sobre o relato livre:")
            parts.append(f"    • {insight_text}")
    return "\n".join(parts)


def compose_report_text(deterministic_summary: str, llm_text: str) -> str:
    deterministic = deterministic_summary.strip() or "Resumo indisponível."
    if len(deterministic) > 2000:
        deterministic = deterministic[:1997].rstrip() + "..."
    return deterministic


