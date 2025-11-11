from __future__ import annotations

from typing import List, Literal, Sequence, Type, TypeVar

from pydantic import BaseModel, Field, ValidationError, field_validator


EmotionLiteral = Literal["tristeza", "ansiedade", "raiva", "cansaco", "alegria", "neutra"]
UrgencyLiteral = Literal["alta", "media", "baixa"]


class ClassifyOut(BaseModel):
    emocao_principal: EmotionLiteral = "neutra"
    intensidade: int = Field(default=0, ge=0, le=10)
    possivel_crise: bool = False
    resposta_empatica: str = Field(
        default="Obrigado por compartilhar. Estou aqui para te acompanhar passo a passo."
    )

    @field_validator("resposta_empatica")
    @classmethod
    def validate_response_length(cls, value: str) -> str:
        return value.strip()[:600]


class TriageOut(BaseModel):
    nivel_urgencia: UrgencyLiteral = "baixa"
    fatores_protecao: List[str] = Field(default_factory=list)
    impacto_funcional: List[str] = Field(default_factory=list)
    sinais_depressao: List[str] = Field(default_factory=list)
    sinais_ansiedade: List[str] = Field(default_factory=list)

    @field_validator(
        "fatores_protecao",
        "impacto_funcional",
        "sinais_depressao",
        "sinais_ansiedade",
        mode="before",
    )
    @classmethod
    def validate_lists(cls, value: Sequence[str] | None) -> List[str]:
        if not value:
            return []
        clean_items = []
        for item in value:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if item:
                clean_items.append(item[:120])
        return clean_items[:6]


class ReportBundle(BaseModel):
    deterministic_summary: str
    llm_observation: str

    @field_validator("deterministic_summary", "llm_observation")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()


TModel = TypeVar("TModel", bound=BaseModel)


def safe_parse(model: Type[TModel], payload: object, default: TModel) -> TModel:
    try:
        return model.model_validate(payload)
    except ValidationError:
        return default

