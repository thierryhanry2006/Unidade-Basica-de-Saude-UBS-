"""Bot Telegram para o protótipo de orientação vacinal."""

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
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import criar_lembrete
from motor_regras import calcular_proxima_dose
from pln import classificar_intencao
from scheduler import (
    agendar_lembrete,
    encerrar_agendador,
    iniciar_agendador,
)


ROOT_DIR = Path(__file__).resolve().parent
REGRAS_PATH = ROOT_DIR / "data" / "regras_pni.json"
FAQ_PATH = ROOT_DIR / "data" / "faq.json"
DATA_NASCIMENTO, VACINA, ULTIMA_DOSE, DATA_ULTIMA_DOSE, LEMBRETE = range(5)
MODO_TESTE = os.getenv("VACINA_MODO_TESTE", "0") == "1"
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
        ]
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


def _mensagem_boas_vindas() -> str:
    return (
        "Olá! Sou o protótipo VACINA da UBS Centenário. "
        "Não envie nome, CPF ou outros dados de identificação. "
        "Para simular uma orientação, use os botões abaixo."
    )


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
            _mensagem_boas_vindas(),
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
            "da UBS Centenário; nenhuma data foi calculada ou recomendada. "
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


def criar_aplicacao(token: str) -> Application:
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
            CommandHandler("start", menu_principal),
            CommandHandler("cancelar", cancelar),
            CallbackQueryHandler(menu_principal, pattern="^menu$"),
            CallbackQueryHandler(iniciar_proxima_dose, pattern="^proxima_dose$"),
            CallbackQueryHandler(abrir_faq, pattern="^faq$"),
            CallbackQueryHandler(responder_faq, pattern="^faq:"),
            CallbackQueryHandler(falar_com_unidade, pattern="^unidade$"),
        ],
    )
    aplicacao = (
        Application.builder()
        .token(token)
        .post_init(iniciar_agendador)
        .post_shutdown(encerrar_agendador)
        .build()
    )
    aplicacao.add_handler(conversa)
    aplicacao.add_handler(CommandHandler("start", menu_principal))
    aplicacao.add_handler(CallbackQueryHandler(abrir_faq, pattern="^faq$"))
    aplicacao.add_handler(CallbackQueryHandler(responder_faq, pattern="^faq:"))
    aplicacao.add_handler(CallbackQueryHandler(falar_com_unidade, pattern="^unidade$"))
    aplicacao.add_error_handler(tratar_erro)
    return aplicacao


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Defina a variável de ambiente TELEGRAM_BOT_TOKEN.")

    logging.basicConfig(level=logging.INFO)
    criar_aplicacao(token).run_polling()


if __name__ == "__main__":
    main()
