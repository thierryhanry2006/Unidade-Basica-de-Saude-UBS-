"""Agendamento de lembretes no fuso local da UBS Centenário."""

import logging
import json
import os
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.error import TelegramError

from database import (
    CAMINHO_BANCO_PADRAO,
    FUSO_LOCAL,
    Lembrete,
    STATUS_ENVIADO,
    STATUS_FALHA,
    atualizar_status,
    expirar_lembretes_vencidos,
    inicializar_banco,
    listar_lembretes_pendentes,
    obter_lembrete,
)


LOGGER = logging.getLogger(__name__)
REGRAS_PATH = Path(__file__).resolve().parent / "data" / "regras_pni.json"

with REGRAS_PATH.open(encoding="utf-8") as arquivo:
    REGRAS = json.load(arquivo)
NOMES_VACINAS = {item["id"]: item["nome"] for item in REGRAS["vacinas"]}


def agendar_lembrete(
    agendador: AsyncIOScheduler,
    bot: Bot,
    lembrete: Lembrete,
    *,
    caminho_banco: Path = CAMINHO_BANCO_PADRAO,
) -> None:
    agendador.add_job(
        enviar_lembrete,
        trigger="date",
        run_date=lembrete.data_lembrete,
        args=[bot, lembrete.id, caminho_banco],
        id=f"vacina-lembrete-{lembrete.id}",
        replace_existing=True,
        misfire_grace_time=14 * 60 * 60,
    )


async def enviar_lembrete(
    bot: Bot,
    lembrete_id: int,
    caminho_banco: Path = CAMINHO_BANCO_PADRAO,
) -> None:
    lembrete = obter_lembrete(lembrete_id, caminho=caminho_banco)
    if lembrete is None or lembrete.status != "pendente":
        LOGGER.info("Lembrete %s não está pendente; envio ignorado.", lembrete_id)
        return

    nome_vacina = NOMES_VACINAS.get(lembrete.vacina_id)
    if nome_vacina is None:
        atualizar_status(
            lembrete.id,
            STATUS_FALHA,
            caminho=caminho_banco,
        )
        LOGGER.error(
            "Lembrete %s referencia uma vacina ausente nas regras.",
            lembrete.id,
        )
        return

    prefixo = (
        "SIMULAÇÃO DO PROTÓTIPO — regras preliminares. "
        if not REGRAS.get("liberado_para_uso_em_producao", False)
        else ""
    )
    mensagem = (
        f"{prefixo}Lembrete da UBS Centenário: está prevista para "
        f"{lembrete.data_prevista:%d/%m/%Y} a próxima dose de {nome_vacina}. "
        "Esta mensagem é meramente informativa. A confirmação final deve ser "
        "feita pela equipe da sala de vacina da UBS Centenário."
    )
    try:
        await bot.send_message(chat_id=lembrete.chat_id, text=mensagem)
    except TelegramError as erro:
        atualizar_status(
            lembrete.id,
            STATUS_FALHA,
            caminho=caminho_banco,
        )
        LOGGER.error(
            "Falha Telegram ao enviar lembrete %s: %s",
            lembrete.id,
            erro,
        )
        return

    atualizado = atualizar_status(
        lembrete.id,
        STATUS_ENVIADO,
        caminho=caminho_banco,
    )
    if not atualizado:
        LOGGER.error(
            "Lembrete %s foi enviado, mas seu status não pôde ser atualizado.",
            lembrete.id,
        )


async def iniciar_agendador(aplicacao) -> None:
    caminho_banco = Path(os.getenv("VACINA_DB_PATH", str(CAMINHO_BANCO_PADRAO)))
    inicializar_banco(caminho_banco)
    expirar_lembretes_vencidos(caminho=caminho_banco)

    agendador = AsyncIOScheduler(timezone=FUSO_LOCAL)
    agendador.start()
    aplicacao.bot_data["scheduler"] = agendador
    aplicacao.bot_data["db_path"] = caminho_banco

    for lembrete in listar_lembretes_pendentes(caminho=caminho_banco):
        agendar_lembrete(
            agendador,
            aplicacao.bot,
            lembrete,
            caminho_banco=caminho_banco,
        )


async def encerrar_agendador(aplicacao) -> None:
    agendador = aplicacao.bot_data.get("scheduler")
    if agendador is not None and agendador.running:
        agendador.shutdown(wait=False)
