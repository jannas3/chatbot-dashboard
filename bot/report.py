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
    phq9_item9_positive: bool = False,
) -> str:
    phq9_score_value = phq9_score(phq9_answers) if phq9_answers else 0
    gad7_score_value = gad7_score(gad7_answers) if gad7_answers else 0
    phq9_label = phq9_bucket(phq9_score_value)
    gad7_label = gad7_bucket(gad7_score_value)

    def _strip_prompt(question: str) -> str:
        return question.split(" ", 1)[1] if " " in question else question

    # Determina item mais preocupante
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

    # Relatório enxuto - informações essenciais + análise IA
    parts = [
        f"Triagem de {nome}:",
        f"PHQ-9: {phq9_score_value} pontos ({phq9_label})",
        f"GAD-7: {gad7_score_value} pontos ({gad7_label})",
        f"Item mais preocupante: {top_item_text}",
        f"Disponibilidade: {disponibilidade or 'Não informada'}",
    ]
    
    if observacao:
        parts.append(f"Observação: {observacao}")
    
    # Análise IA da Triagem
    if triage:
        nivel_urgencia = str(triage.get("nivel_urgencia", "")).strip().lower()
        depressao = [str(item).strip() for item in triage.get("sinais_depressao", []) if str(item).strip()]
        ansiedade = [str(item).strip() for item in triage.get("sinais_ansiedade", []) if str(item).strip()]
        impacto = [str(item).strip() for item in triage.get("impacto_funcional", []) if str(item).strip()]
        protecao = [str(item).strip() for item in triage.get("fatores_protecao", []) if str(item).strip()]

        parts.append("\nAnálise IA:")
        
        # Nível de urgência
        if nivel_urgencia:
            urgencia_emoji = "🔴" if nivel_urgencia == "alta" else "🟡" if nivel_urgencia == "media" else "🟢"
            urgencia_texto = nivel_urgencia.upper()
            parts.append(f"  {urgencia_emoji} Nível de urgência: {urgencia_texto}")
        
        # Sinais identificados
        if depressao or ansiedade:
            parts.append("  📊 Sinais identificados:")
            if depressao:
                parts.append(f"    • Depressão: {', '.join(depressao[:4])}")
            if ansiedade:
                parts.append(f"    • Ansiedade: {', '.join(ansiedade[:4])}")
        
        # Impacto funcional
        if impacto:
            parts.append("  ⚠️ Impacto funcional:")
            for item in impacto[:4]:
                parts.append(f"    • {item}")
        
        # Fatores de proteção
        if protecao:
            parts.append("  💚 Fatores de proteção:")
            for item in protecao[:4]:
                parts.append(f"    • {item}")
        
        # Recomendação baseada na análise
        if depressao or ansiedade or impacto:
            parts.append("  💡 Recomendação: Acolhimento próximo e acompanhamento profissional recomendado.")
    
    return "\n".join(parts)


def compose_report_text(deterministic_summary: str, llm_text: str) -> str:
    # Se o relatório da IA foi gerado com sucesso e está completo, usa ele
    if llm_text and llm_text.strip() and len(llm_text.strip()) > 100:
        return llm_text.strip()
    
    # Caso contrário, usa o resumo determinístico como fallback
    deterministic = deterministic_summary.strip() or "Resumo indisponível."
    if len(deterministic) > 2000:
        deterministic = deterministic[:1997].rstrip() + "..."
    return deterministic


