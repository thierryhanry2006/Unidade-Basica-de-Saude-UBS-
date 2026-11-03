import asyncio
from datetime import date, datetime

from database import (
    FUSO_LOCAL,
    STATUS_ENVIADO,
    STATUS_FALHA,
    criar_lembrete,
    inicializar_banco,
    obter_lembrete,
)
from scheduler import enviar_lembrete
from telegram.error import TelegramError


class BotFake:
    def __init__(self, falhar=False):
        self.falhar = falhar
        self.mensagens = []

    async def send_message(self, *, chat_id, text):
        if self.falhar:
            raise TelegramError("falha simulada")
        self.mensagens.append((chat_id, text))


def _criar_lembrete(caminho):
    inicializar_banco(caminho)
    return criar_lembrete(
        987654,
        "vip",
        date(2025, 1, 4),
        caminho=caminho,
        agora=FUSO_LOCAL.localize(datetime(2025, 1, 2, 8, 0)),
    )


def test_envia_aviso_e_marca_lembrete_como_enviado(tmp_path):
    caminho = tmp_path / "lembretes.sqlite3"
    lembrete = _criar_lembrete(caminho)
    bot = BotFake()

    asyncio.run(enviar_lembrete(bot, lembrete.id, caminho))

    registro = obter_lembrete(lembrete.id, caminho=caminho)
    assert registro.status == STATUS_ENVIADO
    assert bot.mensagens[0][0] == 987654
    assert "Poliomielite inativada (VIP)" in bot.mensagens[0][1]
    assert "meramente informativa" in bot.mensagens[0][1]


def test_falha_telegram_marca_lembrete_como_falha(tmp_path):
    caminho = tmp_path / "lembretes.sqlite3"
    lembrete = _criar_lembrete(caminho)

    asyncio.run(enviar_lembrete(BotFake(falhar=True), lembrete.id, caminho))

    assert obter_lembrete(lembrete.id, caminho=caminho).status == STATUS_FALHA
