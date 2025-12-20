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
    "Sinto muito saber que você está passando por um momento tão difícil. 💙\n"
    "Sua segurança é prioridade.\n"
    "Se você estiver em risco agora, procure ajuda imediata:\n"
    "• CVV 188\n"
    "• SAMU 192\n"
    "• Pronto-socorro mais próximo.\n"
    "Se você quiser, posso continuar a triagem com você."
)

SCALE_INTRO = (
    "📝 Responda usando a escala:\n"
    "0 — Nunca | 1 — Vários dias | 2 — Mais da metade dos dias | 3 — Quase todos os dias\n\n"
)

SCALE_KEYBOARD = ReplyKeyboardMarkup([["0", "1", "2", "3"]], one_time_keyboard=True, resize_keyboard=True)

PERSONAL_FIELDS = [
    ("nome", "Qual seu nome completo?"),
    ("idade", "Qual sua idade?"),
    ("telefone", "Qual seu número de telefone para contato? (ex: 92999999999 ou +5592999999999)"),
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

    menu_keyboard = ReplyKeyboardMarkup([["Sim, vamos começar"], ["Agora não"], ["ℹ️ Informações"]], resize_keyboard=True)
    await update.message.reply_text(
        "Oi! 💙 Sou o assistente de saúde mental do IFAM-CMZL.\nPosso te ajudar com uma triagem rápida para organizar seu atendimento com o psicólogo.",
        reply_markup=menu_keyboard,
    )
    await update.message.reply_text(
        "Essa triagem não é diagnóstico. Ela só ajuda a equipe a entender como você está e organizar o atendimento presencial.\n\nVocê deseja continuar?"
    )
    logger.info("session_start", extra={"event": "session_start", "user_id": user.id})
    return ConversationState.MENU


async def menu(update: Update, context: CallbackContext) -> ConversationState:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    normalized = text.lower().strip().strip("!?.")
    if normalized in {"sim", "vamos", "vamos comecar", "vamos começar", "quero", "topo", "sim, vamos começar", "sim vamos começar", "sim vamos", "sim, vamos"} or text == "🩺 Triagem + Agendamento" or text == "Sim, vamos começar":
        session = _get_session(context, update.effective_user.id)
        _reset_session(session)
        session.triage_active = True
        field = session.next_personal_field()
        await update.message.reply_text(
            "Perfeito, obrigado por aceitar. 🙏\nVamos começar com alguns dados rápidos para organizar seu atendimento.",
            reply_markup=ReplyKeyboardRemove(),
        )
        if field:
            await update.message.reply_text(field[1])
        return ConversationState.DADOS
    if normalized in {"nao", "não", "agora nao", "agora não"} or text == "Agora não":
        await update.message.reply_text(
            "Tudo bem. Obrigado por conversar comigo. 💙 Se quiser retomar depois, é só mandar “/start”.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END
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
                    f"{idx+1}️⃣ {PHQ9_QUESTIONS[idx]} (0–3)",
                    reply_markup=SCALE_KEYBOARD,
                )
            elif inferred == ConversationState.GAD7:
                idx = len(session.gad7_answers)
                await update.message.reply_text(
                    f"{idx+1}️⃣ {GAD7_QUESTIONS[idx]} (0–3)",
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
        "Para iniciar a triagem, responda “Sim, vamos começar” ou envie uma saudação como “oi”."
    )
    return ConversationState.MENU


async def collect_personal_data(update: Update, context: CallbackContext) -> ConversationState:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    session = _get_session(context, update.effective_user.id)
    text = (update.message.text or "").strip()
    # Debug: mostra qual campo está sendo processado
    field = session.next_personal_field()
    if field:
        print(f"   📝 Processando campo: {field[0]}")
    if crisis_gate(text, False):
        await update.message.reply_text(CRISIS_MESSAGE)
    field = session.next_personal_field()
    if field is None:
        return await proceed_to_conversation(update, session)
    key, _question = field
    
    import re
    
    # Validação específica para nome (apenas letras e espaços)
    if key == "nome":
        nome = re.sub(r"\s+", " ", text).strip()
        if (
            not nome
            or len(nome) < 3
            or not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ' -]+", nome)
        ):
            await update.message.reply_text(
                "Por favor, informe apenas seu nome completo usando letras e espaços. Exemplo: Maria Silva."
            )
            return ConversationState.DADOS
        session.personal_data[key] = nome
        session.triage_active = True
        field = session.next_personal_field()
        if field is None:
            return await proceed_to_conversation(update, session)
        await update.message.reply_text(field[1])
        return ConversationState.DADOS
    
    # Validação específica para idade (10-100)
    if key == "idade":
        try:
            idade_num = int(text)
            if idade_num < 10 or idade_num > 100:
                await update.message.reply_text("Por favor, informe sua idade apenas com números. Exemplo: 22.")
                return ConversationState.DADOS
            session.personal_data[key] = str(idade_num)
        except ValueError:
            await update.message.reply_text("Por favor, informe sua idade apenas com números. Exemplo: 22.")
            return ConversationState.DADOS
        session.triage_active = True
        field = session.next_personal_field()
        if field is None:
            return await proceed_to_conversation(update, session)
        await update.message.reply_text(field[1])
        return ConversationState.DADOS
    
    # Validação específica para telefone (11-13 dígitos, formato: 92999999999 ou +5592999999999)
    if key == "telefone":
        # Remove espaços, hífens, parênteses
        telefone_limpo = text.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        
        # Verifica se começa com +55 ou +
        if telefone_limpo.startswith("+55"):
            digitos = re.sub(r'[^\d]', '', telefone_limpo[3:])  # Remove +55 e mantém só dígitos
            telefone_final = "+55" + digitos
        elif telefone_limpo.startswith("+"):
            digitos = re.sub(r'[^\d]', '', telefone_limpo[1:])  # Remove + e mantém só dígitos
            telefone_final = "+" + digitos
        else:
            digitos = re.sub(r'[^\d]', '', telefone_limpo)  # Apenas dígitos
            telefone_final = digitos
        
        # Valida quantidade de dígitos (11-13 dígitos totais)
        total_digitos = len(re.sub(r'[^\d]', '', telefone_final))
        if total_digitos < 11 or total_digitos > 13:
            await update.message.reply_text("Informe um telefone válido no formato: 92999999999 ou +5592999999999.")
            return ConversationState.DADOS
        
        session.personal_data[key] = telefone_final
        session.triage_active = True
        field = session.next_personal_field()
        if field is None:
            return await proceed_to_conversation(update, session)
        await update.message.reply_text(field[1])
        return ConversationState.DADOS
    
    # Validação específica para matrícula (6-15 dígitos, apenas números)
    if key == "matricula":
        # Remove espaços e caracteres não numéricos
        matricula_limpa = re.sub(r'[^\d]', '', text)
        if len(matricula_limpa) < 6 or len(matricula_limpa) > 15:
            await update.message.reply_text("Por favor, informe apenas os números da matrícula.")
            return ConversationState.DADOS
        session.personal_data[key] = matricula_limpa
        session.triage_active = True
        field = session.next_personal_field()
        if field is None:
            return await proceed_to_conversation(update, session)
        await update.message.reply_text(field[1])
        return ConversationState.DADOS
    
    # Validação específica para curso (apenas letras e espaços)
    if key == "curso":
        curso = re.sub(r"\s+", " ", text).strip()
        if not curso or not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ' -]+", curso):
            await update.message.reply_text("Por favor, informe o nome do seu curso usando apenas letras.")
            return ConversationState.DADOS
        session.personal_data[key] = curso
        session.triage_active = True
        field = session.next_personal_field()
        if field is None:
            return await proceed_to_conversation(update, session)
        await update.message.reply_text(field[1])
        return ConversationState.DADOS
    
    # Validação específica para período (1-12, apenas números)
    if key == "periodo":
        try:
            periodo_num = int(text)
            if periodo_num < 1 or periodo_num > 12:
                await update.message.reply_text("Informe apenas o período/semestre em número. Exemplo: 8.")
                return ConversationState.DADOS
            session.personal_data[key] = str(periodo_num)
        except ValueError:
            await update.message.reply_text("Informe apenas o período/semestre em número. Exemplo: 8.")
            return ConversationState.DADOS
        session.triage_active = True
        field = session.next_personal_field()
        if field is None:
            return await proceed_to_conversation(update, session)
        await update.message.reply_text(field[1])
        return ConversationState.DADOS
    
    # Se não for nenhum campo específico, salva normalmente
    session.personal_data[key] = text
    
    session.triage_active = True
    field = session.next_personal_field()
    if field is None:
        return await proceed_to_conversation(update, session)
    await update.message.reply_text(field[1])
    return ConversationState.DADOS


async def proceed_to_conversation(update: Update, session: SessionData) -> ConversationState:
    if update.message:
        await update.message.reply_text("Perfeito, obrigado por compartilhar essas informações. 🙏")
        await update.message.reply_text("Agora, se você se sentir à vontade, me conta com suas palavras: como você tem se sentido nos últimos dias? 💙")
        await update.message.reply_text("Depois vou te fazer algumas perguntas rápidas. Não é diagnóstico; é para o psicólogo entender melhor como te apoiar.")
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
        await update.message.reply_text("Agora vou te fazer 9 perguntas sobre as últimas duas semanas.")
        await update.message.reply_text("Use esta escala para responder só o número: 0 nunca, 1 vários dias, 2 mais da metade dos dias, 3 quase todos os dias. Entendeu? 🙂")
        return await start_phq9(update, session)

    return ConversationState.PHQ9


async def start_phq9(update: Update, session: SessionData) -> ConversationState:
    session.phq9_answers.clear()
    session.phq9_started = True
    if update.message:
        await update.message.reply_text(
            f"1️⃣ {PHQ9_QUESTIONS[0]}\n(0 — Nunca | 1 — Vários dias | 2 — Mais da metade dos dias | 3 — Quase todos os dias)",
            reply_markup=SCALE_KEYBOARD
        )
    return ConversationState.PHQ9


async def phq9_handler(update: Update, context: CallbackContext) -> ConversationState:
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    if crisis_gate(text, False):
        await update.message.reply_text(CRISIS_MESSAGE)
        idx = len(session.phq9_answers)
        await update.message.reply_text(
            f"{idx+1}️⃣ {PHQ9_QUESTIONS[idx]}\n(0 — Nunca | 1 — Vários dias | 2 — Mais da metade dos dias | 3 — Quase todos os dias)",
            reply_markup=SCALE_KEYBOARD
        )
        return ConversationState.PHQ9
    session = _get_session(context, update.effective_user.id)

    if text not in {"0", "1", "2", "3"}:
        idx = len(session.phq9_answers)
        await update.message.reply_text(
            "Responda apenas com um número entre 0 e 3.\n\n"
            + f"{idx+1}️⃣ {PHQ9_QUESTIONS[idx]}\n(0 — Nunca | 1 — Vários dias | 2 — Mais da metade dos dias | 3 — Quase todos os dias)",
            reply_markup=SCALE_KEYBOARD,
        )
        return ConversationState.PHQ9

    session.phq9_answers.append(int(text))

    if len(session.phq9_answers) < len(PHQ9_QUESTIONS):
        idx = len(session.phq9_answers)
        next_question = PHQ9_QUESTIONS[idx]
        await update.message.reply_text(
            f"{idx+1}️⃣ {next_question}\n(0 — Nunca | 1 — Vários dias | 2 — Mais da metade dos dias | 3 — Quase todos os dias)",
            reply_markup=SCALE_KEYBOARD
        )
        return ConversationState.PHQ9

    if phq9_item9_flag(session.phq9_answers):
        session.phq9_item9_positive = True
        logger.warning(
            "crisis_phq9_item9_flagged",
            extra={"event": "crisis_flag", "user_id": session.user_id, "reason": "phq9_item9"},
        )

    await update.message.reply_text(
        "Obrigado. Agora vou fazer 7 perguntas rápidas sobre ansiedade (GAD-7).",
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(
        f"1️⃣ {GAD7_QUESTIONS[0]}\n(0 — Nunca | 1 — Vários dias | 2 — Mais da metade dos dias | 3 — Quase todos os dias)",
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
            f"{idx+1}️⃣ {GAD7_QUESTIONS[idx]}\n(0 — Nunca | 1 — Vários dias | 2 — Mais da metade dos dias | 3 — Quase todos os dias)",
            reply_markup=SCALE_KEYBOARD
        )
        return ConversationState.GAD7
    session = _get_session(context, update.effective_user.id)

    if text not in {"0", "1", "2", "3"}:
        idx = len(session.gad7_answers)
        await update.message.reply_text(
            "Responda apenas com um número entre 0 e 3.\n\n"
            + f"{idx+1}️⃣ {GAD7_QUESTIONS[idx]}\n(0 — Nunca | 1 — Vários dias | 2 — Mais da metade dos dias | 3 — Quase todos os dias)",
            reply_markup=SCALE_KEYBOARD,
        )
        return ConversationState.GAD7

    session.gad7_answers.append(int(text))

    if len(session.gad7_answers) < len(GAD7_QUESTIONS):
        idx = len(session.gad7_answers)
        next_question = GAD7_QUESTIONS[idx]
        await update.message.reply_text(
            f"{idx+1}️⃣ {next_question}\n(0 — Nunca | 1 — Vários dias | 2 — Mais da metade dos dias | 3 — Quase todos os dias)",
            reply_markup=SCALE_KEYBOARD
        )
        return ConversationState.GAD7

    await update.message.reply_text(
        "Obrigado por responder. 💙",
        reply_markup=ReplyKeyboardRemove(),
    )
    # Mensagem institucional de disponibilidade do psicólogo
    await update.message.reply_text(
        "O psicólogo atenderá presencialmente de segunda a sexta, das 15h às 18h, e usará sua disponibilidade para marcar a sessão."
    )
    await update.message.reply_text("Quais dias e horários dentro desse período você tem disponibilidade?")
    print("   📅 Mudando para estado AGENDAMENTO")
    return ConversationState.AGENDAMENTO


def _validate_availability(text: str) -> bool:
    lower = text.lower()
    valid_days = {"segunda", "terça", "terca", "quarta", "quinta", "sexta", "seg", "ter", "qua", "qui", "sex"}
    # Verifica se contém dia útil
    has_valid_day = any(day in lower for day in valid_days)
    # Verifica se contém horário entre 15h e 18h (aceita 15, 16, 17, 18, 15h, 16h, 17h, 18h, 15:00, etc)
    has_valid_hour = any(h in lower for h in ["15", "16", "17", "18"])
    return has_valid_day and has_valid_hour


async def scheduling_handler(update: Update, context: CallbackContext) -> ConversationState:
    # Print de debug para rastreamento
    print("="*60)
    print("📅 SCHEDULING_HANDLER CHAMADO!")
    if update.effective_user:
        print(f"   User ID: {update.effective_user.id}")
    print("="*60)
    
    if not update.message or not update.effective_user:
        print("⚠️  SCHEDULING_HANDLER: Sem mensagem ou usuário")
        return ConversationHandler.END
    
    session = _get_session(context, update.effective_user.id)
    text = (update.message.text or "").strip()
    
    print(f"   Texto recebido: {text[:50]}")
    print(f"   Disponibilidade atual: {session.availability[:50] if session.availability else 'N/A'}")
    print(f"   Observação atual: {session.observation[:50] if session.observation else 'N/A'}")
    
    if crisis_gate(text, False):
        await update.message.reply_text(CRISIS_MESSAGE)

    if not session.availability:
        print("   📝 Processando disponibilidade...")
        if not _validate_availability(text):
            await update.message.reply_text(
                "Os atendimentos ocorrem de segunda a sexta, das 15h às 18h. Pode me informar um horário dentro desse período?",
            )
            return ConversationState.AGENDAMENTO
        session.availability = text
        print(f"   ✅ Disponibilidade salva: {session.availability}")
        await update.message.reply_text("Deseja adicionar alguma observação? (ou digite 'Nenhuma')")
        return ConversationState.AGENDAMENTO

    print("   📝 Processando observação (isso deve chamar finalize_screening)...")
    session.observation = "" if text.lower() == "nenhuma" else text
    print(f"   ✅ Observação salva: {session.observation[:50] if session.observation else 'Nenhuma'}")
    print("   🚀 Chamando finalize_screening...")
    await finalize_screening(update, session)
    print("   ✅ finalize_screening concluído")
    return ConversationHandler.END


async def finalize_screening(update: Update, session: SessionData) -> None:
    # Print de debug para rastreamento
    print("="*60)
    print("🚀 FINALIZE_SCREENING CHAMADO!")
    print(f"   User ID: {session.user_id}")
    print(f"   Nome: {session.personal_data.get('nome', 'N/A')}")
    print(f"   PHQ-9: {len(session.phq9_answers)} respostas")
    print(f"   GAD-7: {len(session.gad7_answers)} respostas")
    print("="*60)
    
    logger.info("Iniciando finalização da triagem...")
    logger.info(f"User ID: {session.user_id}, Nome: {session.personal_data.get('nome', 'N/A')}")
    
    # Envia mensagem de processamento para o usuário
    processing_msg = None
    if update.message:
        try:
            processing_msg = await update.message.reply_text("⏳ Processando sua triagem... Isso pode levar alguns segundos.")
        except Exception as e:
            logger.warning(f"Erro ao enviar mensagem de processamento (ignorado): {e}")
            processing_msg = None
    
    phq9_total = phq9_score(session.phq9_answers)
    gad7_total = gad7_score(session.gad7_answers)
    dados = session.personal_data.copy()

    logger.info("Chamando triage_summary...")
    try:
        triage = await triage_summary(
            dados_pessoais=dados,
            phq9_respostas=session.phq9_answers,
            gad7_respostas=session.gad7_answers,
            texto_livre=session.free_text,
        )
        session.triage_result = triage.model_dump()
        logger.info("triage_summary concluído")
    except Exception as e:
        logger.error(f"Erro em triage_summary: {e}")
        session.triage_result = {}

    deterministic = build_deterministic_summary(
        nome=dados.get("nome", "Participante"),
        phq9_answers=session.phq9_answers,
        gad7_answers=session.gad7_answers,
        disponibilidade=session.availability,
        observacao=session.observation,
        free_text=session.free_text,
        triage=session.triage_result,
        phq9_item9_positive=session.phq9_item9_positive,
    )

    # Prepara contexto mais rico para o relatório da IA
    from .instruments import phq9_bucket, gad7_bucket
    from datetime import datetime
    
    phq9_nivel = phq9_bucket(phq9_total)
    gad7_nivel = gad7_bucket(gad7_total)
    
    # Determina classificação geral (maior risco)
    risk_weight = {"Mínima": 0, "Leve": 1, "Moderada": 2, "Moderadamente grave": 3, "Grave": 4}
    phq9_weight = risk_weight.get(phq9_nivel, 0)
    gad7_weight = risk_weight.get(gad7_nivel, 0)
    classificacao_geral = phq9_nivel if phq9_weight >= gad7_weight else gad7_nivel
    
    # Determina item mais preocupante
    top_phq9_score = max(session.phq9_answers) if session.phq9_answers else -1
    top_gad7_score = max(session.gad7_answers) if session.gad7_answers else -1
    item_mais_preocupante = ""
    if top_phq9_score >= top_gad7_score and top_phq9_score > 0:
        idx = session.phq9_answers.index(top_phq9_score)
        from .instruments import PHQ9_QUESTIONS
        item_mais_preocupante = f"PHQ-9 Q{idx + 1}: {PHQ9_QUESTIONS[idx].split(' ', 1)[1] if ' ' in PHQ9_QUESTIONS[idx] else PHQ9_QUESTIONS[idx]} (pontuação {top_phq9_score})"
    elif top_gad7_score > 0:
        idx = session.gad7_answers.index(top_gad7_score)
        from .instruments import GAD7_QUESTIONS
        item_mais_preocupante = f"GAD-7 Q{idx + 1}: {GAD7_QUESTIONS[idx].split(' ', 1)[1] if ' ' in GAD7_QUESTIONS[idx] else GAD7_QUESTIONS[idx]} (pontuação {top_gad7_score})"
    
    contexto = {
        "nome": dados.get("nome", "Participante"),
        "matricula": dados.get("matricula", "Não informada"),
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "disponibilidade": session.availability or "Não informada",
        "phq9_score": phq9_total,
        "phq9_classificacao": phq9_nivel,
        "gad7_score": gad7_total,
        "gad7_classificacao": gad7_nivel,
        "classificacao_geral": classificacao_geral,
        "phq9_respostas": session.phq9_answers,
        "gad7_respostas": session.gad7_answers,
        "item_mais_preocupante": item_mais_preocupante,
        "item9_positive": session.phq9_item9_positive,
        "observacao": session.observation or "",
        "relatos_livres": list(session.free_text)[-6:] if session.free_text else [],
        "triage": session.triage_result or {},
    }

    logger.info("Chamando gen_report_text...")
    try:
        llm_text = await gen_report_text(json.dumps(contexto, ensure_ascii=False))
        logger.info("gen_report_text concluído")
    except Exception as e:
        logger.error(f"Erro em gen_report_text: {e}")
        llm_text = ""
    
    final_report = compose_report_text(deterministic, llm_text)
    
    # Remove mensagem de processamento
    if processing_msg:
        try:
            await processing_msg.delete()
        except Exception as e:
            logger.debug(f"Erro ao deletar mensagem de processamento (ignorado): {e}")
            pass  # Ignora se não conseguir deletar

    # Converte idade para número se necessário
    idade_val = dados.get("idade")
    if isinstance(idade_val, str):
        try:
            idade_val = int(idade_val)
        except:
            idade_val = 18
    
    payload = {
        "nome": dados.get("nome"),
        "idade": idade_val,
        "telefone": dados.get("telefone", ""),
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
    logger.info(f"Enviando triagem para: {settings.backend_url}")
    logger.info(f"Secret configurado: {'Sim' if settings.bot_shared_secret else 'Não'}")
    logger.debug(f"Payload completo: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    # Validação básica do payload antes de enviar
    required_fields = ["nome", "matricula", "curso", "periodo", "phq9_respostas", "gad7_respostas", "relatorio"]
    missing_fields = [f for f in required_fields if not payload.get(f)]
    if missing_fields:
        logger.error(f"Payload incompleto. Campos faltando: {missing_fields}")
    
    success = send_screening(settings.backend_url, settings.bot_shared_secret, payload)
    if not success:
        logger.error(
            "backend_post_failed",
            extra={
                "event": "backend_post_failed",
                "user_id": session.user_id,
                "url": str(settings.backend_url),
                "secret_length": len(settings.bot_shared_secret) if settings.bot_shared_secret else 0,
            },
        )
        # Ainda mostra mensagem de sucesso para o usuário, mas loga o erro
        if update.message:
            await update.message.reply_text(
                "⚠️ Aviso: A triagem foi registrada localmente, mas houve um problema ao enviar para o sistema. "
                "A equipe será notificada. Em caso de emergência, procure ajuda imediatamente (188 ou 192)."
            )
        return

    # Prepara mensagem simples de resultados e encerramento
    if update.message:
        try:
            from .instruments import phq9_bucket, gad7_bucket
            
            # Rótulos simples
            phq9_label = phq9_bucket(phq9_total)
            gad7_label = gad7_bucket(gad7_total)

            # Classificação geral simples com base no risco maior
            risk_weight = {"Mínima": 0, "Leve": 1, "Moderada": 2, "Moderadamente grave": 3, "Grave": 4}
            phq9_weight = risk_weight.get(phq9_label, 0)
            gad7_weight = risk_weight.get(gad7_label, 0)
            classificacao_simples = phq9_label if phq9_weight >= gad7_weight else gad7_label

            resultados_msg = (
                "📊 Resultados da sua Triagem\n\n"
                f"PHQ-9: {phq9_total} pontos – {phq9_label}\n"
                f"GAD-7: {gad7_total} pontos – {gad7_label}\n"
                f"🟢 Classificação geral: {classificacao_simples}"
            )

            await update.message.reply_text(resultados_msg)

            mensagem_final = (
                "Obrigado por confiar em nós e concluir sua triagem.\n"
                "O psicólogo irá verificar sua disponibilidade e retornará com o agendamento. 💙\n\n"
                "Em caso de emergência, procure ajuda imediata:\n"
                "CVV 188 • SAMU 192\n"
                "Cuide-se 💚."
            )
            await update.message.reply_text(mensagem_final)
        except Exception as e:
            logger.warning(f"Erro ao enviar mensagens finais (ignorado): {e}")
            # Não interrompe o fluxo - o importante é que o backend recebeu
    
    logger.info("screening_completed", extra={"event": "screening_completed", "user_id": session.user_id})
    session.triage_active = False


async def cancel(update: Update, context: CallbackContext) -> int:
    if update.message:
        await update.message.reply_text("Triagem cancelada. Use /start para recomeçar.")
    session = context.user_data.get("session")
    if isinstance(session, SessionData):
        session.triage_active = False
    return ConversationHandler.END

