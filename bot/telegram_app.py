from __future__ import annotations

import logging
import json
from dataclasses import dataclass, field
from typing import Dict, List

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    Defaults,
    MessageHandler,
    filters,
)

from .backend import send_screening
from .config import Settings, get_settings
from .instruments import (
    GAD7_QUESTIONS,
    PHQ9_QUESTIONS,
    gad7_score,
    phq9_item9_flag,
    phq9_score,
)
from .llm import classify_msg, gen_report_text, triage_summary
from .report import build_deterministic_summary, compose_report_text
from .safety import crisis_gate
from .states import ConversationState

logger = logging.getLogger(__name__)

GREETINGS = {
    "oi",
    "olá",
    "ola",
    "hello",
    "hi",
    "hey",
    "bom dia",
    "boa tarde",
    "boa noite",
}

CRISIS_MESSAGE = (
    "⚠️ Sua segurança é prioridade.\n"
    "Se houver risco imediato, ligue 188 (CVV) ou 192 (SAMU) agora.\n"
    "Vou sinalizar sua mensagem para a equipe."
)

SCALE_INTRO = (
    "📝 Responda usando a escala:\n"
    "0 — Nunca | 1 — Vários dias | 2 — Mais da metade dos dias | 3 — Quase todos os dias\n\n"
)

SCALE_KEYBOARD = ReplyKeyboardMarkup([["0", "1", "2", "3"]], one_time_keyboard=True, resize_keyboard=True)

PERSONAL_FIELDS = [
    ("nome", "Qual seu nome completo?"),
    ("idade", "Qual sua idade?"),
    ("matricula", "Informe sua matrícula."),
    ("curso", "Qual o seu curso?"),
    ("periodo", "Qual o período/semestre atual?"),
]


@dataclass
class SessionData:
    user_id: int
    personal_data: Dict[str, str] = field(default_factory=dict)
    phq9_answers: List[int] = field(default_factory=list)
    phq9_item9_positive: bool = False
    gad7_answers: List[int] = field(default_factory=list)
    availability: str = ""
    observation: str = ""
    free_text: List[str] = field(default_factory=list)
    history: List[str] = field(default_factory=list)
    triage_result: Dict[str, object] = field(default_factory=dict)
    phq9_started: bool = False
    triage_active: bool = False

    def next_personal_field(self) -> tuple[str, str] | None:
        for key, question in PERSONAL_FIELDS:
            if key not in self.personal_data:
                return key, question
        return None


def _get_session(context: CallbackContext, user_id: int) -> SessionData:
    session = context.user_data.get("session")
    if isinstance(session, SessionData):
        return session
    session = SessionData(user_id=user_id)
    context.user_data["session"] = session
    return session


def _reset_session(session: SessionData) -> None:
    session.personal_data.clear()
    session.phq9_answers.clear()
    session.phq9_item9_positive = False
    session.gad7_answers.clear()
    session.availability = ""
    session.observation = ""
    session.free_text.clear()
    session.history.clear()
    session.triage_result.clear()
    session.phq9_started = False
    session.triage_active = False


def _inferred_state(session: SessionData) -> ConversationState:
    if len(session.personal_data) < len(PERSONAL_FIELDS):
        return ConversationState.DADOS
    if not session.phq9_started:
        return ConversationState.CONVERSA
    if len(session.phq9_answers) < len(PHQ9_QUESTIONS):
        return ConversationState.PHQ9
    if len(session.gad7_answers) < len(GAD7_QUESTIONS):
        return ConversationState.GAD7
    if not session.availability or session.observation == "":
        return ConversationState.AGENDAMENTO
    return ConversationState.AGENDAMENTO


def build_application(settings: Settings | None = None) -> Application:
    config = settings or get_settings()
    builder = (
        Application.builder()
        .token(config.telegram_token)
        .defaults(Defaults(parse_mode=ParseMode.MARKDOWN))
    )
    application = builder.build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("menu", start),
            MessageHandler(
                filters.Regex(r"(?i)^(?:oi|olá|ola|hello|hi|hey|bom dia|boa tarde|boa noite)\b"),
                start,
            ),
        ],
        states={
            ConversationState.MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu)],
            ConversationState.DADOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_personal_data)],
            ConversationState.CONVERSA: [MessageHandler(filters.TEXT & ~filters.COMMAND, empathetic_conversation)],
            ConversationState.PHQ9: [MessageHandler(filters.TEXT & ~filters.COMMAND, phq9_handler)],
            ConversationState.GAD7: [MessageHandler(filters.TEXT & ~filters.COMMAND, gad7_handler)],
            ConversationState.AGENDAMENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, scheduling_handler)],
        },
        fallbacks=[CommandHandler("cancelar", cancel)],
    )

    application.add_handler(conv_handler)
    return application


