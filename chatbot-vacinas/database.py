"""Persistência mínima de lembretes sem armazenar dados pessoais identificáveis."""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterator

import pytz


FUSO_LOCAL = pytz.timezone("America/Fortaleza")
CAMINHO_BANCO_PADRAO = Path(__file__).resolve().parent / "data" / "lembretes.sqlite3"
STATUS_PENDENTE = "pendente"
STATUS_ENVIADO = "enviado"
STATUS_FALHA = "falha"
STATUS_EXPIRADO = "expirado"


@dataclass(frozen=True)
class Lembrete:
    id: int
    chat_id: int
    vacina_id: str
    data_prevista: date
    data_lembrete: datetime
    status: str


@contextmanager
def _conexao(caminho: Path) -> Iterator[sqlite3.Connection]:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(caminho)
    conexao.row_factory = sqlite3.Row
    try:
        with conexao:
            yield conexao
    finally:
        conexao.close()


def inicializar_banco(caminho: Path = CAMINHO_BANCO_PADRAO) -> None:
    with _conexao(caminho) as conexao:
        conexao.execute(
            """
            CREATE TABLE IF NOT EXISTS lembretes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                vacina_id TEXT NOT NULL,
                data_prevista TEXT NOT NULL,
                data_lembrete TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('pendente', 'enviado', 'falha', 'expirado')
                )
            )
            """
        )
        conexao.execute(
            "CREATE INDEX IF NOT EXISTS idx_lembretes_pendentes "
            "ON lembretes(status, data_lembrete)"
        )


def criar_lembrete(
    chat_id: int,
    vacina_id: str,
    data_prevista: date,
    *,
    caminho: Path = CAMINHO_BANCO_PADRAO,
    agora: datetime | None = None,
) -> Lembrete:
    if isinstance(chat_id, bool) or not isinstance(chat_id, int) or chat_id == 0:
        raise ValueError("chat_id do Telegram inválido.")
    if not isinstance(vacina_id, str) or not vacina_id.strip():
        raise ValueError("vacina_id não pode ser vazio.")
    if isinstance(data_prevista, datetime) or not isinstance(data_prevista, date):
        raise TypeError("data_prevista deve ser datetime.date.")

    instante_atual = agora or datetime.now(FUSO_LOCAL)
    if instante_atual.tzinfo is None or instante_atual.utcoffset() is None:
        raise ValueError("agora deve conter fuso horário.")
    instante_atual = instante_atual.astimezone(FUSO_LOCAL)

    dia_lembrete = data_prevista - timedelta(days=1)
    data_lembrete = FUSO_LOCAL.localize(
        datetime.combine(dia_lembrete, time(hour=9))
    )
    if data_lembrete <= instante_atual:
        raise ValueError(
            "O horário do lembrete de um dia antes já passou; "
            "nenhum lembrete foi criado."
        )

    with _conexao(caminho) as conexao:
        cursor = conexao.execute(
            """
            INSERT INTO lembretes
                (chat_id, vacina_id, data_prevista, data_lembrete, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                vacina_id,
                data_prevista.isoformat(),
                data_lembrete.isoformat(),
                STATUS_PENDENTE,
            ),
        )
        lembrete_id = cursor.lastrowid

    return Lembrete(
        id=lembrete_id,
        chat_id=chat_id,
        vacina_id=vacina_id,
        data_prevista=data_prevista,
        data_lembrete=data_lembrete,
        status=STATUS_PENDENTE,
    )


def _mapear_lembrete(linha: sqlite3.Row) -> Lembrete:
    return Lembrete(
        id=linha["id"],
        chat_id=linha["chat_id"],
        vacina_id=linha["vacina_id"],
        data_prevista=date.fromisoformat(linha["data_prevista"]),
        data_lembrete=datetime.fromisoformat(linha["data_lembrete"]),
        status=linha["status"],
    )


def obter_lembrete(
    lembrete_id: int, *, caminho: Path = CAMINHO_BANCO_PADRAO
) -> Lembrete | None:
    with _conexao(caminho) as conexao:
        linha = conexao.execute(
            "SELECT * FROM lembretes WHERE id = ?",
            (lembrete_id,),
        ).fetchone()
    return _mapear_lembrete(linha) if linha is not None else None


def listar_lembretes_pendentes(
    *, caminho: Path = CAMINHO_BANCO_PADRAO
) -> list[Lembrete]:
    with _conexao(caminho) as conexao:
        linhas = conexao.execute(
            "SELECT * FROM lembretes WHERE status = ? ORDER BY data_lembrete",
            (STATUS_PENDENTE,),
        ).fetchall()
    return [_mapear_lembrete(linha) for linha in linhas]


def atualizar_status(
    lembrete_id: int,
    status: str,
    *,
    caminho: Path = CAMINHO_BANCO_PADRAO,
) -> bool:
    status_validos = {
        STATUS_PENDENTE,
        STATUS_ENVIADO,
        STATUS_FALHA,
        STATUS_EXPIRADO,
    }
    if status not in status_validos:
        raise ValueError(f"Status de lembrete inválido: {status}.")

    with _conexao(caminho) as conexao:
        cursor = conexao.execute(
            "UPDATE lembretes SET status = ? WHERE id = ? AND status = ?",
            (status, lembrete_id, STATUS_PENDENTE),
        )
    return cursor.rowcount == 1


def expirar_lembretes_vencidos(
    *,
    caminho: Path = CAMINHO_BANCO_PADRAO,
    agora: datetime | None = None,
) -> int:
    instante_atual = agora or datetime.now(FUSO_LOCAL)
    if instante_atual.tzinfo is None or instante_atual.utcoffset() is None:
        raise ValueError("agora deve conter fuso horário.")
    limite = instante_atual.astimezone(FUSO_LOCAL)

    pendentes = listar_lembretes_pendentes(caminho=caminho)
    vencidos = [
        item.id for item in pendentes if item.data_lembrete <= limite
    ]
    if not vencidos:
        return 0

    with _conexao(caminho) as conexao:
        conexao.executemany(
            "UPDATE lembretes SET status = ? WHERE id = ? AND status = ?",
            [
                (STATUS_EXPIRADO, lembrete_id, STATUS_PENDENTE)
                for lembrete_id in vencidos
            ],
        )
    return len(vencidos)
