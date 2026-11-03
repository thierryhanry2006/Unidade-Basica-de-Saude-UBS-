import sqlite3
from datetime import date, datetime

import pytest

from database import (
    FUSO_LOCAL,
    STATUS_EXPIRADO,
    STATUS_PENDENTE,
    atualizar_status,
    criar_lembrete,
    expirar_lembretes_vencidos,
    inicializar_banco,
    listar_lembretes_pendentes,
    obter_lembrete,
)


def test_persiste_apenas_dados_necessarios_e_calcula_envio_local(tmp_path):
    caminho = tmp_path / "lembretes.sqlite3"
    inicializar_banco(caminho)
    agora = FUSO_LOCAL.localize(datetime(2025, 1, 1, 8, 0))

    lembrete = criar_lembrete(
        123456,
        "hepatite_b",
        date(2025, 1, 2),
        caminho=caminho,
        agora=agora,
    )

    assert lembrete.data_lembrete == FUSO_LOCAL.localize(
        datetime(2025, 1, 1, 9, 0)
    )
    assert lembrete.status == STATUS_PENDENTE
    with sqlite3.connect(caminho) as conexao:
        colunas = {
            linha[1]
            for linha in conexao.execute("PRAGMA table_info(lembretes)")
        }
    assert colunas == {
        "id",
        "chat_id",
        "vacina_id",
        "data_prevista",
        "data_lembrete",
        "status",
    }


def test_nao_cria_lembrete_quando_o_horario_de_envio_ja_passou(tmp_path):
    caminho = tmp_path / "lembretes.sqlite3"
    inicializar_banco(caminho)

    with pytest.raises(ValueError, match="já passou"):
        criar_lembrete(
            123456,
            "vip",
            date(2025, 1, 2),
            caminho=caminho,
            agora=FUSO_LOCAL.localize(datetime(2025, 1, 1, 9, 0)),
        )

    assert obter_lembrete(1, caminho=caminho) is None


def test_expira_lembretes_vencidos_e_preserva_os_futuros(tmp_path):
    caminho = tmp_path / "lembretes.sqlite3"
    inicializar_banco(caminho)
    vencido = criar_lembrete(
        111,
        "vip",
        date(2025, 1, 4),
        caminho=caminho,
        agora=FUSO_LOCAL.localize(datetime(2025, 1, 2, 8, 0)),
    )
    futuro = criar_lembrete(
        222,
        "dt",
        date(2025, 1, 5),
        caminho=caminho,
        agora=FUSO_LOCAL.localize(datetime(2025, 1, 2, 8, 0)),
    )

    quantidade = expirar_lembretes_vencidos(
        caminho=caminho,
        agora=FUSO_LOCAL.localize(datetime(2025, 1, 3, 10, 0)),
    )

    assert quantidade == 1
    assert obter_lembrete(vencido.id, caminho=caminho).status == STATUS_EXPIRADO
    assert [item.id for item in listar_lembretes_pendentes(caminho=caminho)] == [
        futuro.id
    ]


def test_atualiza_status_apenas_uma_vez(tmp_path):
    caminho = tmp_path / "lembretes.sqlite3"
    inicializar_banco(caminho)
    lembrete = criar_lembrete(
        123456,
        "dt",
        date(2025, 1, 4),
        caminho=caminho,
        agora=FUSO_LOCAL.localize(datetime(2025, 1, 2, 8, 0)),
    )

    assert atualizar_status(lembrete.id, "enviado", caminho=caminho) is True
    assert atualizar_status(lembrete.id, "falha", caminho=caminho) is False
