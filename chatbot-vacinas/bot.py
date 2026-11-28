"""Bot Telegram para o protótipo de orientação vacinal."""

import asyncio
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from assistente import (
    RESPOSTA_FALHA,
    AssistenteClaude,
    AssistenteGemini,
    AssistenteGroq,
    Audio,
    ErroModelo,
    Memoria,
    transcritor_gemini,
    transcritor_groq,
)
from database import criar_lembrete
from ferramentas import ContextoExecucao
from motor_regras import calcular_proxima_dose
from pln import classificar_intencao
from scheduler import (
    agendar_lembrete,
    desagendar_lembrete,
    encerrar_agendador,
    iniciar_agendador,
)


ROOT_DIR = Path(__file__).resolve().parent
REGRAS_PATH = ROOT_DIR / "data" / "regras_pni.json"
FAQ_PATH = ROOT_DIR / "data" / "faq.json"
DATA_NASCIMENTO, VACINA, ULTIMA_DOSE, DATA_ULTIMA_DOSE, LEMBRETE = range(5)
MODO_TESTE = os.getenv("VACINA_MODO_TESTE", "0") == "1"
LIMITE_MENSAGEM_TELEGRAM = 4000
# Tempo máximo de uma resposta completa do assistente, incluindo ferramentas.
TEMPO_MAXIMO_RESPOSTA_SEGUNDOS = 90
LOGGER = logging.getLogger(__name__)

with REGRAS_PATH.open(encoding="utf-8") as arquivo:
    REGRAS = json.load(arquivo)
with FAQ_PATH.open(encoding="utf-8") as arquivo:
    FAQ = json.load(arquivo)


def _teclado_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Próxima dose", callback_data="proxima_dose")],
            [InlineKeyboardButton("Perguntas frequentes", callback_data="faq")],
            [InlineKeyboardButton("Falar com a unidade", callback_data="unidade")],
            [InlineKeyboardButton("Como chegar", callback_data="localizacao")],
        ]
    )


LEGENDA_CADERNETA = (
    "Caderneta da Criança (Ministério da Saúde): versão menina (lilás) e "
    "versão menino (verde)."
)


async def _enviar_foto(mensagem, nome_arquivo: str, legenda: str) -> None:
    caminho = ROOT_DIR / "data" / nome_arquivo
    if not caminho.exists():
        LOGGER.warning("Imagem %s não encontrada.", nome_arquivo)
        return
    with caminho.open("rb") as arquivo:
        await mensagem.reply_photo(photo=arquivo, caption=legenda)


async def _enviar_mapa(mensagem) -> None:
    """Envia o pino da UBS, que abre no app de mapas do celular."""
    local = FAQ.get("localizacao")
    if not local:
        return
    await mensagem.reply_venue(
        latitude=local["latitude"],
        longitude=local["longitude"],
        title=local["titulo"],
        address=local["endereco"],
    )


def _teclado_vacinas() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    vacina["nome"],
                    callback_data=f"vacina:{vacina['id']}",
                )
            ]
            for vacina in REGRAS["vacinas"]
        ]
    )


def _teclado_faq() -> InlineKeyboardMarkup:
    botoes = [
        [
            InlineKeyboardButton(
                item["pergunta"],
                callback_data=f"faq:{item['id']}",
            )
        ]
        for item in FAQ["perguntas"]
    ]
    botoes.append([InlineKeyboardButton("Voltar ao menu", callback_data="menu")])
    return InlineKeyboardMarkup(botoes)


def _mensagem_boas_vindas(com_assistente: bool = False) -> str:
    if com_assistente:
        return (
            "Olá! Sou o assistente virtual da UBS Maria Luiza (protótipo). "
            "Pode me escrever ou mandar um áudio com sua dúvida sobre a UBS ou "
            "sobre vacinas, ou usar os botões abaixo. "
            "Não envie nome, CPF ou outros dados de identificação."
        )
    return (
        "Olá! Sou o protótipo VACINA da UBS Maria Luiza. "
        "Não envie nome, CPF ou outros dados de identificação. "
        "Para simular uma orientação, use os botões abaixo."
    )


