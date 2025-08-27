print(">> MAIN EXEC:", __file__)
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from dotenv import load_dotenv
import google.generativeai as genai
from datetime import datetime
import requests
import os

load_dotenv()


genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('models/gemini-1.5-flash')

# Estados da conversa
MENU, DADOS, PHQ9, GAD7, AGENDAMENTO = range(5)


respostas = {}

phq9_perguntas = [
    "1. Pouco interesse ou prazer em fazer as coisas?",
    "2. Sentir-se para baixo, deprimido(a) ou sem esperança?",
    "3. Dificuldade para dormir, dormir demais ou dormir mal?",
    "4. Sentir-se cansado(a) ou com pouca energia?",
    "5. Falta de apetite ou comer em excesso?",
    "6. Sentir-se mal consigo mesmo(a) ou que é um fracasso?",
    "7. Dificuldade de concentração, como ao ler ou assistir TV?",
    "8. Mover-se ou falar muito devagar, ou estar muito agitado(a)?",
    "9. Pensamentos de que seria melhor estar morto(a) ou se machucar?"
]

gad7_perguntas = [
    "1. Sentir-se nervoso(a), ansioso(a) ou tenso(a)?",
    "2. Não conseguir parar ou controlar a preocupação?",
    "3. Preocupar-se excessivamente com diferentes coisas?",
    "4. Dificuldade em relaxar?",
    "5. Estar tão inquieto(a) que é difícil ficar parado(a)?",
    "6. Ficar facilmente irritado(a) ou aborrecido(a)?",
    "7. Sentir medo como se algo horrível fosse acontecer?"
]

teclado_respostas = [["0", "1", "2", "3"]]
markup_respostas = ReplyKeyboardMarkup(teclado_respostas, one_time_keyboard=True, resize_keyboard=True)
# 
escala = "📝 Responda usando a escala:\n0 — Nunca | 1 — Vários dias | 2 — Mais da metade dos dias | 3 — Quase todos os dias\n\n"


# ----------- MENU INICIAL ------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    respostas[user_id] = {"dados": [], "phq9": [], "gad7": [], "agendamento": {}}

    teclado_menu = [
        ["🩺 Triagem + Agendamento"],
        ["ℹ️ Informações"]
    ]
    markup_menu = ReplyKeyboardMarkup(teclado_menu, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        "🧠 Olá! Sou o Assistente de Saúde Mental do IFAM CMZL 💙\n"
        "Como posso te ajudar hoje?\n\n"
        "Escolha uma opção no menu:",
        reply_markup=markup_menu
    )
    return MENU

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text

    if texto == "🩺 Triagem + Agendamento":
        await update.message.reply_text("Perfeito! Vamos começar com seus dados pessoais.\n\nPor favor, informe seu nome completo:", reply_markup=ReplyKeyboardRemove())
        context.user_data["etapa"] = "nome"
        return DADOS

    elif texto == "ℹ️ Informações":
        await update.message.reply_text(
            "🧠 **Informações sobre o serviço:**\n"
            "• Atendimento psicológico para alunos do IFAM CMZL.\n"
            "• Triagem online para avaliar seu bem-estar emocional.\n"
            "• Após a triagem, você pode solicitar atendimento com um psicólogo.\n"
            "• Suporte sigiloso, gratuito e acolhedor.\n\n"
            "Digite /start ou /menu para voltar ao menu."
        )
        return ConversationHandler.END

# ----------- COLETA DE DADOS ------------

async def coletar_dados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    texto = update.message.text
    etapa = context.user_data.get("etapa")

    if etapa == "nome":
        respostas[user_id]["dados"].append(texto)
        await update.message.reply_text("Idade:")
        context.user_data["etapa"] = "idade"
        return DADOS

    if etapa == "idade":
        respostas[user_id]["dados"].append(texto)
        await update.message.reply_text("Matrícula:")
        context.user_data["etapa"] = "matricula"
        return DADOS

    if etapa == "matricula":
        respostas[user_id]["dados"].append(texto)
        await update.message.reply_text("Curso:")
        context.user_data["etapa"] = "curso"
        return DADOS

    if etapa == "curso":
        respostas[user_id]["dados"].append(texto)
        await update.message.reply_text("Período/Semestre:")
        context.user_data["etapa"] = "periodo"
        return DADOS
    if etapa == "periodo":
        respostas[user_id]["dados"].append(texto)
        await update.message.reply_text(
            escala + phq9_perguntas[0],
            reply_markup=markup_respostas
        )
        context.user_data["indice"] = 0
        return PHQ9



# ----------- PHQ-9 ------------