async def start(update: Update, context: CallbackContext) -> ConversationState:
    user = update.effective_user
    if not user or not update.message:
        return ConversationHandler.END
    session = _get_session(context, user.id)
    _reset_session(session)

    menu_keyboard = ReplyKeyboardMarkup(
        [["🩺 Triagem + Agendamento"], ["ℹ️ Informações"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "🧠 Olá! Sou o Assistente de Saúde Mental do IFAM CMZL.\nComo posso ajudar?",
        reply_markup=menu_keyboard,
    )
    logger.info("session_start", extra={"event": "session_start", "user_id": user.id})
    return ConversationState.MENU


async def menu(update: Update, context: CallbackContext) -> ConversationState:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    normalized = text.lower().strip().strip("!?.")
    if normalized in GREETINGS:
        session = _get_session(context, update.effective_user.id)
        if session.triage_active:
            inferred = _inferred_state(session)
            await update.message.reply_text(
                "Estamos com a triagem em andamento. Vamos continuar de onde paramos, tudo bem?"
            )
            if inferred == ConversationState.DADOS:
                field = session.next_personal_field()
                if field:
                    await update.message.reply_text(field[1])
            elif inferred == ConversationState.CONVERSA:
                await update.message.reply_text(
                    "Pode continuar compartilhando como tem se sentido. Assim que terminar, sigo com as próximas etapas."
                )
            elif inferred == ConversationState.PHQ9:
                idx = len(session.phq9_answers)
                await update.message.reply_text(
                    SCALE_INTRO + PHQ9_QUESTIONS[idx],
                    reply_markup=SCALE_KEYBOARD,
                )
            elif inferred == ConversationState.GAD7:
                idx = len(session.gad7_answers)
                await update.message.reply_text(
                    SCALE_INTRO + GAD7_QUESTIONS[idx],
                    reply_markup=SCALE_KEYBOARD,
                )
            else:
                if not session.availability:
                    await update.message.reply_text(
                        "Me conte seus horários disponíveis entre 15h e 18h (segunda a sexta)."
                    )
                elif session.observation == "":
                    await update.message.reply_text(
                        "Deseja adicionar alguma observação? (ou digite 'Nenhuma')"
                    )
            return inferred
        return await start(update, context)
    if text == "🩺 Triagem + Agendamento":
        session = _get_session(context, update.effective_user.id)
        _reset_session(session)
        session.triage_active = True
        field = session.next_personal_field()
        await update.message.reply_text(
            "Perfeito! Vamos começar com alguns dados básicos para o agendamento.",
            reply_markup=ReplyKeyboardRemove(),
        )
        if field:
            await update.message.reply_text(field[1])
        return ConversationState.DADOS
    if text == "ℹ️ Informações":
        await update.message.reply_text(
            "Triagem acolhedora do IFAM CMZL.\n"
            "Em caso de emergência, ligue 188 (CVV) ou 192 (SAMU).\n"
            "Use /start para voltar ao menu.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "Para iniciar a triagem, escolha 🩺 Triagem + Agendamento ou envie uma saudação como “oi”."
    )
    return ConversationState.MENU


async def collect_personal_data(update: Update, context: CallbackContext) -> ConversationState:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    session = _get_session(context, update.effective_user.id)
    text = (update.message.text or "").strip()
    if crisis_gate(text, False):
        await update.message.reply_text(CRISIS_MESSAGE)
    field = session.next_personal_field()
    if field is None:
        return await proceed_to_conversation(update, session)
    key, _question = field
    session.personal_data[key] = text
    session.triage_active = True
    field = session.next_personal_field()
    if field is None:
        return await proceed_to_conversation(update, session)
    await update.message.reply_text(field[1])
    return ConversationState.DADOS


async def proceed_to_conversation(update: Update, session: SessionData) -> ConversationState:
    if update.message:
        await update.message.reply_text(
            """Obrigado por compartilhar suas informações até aqui 💙

Agora, se sentir confortável, me conte:
**como você tem se sentido nos últimos dias?**

Estou aqui para te ouvir.

Logo após a sua mensagem, vou conduzir um questionário rápido para cuidar de você, tudo bem?"""
        )
    return ConversationState.CONVERSA


def _record_history(session: SessionData, message: str) -> None:
    session.history.append(message)
    session.history = session.history[-6:]
    session.free_text.append(message)


async def empathetic_conversation(update: Update, context: CallbackContext) -> ConversationState:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    message = (update.message.text or "").strip()
    session = _get_session(context, update.effective_user.id)

    classify = await classify_msg(message, session.history)
    crisis_detected = crisis_gate(message, classify.possivel_crise)
    _record_history(session, message)
    if crisis_detected:
        await update.message.reply_text(CRISIS_MESSAGE)
        logger.warning(
            "crisis_detected",
            extra={"event": "crisis", "user_id": session.user_id, "reason": "conversation"},
        )
    bubbles = [part.strip() for part in classify.resposta_empatica.split("\n\n") if part.strip()]
    if not bubbles:
        bubbles = [classify.resposta_empatica.strip() or "Estou aqui com você."]
    for chunk in bubbles[:2]:
        await update.message.reply_text(chunk)

    if not session.phq9_started:
        await update.message.reply_text(
            "Para seguirmos com o cuidado, vou aplicar um questionário rápido sobre seu humor nas últimas semanas."
        )
        await update.message.reply_text(
            "São 9 perguntas (PHQ-9). Responda usando os botões 0, 1, 2 ou 3 conforme a frequência."
        )
        return await start_phq9(update, session)

    return ConversationState.PHQ9


async def start_phq9(update: Update, session: SessionData) -> ConversationState:
    session.phq9_answers.clear()
    session.phq9_started = True
    if update.message:
        await update.message.reply_text(SCALE_INTRO + PHQ9_QUESTIONS[0], reply_markup=SCALE_KEYBOARD)
    return ConversationState.PHQ9


async def phq9_handler(update: Update, context: CallbackContext) -> ConversationState:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    if crisis_gate(text, False):
        await update.message.reply_text(CRISIS_MESSAGE)
        idx = len(session.phq9_answers)
        await update.message.reply_text(
            SCALE_INTRO + PHQ9_QUESTIONS[idx],
            reply_markup=SCALE_KEYBOARD,
        )
        return ConversationState.PHQ9
    session = _get_session(context, update.effective_user.id)

    if text not in {"0", "1", "2", "3"}:
        idx = len(session.phq9_answers)
        await update.message.reply_text(
            "Por favor, responda com 0, 1, 2 ou 3 conforme a escala de frequência.\n\n"
            + PHQ9_QUESTIONS[idx],
            reply_markup=SCALE_KEYBOARD,
        )
        return ConversationState.PHQ9

    session.phq9_answers.append(int(text))

    if len(session.phq9_answers) < len(PHQ9_QUESTIONS):
        next_question = PHQ9_QUESTIONS[len(session.phq9_answers)]
        await update.message.reply_text(SCALE_INTRO + next_question, reply_markup=SCALE_KEYBOARD)
        return ConversationState.PHQ9

    if phq9_item9_flag(session.phq9_answers):
        session.phq9_item9_positive = True
        logger.warning(
            "crisis_phq9_item9_flagged",
            extra={"event": "crisis_flag", "user_id": session.user_id, "reason": "phq9_item9"},
        )

    await update.message.reply_text(
        "Agora vamos responder 7 perguntas rápidas sobre ansiedade (GAD-7).",
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(
        SCALE_INTRO + GAD7_QUESTIONS[0],
        reply_markup=SCALE_KEYBOARD,
    )
    session.gad7_answers.clear()
    return ConversationState.GAD7


async def gad7_handler(update: Update, context: CallbackContext) -> ConversationState:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    if crisis_gate(text, False):
        await update.message.reply_text(CRISIS_MESSAGE)
        idx = len(session.gad7_answers)
        await update.message.reply_text(
            SCALE_INTRO + GAD7_QUESTIONS[idx],
            reply_markup=SCALE_KEYBOARD,
        )
        return ConversationState.GAD7
    session = _get_session(context, update.effective_user.id)

    if text not in {"0", "1", "2", "3"}:
        idx = len(session.gad7_answers)
        await update.message.reply_text(
            "Por favor, responda com 0, 1, 2 ou 3 conforme a escala de frequência.\n\n"
            + GAD7_QUESTIONS[idx],
            reply_markup=SCALE_KEYBOARD,
        )
        return ConversationState.GAD7

    session.gad7_answers.append(int(text))

    if len(session.gad7_answers) < len(GAD7_QUESTIONS):
        next_question = GAD7_QUESTIONS[len(session.gad7_answers)]
        await update.message.reply_text(SCALE_INTRO + next_question, reply_markup=SCALE_KEYBOARD)
        return ConversationState.GAD7

    await update.message.reply_text(
        "Para finalizar, informe seus horários disponíveis (seg–sex, 15h–18h).",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationState.AGENDAMENTO


def _validate_availability(text: str) -> bool:
    lower = text.lower()
    valid_days = {"segunda", "terça", "terca", "quarta", "quinta", "sexta"}
    return any(day in lower for day in valid_days) and any(h in lower for h in ["15", "16", "17", "18"])


async def scheduling_handler(update: Update, context: CallbackContext) -> ConversationState:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    session = _get_session(context, update.effective_user.id)
    text = (update.message.text or "").strip()
    if crisis_gate(text, False):
        await update.message.reply_text(CRISIS_MESSAGE)

    if not session.availability:
        if not _validate_availability(text):
            await update.message.reply_text(
                "Informe dia(s) e horários entre 15h e 18h, de segunda a sexta.",
            )
            return ConversationState.AGENDAMENTO
        session.availability = text
        await update.message.reply_text("Deseja adicionar alguma observação? (ou digite 'Nenhuma')")
        return ConversationState.AGENDAMENTO

    session.observation = "" if text.lower() == "nenhuma" else text
    await finalize_screening(update, session)
    return ConversationHandler.END


async def finalize_screening(update: Update, session: SessionData) -> None:
    phq9_total = phq9_score(session.phq9_answers)
    gad7_total = gad7_score(session.gad7_answers)
    dados = session.personal_data.copy()

    triage = await triage_summary(
        dados_pessoais=dados,
        phq9_respostas=session.phq9_answers,
        gad7_respostas=session.gad7_answers,
        texto_livre=session.free_text,
    )
    session.triage_result = triage.model_dump()

    deterministic = build_deterministic_summary(
        nome=dados.get("nome", "Participante"),
        phq9_answers=session.phq9_answers,
        gad7_answers=session.gad7_answers,
        disponibilidade=session.availability,
        observacao=session.observation,
        free_text=session.free_text,
        triage=session.triage_result,
    )

    contexto = {
        "dados": dados,
        "phq9_score": phq9_total,
        "gad7_score": gad7_total,
        "disponibilidade": session.availability,
        "observacao": session.observation,
        "triage": session.triage_result,
    }

    llm_text = await gen_report_text(json.dumps(contexto, ensure_ascii=False))
    final_report = compose_report_text(deterministic, llm_text)

    payload = {
        "nome": dados.get("nome"),
        "idade": dados.get("idade"),
        "matricula": dados.get("matricula"),
        "curso": dados.get("curso"),
        "periodo": dados.get("periodo"),
        "phq9_respostas": session.phq9_answers,
        "phq9_score": phq9_total,
        "gad7_respostas": session.gad7_answers,
        "gad7_score": gad7_total,
        "disponibilidade": session.availability,
        "observacao": session.observation,
        "relatorio": final_report,
        "analise_ia": session.triage_result,
        "telegram_id": str(session.user_id),
    }

    settings = get_settings()
    success = send_screening(settings.backend_url, settings.bot_shared_secret, payload)
    if not success:
        logger.error(
            "backend_post_failed",
            extra={"event": "backend_post_failed", "user_id": session.user_id},
        )

    if update.message:
        await update.message.reply_text(
            "✅ Triagem registrada com sucesso. A equipe entrará em contato em breve. "
            "Em caso de emergência, procure ajuda imediatamente (188 ou 192)."
        )
    logger.info("screening_completed", extra={"event": "screening_completed", "user_id": session.user_id})
    session.triage_active = False


async def cancel(update: Update, context: CallbackContext) -> int:
    if update.message:
        await update.message.reply_text("Triagem cancelada. Use /start para recomeçar.")
    session = context.user_data.get("session")
    if isinstance(session, SessionData):
        session.triage_active = False
    return ConversationHandler.END