def _tem_assistente(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.application.bot_data.get("assistente") is not None


def _contexto_execucao(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> ContextoExecucao:
    agendador = context.application.bot_data.get("scheduler")
    caminho_banco = context.application.bot_data.get("db_path")

    def agendar(lembrete) -> None:
        if agendador is not None:
            agendar_lembrete(
                agendador, context.bot, lembrete, caminho_banco=caminho_banco
            )

    def desagendar(lembrete_id: int) -> None:
        if agendador is not None:
            desagendar_lembrete(agendador, lembrete_id)

    return ContextoExecucao(
        chat_id=update.effective_chat.id,
        regras=REGRAS,
        modo_teste=MODO_TESTE,
        caminho_banco=caminho_banco,
        agendar=agendar,
        desagendar=desagendar,
        # Datas calculadas continuam válidas para os próximos turnos da conversa.
        doses_calculadas=context.chat_data.setdefault("doses_calculadas", {}),
    )


async def _conversar_com_ia(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    entrada: str | Audio,
) -> None:
    assistente = context.application.bot_data["assistente"]
    memoria = context.chat_data.setdefault("memoria", Memoria())
    await update.effective_chat.send_action(ChatAction.TYPING)
    ctx = _contexto_execucao(update, context)
    try:
        resposta = await asyncio.wait_for(
            assistente.responder(entrada, memoria, ctx),
            timeout=TEMPO_MAXIMO_RESPOSTA_SEGUNDOS,
        )
    except ErroModelo as erro:
        LOGGER.error("Falha na API do modelo: %s", erro)
        resposta = RESPOSTA_FALHA
    except asyncio.TimeoutError:
        LOGGER.error("O modelo não respondeu dentro do tempo limite.")
        resposta = RESPOSTA_FALHA
    for inicio in range(0, len(resposta), LIMITE_MENSAGEM_TELEGRAM):
        await update.effective_message.reply_text(
            resposta[inicio : inicio + LIMITE_MENSAGEM_TELEGRAM]
        )
    if ctx.localizacao_solicitada:
        await _enviar_mapa(update.effective_message)
    if ctx.caderneta_solicitada:
        await _enviar_foto(
            update.effective_message, "caderneta_crianca.jpg", LEGENDA_CADERNETA
        )


async def iniciar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Comando /start: recomeça a conversa, apagando a memória do assistente."""
    context.chat_data.pop("memoria", None)
    context.chat_data.pop("doses_calculadas", None)
    return await menu_principal(update, context)


async def receber_audio(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    assistente = context.application.bot_data.get("assistente")
    transcritor = context.application.bot_data.get("transcritor")
    if assistente is None or (not assistente.aceita_audio and transcritor is None):
        await update.effective_message.reply_text(
            "Ainda não consigo ouvir áudios. Escreva sua dúvida ou use /start."
        )
        return
    midia = update.effective_message.voice or update.effective_message.audio
    arquivo = await midia.get_file()
    audio = Audio(
        dados=bytes(await arquivo.download_as_bytearray()),
        mime=midia.mime_type or "audio/ogg",
    )
    if assistente.aceita_audio:
        await _conversar_com_ia(update, context, audio)
        return

    # O modelo principal não recebe áudio: transcreve antes de conversar.
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        texto = await transcritor(audio)
    except ErroModelo as erro:
        LOGGER.error("Falha ao transcrever áudio: %s", erro)
        texto = ""
    if not texto:
        await update.effective_message.reply_text(
            "Não consegui entender o áudio. Pode escrever sua dúvida?"
        )
        return
    await update.effective_message.reply_text(f"Entendi: \"{texto}\"")
    await _conversar_com_ia(update, context, texto)


async def menu_principal(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        mensagem = update.callback_query.message
    else:
        mensagem = update.effective_message

    if mensagem is not None:
        await mensagem.reply_text(
            _mensagem_boas_vindas(_tem_assistente(context)),
            reply_markup=_teclado_menu(),
        )
    return ConversationHandler.END


async def iniciar_proxima_dose(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.message.reply_text(
        "Informe sua data de nascimento no formato DD/MM/AAAA. "
        "Não envie nome ou CPF."
    )
    return DATA_NASCIMENTO


async def interpretar_texto_livre(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if _tem_assistente(context):
        await _conversar_com_ia(
            update,
            context,
            update.effective_message.text,
        )
        return ConversationHandler.END

    classificacao = classificar_intencao(update.effective_message.text)
    if classificacao.intencao == "proxima_dose":
        context.user_data.clear()
        await update.effective_message.reply_text(
            "Entendi que você quer consultar uma próxima dose."
        )
        await update.effective_message.reply_text(
            "Informe sua data de nascimento no formato DD/MM/AAAA. "
            "Não envie nome ou CPF."
        )
        return DATA_NASCIMENTO

    if classificacao.intencao == "faq":
        await update.effective_message.reply_text(
            "Entendi que você tem uma dúvida administrativa. "
            "Escolha uma pergunta frequente:",
            reply_markup=_teclado_faq(),
        )
        return ConversationHandler.END

    if classificacao.intencao == "falar_com_unidade":
        await update.effective_message.reply_text(FAQ["contato_unidade"])
        await _enviar_mapa(update.effective_message)
        return ConversationHandler.END

    await update.effective_message.reply_text(
        "Não consegui identificar o assunto. Escolha uma opção no menu:"
    )
    await update.effective_message.reply_text(
        _mensagem_boas_vindas(),
        reply_markup=_teclado_menu(),
    )
    return ConversationHandler.END


async def receber_data_nascimento(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        nascimento = datetime.strptime(
            update.effective_message.text.strip(), "%d/%m/%Y"
        ).date()
    except ValueError:
        await update.effective_message.reply_text(
            "Não consegui interpretar a data. Informe no formato DD/MM/AAAA."
        )
        return DATA_NASCIMENTO

    if nascimento > date.today():
        await update.effective_message.reply_text(
            "A data de nascimento não pode estar no futuro. "
            "Informe novamente no formato DD/MM/AAAA."
        )
        return DATA_NASCIMENTO

    context.user_data["data_nascimento"] = nascimento
    await update.effective_message.reply_text(
        "Escolha a vacina:",
        reply_markup=_teclado_vacinas(),
    )
    return VACINA


async def escolher_vacina(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    vacina_id = query.data.partition(":")[2]
    vacina = next(
        (item for item in REGRAS["vacinas"] if item["id"] == vacina_id),
        None,
    )
    if vacina is None:
        await query.message.reply_text(
            REGRAS["orientacao_segura"]["fora_do_escopo"]
        )
        context.user_data.clear()
        return ConversationHandler.END

    context.user_data["vacina_id"] = vacina_id
    await query.message.reply_text(
        f"Qual foi o número da última dose de {vacina['nome']}? "
        "Informe apenas o número (por exemplo, 1, 2 ou 3)."
    )
    return ULTIMA_DOSE


async def receber_ultima_dose(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        ultima_dose = int(update.effective_message.text.strip())
    except ValueError:
        await update.effective_message.reply_text(
            "Informe o número da última dose usando algarismos."
        )
        return ULTIMA_DOSE

    if ultima_dose < 1:
        await update.effective_message.reply_text(
            "O número da dose deve ser maior que zero. Informe novamente."
        )
        return ULTIMA_DOSE

    context.user_data["ultima_dose"] = ultima_dose
    await update.effective_message.reply_text(
        "Informe a data de aplicação dessa dose no formato DD/MM/AAAA."
    )
    return DATA_ULTIMA_DOSE


async def receber_data_ultima_dose(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        data_ultima_dose = datetime.strptime(
            update.effective_message.text.strip(), "%d/%m/%Y"
        ).date()
    except ValueError:
        await update.effective_message.reply_text(
            "Não consegui interpretar a data. Informe no formato DD/MM/AAAA."
        )
        return DATA_ULTIMA_DOSE

    if data_ultima_dose > date.today():
        await update.effective_message.reply_text(
            "A data de aplicação não pode estar no futuro. "
            "Informe novamente no formato DD/MM/AAAA."
        )
        return DATA_ULTIMA_DOSE

    if not REGRAS.get("liberado_para_uso_em_producao", False) and not MODO_TESTE:
        await update.effective_message.reply_text(
            "As regras vacinais deste protótipo ainda aguardam validação clínica "
            "da UBS Maria Luiza; nenhuma data foi calculada ou recomendada. "
            + REGRAS["orientacao_segura"]["fora_do_escopo"]
            + "\n"
            + REGRAS["orientacao_segura"]["aviso_obrigatorio"]
        )
        context.user_data.clear()
        return ConversationHandler.END

    resultado = calcular_proxima_dose(
        context.user_data["data_nascimento"],
        context.user_data["vacina_id"],
        context.user_data["ultima_dose"],
        data_ultima_dose,
    )

    if resultado.status == "proxima_dose":
        context.user_data.clear()
        context.user_data["lembrete_pendente"] = {
            "vacina_id": resultado.vacina_id,
            "data_prevista": resultado.data_proxima_dose,
        }
        prefixo = (
            "SIMULAÇÃO DO PROTÓTIPO — regras preliminares. "
            if resultado.validacao_clinica_pendente
            else ""
        )
        resposta = (
            f"{prefixo}A data calculada para a dose {resultado.dose_seguinte} "
            f"é {resultado.data_proxima_dose:%d/%m/%Y}.\n"
            f"{resultado.aviso_seguranca}"
        )
        await update.effective_message.reply_text(resposta)
        await update.effective_message.reply_text(
            "Você gostaria de receber um lembrete automático no dia anterior "
            "à data prevista, às 09:00 (horário de Riachão-MA)? "
            "Se aceitar, o bot armazenará o chat_id, a vacina e as datas "
            "necessárias para enviar o aviso.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Sim", callback_data="lembrete:sim"),
                        InlineKeyboardButton("Não", callback_data="lembrete:nao"),
                    ]
                ]
            ),
        )
        return LEMBRETE

    context.user_data.clear()
    await update.effective_message.reply_text(
        f"{resultado.mensagem}\n{resultado.aviso_seguranca}"
    )
    return await menu_principal(update, context)


async def responder_lembrete(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "lembrete:sim":
        dados_lembrete = context.user_data.get("lembrete_pendente")
        agendador = context.application.bot_data.get("scheduler")
        caminho_banco = context.application.bot_data.get("db_path")
        conversa = update.effective_chat
        if (
            dados_lembrete is None
            or agendador is None
            or caminho_banco is None
            or conversa is None
        ):
            await query.message.reply_text(
                "Não foi possível confirmar o agendamento. "
                "Nenhum lembrete foi confirmado; procure a recepção da UBS."
            )
            return await menu_principal(update, context)

        try:
            lembrete = criar_lembrete(
                conversa.id,
                dados_lembrete["vacina_id"],
                dados_lembrete["data_prevista"],
                caminho=caminho_banco,
            )
        except (TypeError, ValueError) as erro:
            await query.message.reply_text(
                f"Não foi possível agendar o lembrete: {erro}"
            )
            return await menu_principal(update, context)

        agendar_lembrete(
            agendador,
            context.bot,
            lembrete,
            caminho_banco=caminho_banco,
        )
        prefixo = (
            "SIMULAÇÃO DO PROTÓTIPO — "
            if not REGRAS.get("liberado_para_uso_em_producao", False)
            else ""
        )
        await query.message.reply_text(
            f"{prefixo}Lembrete agendado para "
            f"{lembrete.data_lembrete:%d/%m/%Y às %H:%M} "
            "(horário de Riachão-MA)."
        )
    else:
        await query.message.reply_text("Tudo bem. Nenhum lembrete foi agendado.")
    return await menu_principal(update, context)


async def abrir_faq(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "Escolha uma pergunta frequente:",
        reply_markup=_teclado_faq(),
    )
    return ConversationHandler.END


async def responder_faq(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    item_id = query.data.partition(":")[2]
    item = next(
        (item for item in FAQ["perguntas"] if item["id"] == item_id),
        None,
    )
    if item is None:
        await query.message.reply_text(
            REGRAS["orientacao_segura"]["fora_do_escopo"]
        )
    else:
        await query.message.reply_text(item["resposta"])
        if item.get("imagem"):
            await _enviar_foto(
                query.message, item["imagem"], item.get("legenda_imagem", "")
            )
    await query.message.reply_text(
        "Perguntas frequentes:",
        reply_markup=_teclado_faq(),
    )
    return ConversationHandler.END


async def falar_com_unidade(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(FAQ["contato_unidade"])
    await _enviar_mapa(query.message)
    return ConversationHandler.END


async def como_chegar(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    local = FAQ.get("localizacao")
    if local:
        await query.message.reply_text(
            f"A {local['titulo']} fica na {local['endereco']}. "
            "Toque no mapa abaixo para abrir a rota no seu celular."
        )
    await _enviar_mapa(query.message)
    return ConversationHandler.END


async def cancelar(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text("Fluxo cancelado.")
    return await menu_principal(update, context)


async def tratar_erro(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    context.user_data.clear()
    erro = context.error
    info_erro = (
        (type(erro), erro, erro.__traceback__)
        if erro is not None
        else None
    )
    LOGGER.error(
        "Falha ao processar atualização do Telegram",
        exc_info=info_erro,
    )
    if isinstance(update, Update) and update.effective_message is not None:
        await update.effective_message.reply_text(
            "Não foi possível concluir a solicitação. Se você pediu um lembrete, "
            "não considere o agendamento confirmado; procure a recepção da UBS."
        )


def criar_aplicacao(
    token: str,
    assistente: AssistenteClaude | AssistenteGroq | AssistenteGemini | None = None,
    transcritor=None,
) -> Application:
    conversa = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(iniciar_proxima_dose, pattern="^proxima_dose$"),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                interpretar_texto_livre,
            ),
        ],
        states={
            DATA_NASCIMENTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_data_nascimento)
            ],
            VACINA: [
                CallbackQueryHandler(escolher_vacina, pattern="^vacina:")
            ],
            ULTIMA_DOSE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_ultima_dose)
            ],
            DATA_ULTIMA_DOSE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receber_data_ultima_dose,
                )
            ],
            LEMBRETE: [
                CallbackQueryHandler(responder_lembrete, pattern="^lembrete:")
            ],
        },
        fallbacks=[
            CommandHandler("start", iniciar),
            CommandHandler("cancelar", cancelar),
            CallbackQueryHandler(menu_principal, pattern="^menu$"),
            CallbackQueryHandler(iniciar_proxima_dose, pattern="^proxima_dose$"),
            CallbackQueryHandler(abrir_faq, pattern="^faq$"),
            CallbackQueryHandler(responder_faq, pattern="^faq:"),
            CallbackQueryHandler(falar_com_unidade, pattern="^unidade$"),
            CallbackQueryHandler(como_chegar, pattern="^localizacao$"),
        ],
    )
    aplicacao = (
        Application.builder()
        .token(token)
        .post_init(iniciar_agendador)
        .post_shutdown(encerrar_agendador)
        .build()
    )
    aplicacao.bot_data["assistente"] = assistente
    aplicacao.bot_data["transcritor"] = transcritor
    aplicacao.add_handler(conversa)
    aplicacao.add_handler(CommandHandler("start", iniciar))
    aplicacao.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, receber_audio)
    )
    aplicacao.add_handler(CallbackQueryHandler(abrir_faq, pattern="^faq$"))
    aplicacao.add_handler(CallbackQueryHandler(responder_faq, pattern="^faq:"))
    aplicacao.add_handler(CallbackQueryHandler(falar_com_unidade, pattern="^unidade$"))
    aplicacao.add_handler(CallbackQueryHandler(como_chegar, pattern="^localizacao$"))
    aplicacao.add_error_handler(tratar_erro)
    return aplicacao


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Defina a variável de ambiente TELEGRAM_BOT_TOKEN.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # O httpx registra a URL completa da API do Telegram, que contém o token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    chave_claude = os.getenv("ANTHROPIC_API_KEY")
    chave_groq = os.getenv("GROQ_API_KEY")
    chave_gemini = os.getenv("GEMINI_API_KEY")
    assistente = None
    transcritor = None
    if chave_groq:
        transcritor = transcritor_groq(
            chave_groq, os.getenv("GROQ_TRANSCRIPTION_MODEL")
        )
    elif chave_gemini:
        transcritor = transcritor_gemini(chave_gemini, os.getenv("GEMINI_MODEL"))

    if chave_claude:
        assistente = AssistenteClaude.com_api(
            chave_claude,
            REGRAS,
            modelo=os.getenv("CLAUDE_MODEL"),
            esforco=os.getenv("CLAUDE_EFFORT", "low"),
        )
        LOGGER.info("Assistente ativado com Claude.")
    elif chave_groq:
        assistente = AssistenteGroq.com_api(
            chave_groq, REGRAS, modelo=os.getenv("GROQ_MODEL")
        )
        LOGGER.info("Assistente ativado com Groq.")
    elif chave_gemini:
        assistente = AssistenteGemini.com_api(
            chave_gemini,
            REGRAS,
            modelo=os.getenv("GEMINI_MODEL"),
            modelo_reserva=os.getenv("GEMINI_MODEL_RESERVA"),
        )
        transcritor = None  # o Gemini entende áudio diretamente
        LOGGER.info("Assistente ativado com Gemini.")
    else:
        LOGGER.warning(
            "Nenhuma chave de modelo definida: usando o classificador local de intenções."
        )
    if assistente is not None and not assistente.aceita_audio:
        LOGGER.info(
            "Áudio: %s.",
            "transcrito antes da resposta" if transcritor else "desativado",
        )
    criar_aplicacao(token, assistente, transcritor).run_polling()


if __name__ == "__main__":
    main()