async def phq9(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    respostas[user_id]["phq9"].append(int(update.message.text))

    indice = context.user_data["indice"] + 1
    context.user_data["indice"] = indice

    if indice < len(phq9_perguntas):
        await update.message.reply_text(
            escala + phq9_perguntas[indice],
            reply_markup=markup_respostas
        )
        return PHQ9
    else:
        await update.message.reply_text(
            "Agora vamos para as perguntas sobre ansiedade (GAD-7):\n\n"
            + escala + gad7_perguntas[0],
            reply_markup=markup_respostas
        )
        context.user_data["indice"] = 0  # Reseta o índice para o GAD-7
        return GAD7




# ----------- GAD-7 ------------

async def gad7(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    respostas[user_id]["gad7"].append(int(update.message.text))

    indice = context.user_data["indice"] + 1
    context.user_data["indice"] = indice

    if indice < len(gad7_perguntas):
        await update.message.reply_text(
            escala + gad7_perguntas[indice],
            reply_markup=markup_respostas
        )
        return GAD7
    else:
        await update.message.reply_text(
            "Perfeito! Agora, para finalizar, gostaria de saber sobre sua disponibilidade para agendamento.\n"
            "⚠️ O atendimento é realizado **apenas presencialmente, de segunda a sexta, das 15h às 18h.**\n"
            "Por favor, informe seus dias e horários disponíveis:"
        )
        context.user_data["etapa"] = "disponibilidade"
        return AGENDAMENTO



# ----------- AGENDAMENTO ------------

async def agendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    texto = update.message.text.strip().lower()
    etapa = context.user_data.get("etapa")

    if etapa == "disponibilidade":
        # Validação de dia e horário
        if not (
            ("15" in texto or "16" in texto or "17" in texto or "18" in texto)
            and any(dia in texto for dia in ["segunda", "terça", "terca", "quarta", "quinta", "sexta"])
        ):
            await update.message.reply_text(
                "⚠️ O atendimento é realizado **apenas presencialmente, de segunda a sexta, das 15h às 18h.**\n"
                "Por favor, informe corretamente sua disponibilidade dentro desse período."
            )
            return AGENDAMENTO

        respostas[user_id]["agendamento"]["disponibilidade"] = texto

        await update.message.reply_text("Se desejar, adicione alguma observação (ou digite 'Nenhuma'):")
        context.user_data["etapa"] = "observacao"
        return AGENDAMENTO

    if etapa == "observacao":
        respostas[user_id]["agendamento"]["observacao"] = texto

        await gerar_relatorio(update, context)

        await update.message.reply_text(
            "✅ Sua triagem e solicitação de agendamento foram registradas.\n"
            "O setor de psicologia entrará em contato em breve. 💙"
        )
        return ConversationHandler.END



# ----------- RELATÓRIO E GOOGLE SHEETS ------------

async def gerar_relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    dados = respostas[user_id]["dados"]
    phq9 = respostas[user_id]["phq9"]
    gad7 = respostas[user_id]["gad7"]
    agendamento = respostas[user_id]["agendamento"]

    phq9_score = sum(phq9)
    gad7_score = sum(gad7)

    data_hora = datetime.now().strftime('%d/%m/%Y %H:%M')

    prompt = (
    f"Você é um assistente psicológico que gera relatórios de triagem.\n\n"
    f"🧠 Dados Pessoais:\n"
    f"• Nome: {dados[0]}\n"
    f"• Idade: {dados[1]} anos\n"
    f"• Matrícula: {dados[2]}\n"
    f"• Curso: {dados[3]}\n"
    f"• Período/Semestre: {dados[4]}\n\n"
    f"📝 Resultados da Triagem:\n"
    f"• PHQ-9: {phq9} (Total: {phq9_score})\n"
    f"• GAD-7: {gad7} (Total: {gad7_score})\n\n"
    f"➡️ Interprete os escores de acordo com os critérios abaixo e inclua essa interpretação no relatório:\n\n"
    f"📊 **PHQ-9:**\n"
    f"• 0 a 4 → Mínimo\n"
    f"• 5 a 9 → Leve\n"
    f"• 10 a 14 → Moderado\n"
    f"• 15 a 19 → Moderadamente Grave\n"
    f"• 20 a 27 → Grave\n\n"
    f"📊 **GAD-7:**\n"
    f"• 0 a 4 → Mínimo\n"
    f"• 5 a 9 → Leve\n"
    f"• 10 a 14 → Moderado\n"
    f"• 15 a 21 → Grave\n\n"
    f"📅 Solicitação de Agendamento:\n"
    f"• Disponibilidade: {agendamento.get('disponibilidade')}\n"
    f"• Preferência: {agendamento.get('preferencia')}\n"
    f"• Observação: {agendamento.get('observacao')}\n\n"
    f"🕒 Data da Triagem: {data_hora}\n\n"
    f"Gere um relatório profissional, empático e acolhedor, destacando:\n"
    f"• O nível de severidade dos escores PHQ-9 e GAD-7, de acordo com a tabela.\n"
    f"• Se há pontos de atenção e se recomenda acompanhamento psicológico.\n"
    f"• NÃO forneça diagnóstico. Apenas informe os níveis e redija de forma humana e acolhedora."
)


    response = model.generate_content(prompt)
    relatorio = response.text



    payload = {
        "nome": dados[0],
        "idade": int(dados[1]),
        "matricula": dados[2],
        "curso": dados[3],
        "periodo": dados[4],
        "phq9_respostas": phq9,
        "phq9_score": phq9_score,
        "gad7_respostas": gad7,
        "gad7_score": gad7_score,
        "disponibilidade": agendamento.get("disponibilidade"),
        "observacao": agendamento.get("observacao"),
        "relatorio": relatorio,
        "telegram_id": str(update.effective_user.id)
    }

    headers = {
        "Content-Type": "application/json",
        "X-Bot-Secret": os.getenv("BOT_SHARED_SECRET")
    }

    r = requests.post("http://localhost:4000/api/screenings", json=payload, headers=headers)
    print(r.status_code, r.json())

# ----------- CANCELAR ------------

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Conversa encerrada. Você pode voltar digitando /menu ou /start.")
    return ConversationHandler.END

# ----------- MAIN ------------

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("menu", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, start)  # <- Menu aparece ao digitar qualquer coisa
        ],
        states={
            MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu)],
            DADOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, coletar_dados)],
            PHQ9: [MessageHandler(filters.Regex("^(0|1|2|3)$"), phq9)],
            GAD7: [MessageHandler(filters.Regex("^(0|1|2|3)$"), gad7)],
            AGENDAMENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, agendar)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(conv_handler)
    print("Bot está rodando...")
    app.run_polling()

if __name__ == "__main__":
    main()
