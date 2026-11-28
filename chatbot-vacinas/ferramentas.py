"""Ferramentas que o modelo de linguagem pode acionar no sistema.

O modelo nunca calcula datas nem grava dados por conta própria: ele pede a
execução de uma destas funções, que reutilizam o motor de regras e o banco de
lembretes já testados. Cada função devolve um dicionário simples, que é
reenviado ao modelo como resultado da ferramenta.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

from database import cancelar_lembrete, criar_lembrete, listar_lembretes_do_chat
from motor_regras import calcular_proxima_dose


@dataclass
class ContextoExecucao:
    """Dados de uma conversa necessários para executar as ferramentas."""

    chat_id: int
    regras: dict
    modo_teste: bool
    caminho_banco: Path | None = None
    agendar: Callable[[Any], None] | None = None
    desagendar: Callable[[int], None] | None = None
    # Datas calculadas pelo motor nesta conversa: só elas podem virar lembrete.
    doses_calculadas: dict[str, date] = field(default_factory=dict)
    hoje: date | None = None
    # Marcado pela ferramenta enviar_localizacao; o bot envia o mapa depois do texto.
    localizacao_solicitada: bool = False
    # Marcado pela ferramenta enviar_foto_caderneta; o bot envia a foto depois do texto.
    caderneta_solicitada: bool = False


def _ids_vacinas(regras: dict) -> list[str]:
    return [vacina["id"] for vacina in regras["vacinas"]]


def declaracoes(regras: dict) -> list[dict]:
    """Descrição das ferramentas no formato JSON Schema aceito pelo modelo."""
    return [
        {
            "name": "calcular_proxima_dose",
            "description": (
                "Calcula a data prevista da próxima dose de uma vacina usando as "
                "regras cadastradas da UBS. Use SEMPRE esta ferramenta para "
                "qualquer data de dose; nunca calcule datas por conta própria. "
                "Antes de chamar, obtenha do usuário a data de nascimento de quem "
                "vai se vacinar, a vacina, o número da última dose recebida e a "
                "data dessa dose."
            ),
            "parameters_json_schema": {
                "type": "object",
                "properties": {
                    "data_nascimento": {
                        "type": "string",
                        "description": "Data de nascimento no formato AAAA-MM-DD.",
                    },
                    "vacina_id": {
                        "type": "string",
                        "enum": _ids_vacinas(regras),
                        "description": "Identificador da vacina cadastrada.",
                    },
                    "ultima_dose": {
                        "type": "integer",
                        "description": "Número da última dose recebida (1, 2, 3...).",
                    },
                    "data_ultima_dose": {
                        "type": "string",
                        "description": "Data da última dose no formato AAAA-MM-DD.",
                    },
                },
                "required": [
                    "data_nascimento",
                    "vacina_id",
                    "ultima_dose",
                    "data_ultima_dose",
                ],
            },
        },
        {
            "name": "agendar_lembrete",
            "description": (
                "Agenda um lembrete no Telegram para o dia anterior à próxima dose, "
                "às 09:00. Só funciona para uma vacina cuja data já foi calculada "
                "com calcular_proxima_dose nesta conversa. Chame apenas depois que "
                "o usuário disser claramente que quer o lembrete."
            ),
            "parameters_json_schema": {
                "type": "object",
                "properties": {
                    "vacina_id": {
                        "type": "string",
                        "enum": _ids_vacinas(regras),
                    },
                },
                "required": ["vacina_id"],
            },
        },
        {
            "name": "enviar_localizacao",
            "description": (
                "Envia ao usuário o mapa com a localização da UBS, que abre no app "
                "de mapas para traçar a rota. Use quando a pessoa perguntar onde "
                "fica a UBS ou como chegar. O mapa aparece logo após sua resposta."
            ),
            "parameters_json_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "enviar_foto_caderneta",
            "description": (
                "Envia ao usuário a foto da Caderneta da Criança do Ministério da "
                "Saúde (versões menina e menino). Use quando a pessoa perguntar sobre "
                "a caderneta ou carteirinha da criança. A foto aparece logo após sua "
                "resposta."
            ),
            "parameters_json_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "listar_meus_lembretes",
            "description": "Lista os lembretes pendentes do usuário desta conversa.",
            "parameters_json_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "cancelar_lembrete",
            "description": (
                "Cancela e apaga um lembrete pendente do usuário. Use o id "
                "retornado por listar_meus_lembretes e confirme com o usuário "
                "antes de cancelar."
            ),
            "parameters_json_schema": {
                "type": "object",
                "properties": {"lembrete_id": {"type": "integer"}},
                "required": ["lembrete_id"],
            },
        },
    ]


def _data(valor: Any, campo: str) -> date:
    if not isinstance(valor, str):
        raise ValueError(f"{campo} deve ser uma data no formato AAAA-MM-DD.")
    try:
        return date.fromisoformat(valor)
    except ValueError as erro:
        raise ValueError(f"{campo} deve ser uma data no formato AAAA-MM-DD.") from erro


def _nome_vacina(regras: dict, vacina_id: str) -> str:
    return next(
        (v["nome"] for v in regras["vacinas"] if v["id"] == vacina_id),
        vacina_id,
    )


def _calcular(ctx: ContextoExecucao, args: dict) -> dict:
    nascimento = _data(args.get("data_nascimento"), "data_nascimento")
    data_ultima = _data(args.get("data_ultima_dose"), "data_ultima_dose")
    ultima_dose = args.get("ultima_dose")
    # O modelo pode enviar números como float (ex.: 1.0).
    if isinstance(ultima_dose, float) and ultima_dose.is_integer():
        ultima_dose = int(ultima_dose)
    vacina_id = args.get("vacina_id")

    if not ctx.regras.get("liberado_para_uso_em_producao", False) and not ctx.modo_teste:
        return {
            "status": "bloqueado",
            "mensagem": (
                "As regras vacinais ainda aguardam validação clínica da UBS; "
                "nenhuma data pode ser calculada. Oriente a pessoa a procurar a "
                "sala de vacina."
            ),
        }

    resultado = calcular_proxima_dose(
        nascimento, vacina_id, ultima_dose, data_ultima, hoje=ctx.hoje
    )
    resposta = {
        "status": resultado.status,
        "vacina": _nome_vacina(ctx.regras, vacina_id),
        "mensagem": resultado.mensagem,
        "aviso_obrigatorio": resultado.aviso_seguranca,
        "simulacao": resultado.validacao_clinica_pendente,
    }
    if resultado.status == "proxima_dose":
        ctx.doses_calculadas[vacina_id] = resultado.data_proxima_dose
        resposta["dose_seguinte"] = resultado.dose_seguinte
        resposta["data_prevista"] = resultado.data_proxima_dose.isoformat()
    return resposta


def _agendar(ctx: ContextoExecucao, args: dict) -> dict:
    vacina_id = args.get("vacina_id")
    data_prevista = ctx.doses_calculadas.get(vacina_id)
    if data_prevista is None:
        return {
            "erro": (
                "Não há data calculada para esta vacina nesta conversa. "
                "Use calcular_proxima_dose antes."
            )
        }
    lembrete = criar_lembrete(
        ctx.chat_id,
        vacina_id,
        data_prevista,
        **({"caminho": ctx.caminho_banco} if ctx.caminho_banco else {}),
    )
    if ctx.agendar is not None:
        ctx.agendar(lembrete)
    return {
        "status": "agendado",
        "lembrete_id": lembrete.id,
        "vacina": _nome_vacina(ctx.regras, vacina_id),
        "data_prevista": lembrete.data_prevista.isoformat(),
        "envio": lembrete.data_lembrete.strftime("%Y-%m-%d %H:%M"),
        "fuso": "horário de Riachão-MA",
    }


def _listar(ctx: ContextoExecucao, args: dict) -> dict:
    lembretes = listar_lembretes_do_chat(
        ctx.chat_id,
        **({"caminho": ctx.caminho_banco} if ctx.caminho_banco else {}),
    )
    return {
        "lembretes": [
            {
                "lembrete_id": item.id,
                "vacina": _nome_vacina(ctx.regras, item.vacina_id),
                "data_prevista": item.data_prevista.isoformat(),
                "envio": item.data_lembrete.strftime("%Y-%m-%d %H:%M"),
            }
            for item in lembretes
        ]
    }


def _cancelar(ctx: ContextoExecucao, args: dict) -> dict:
    lembrete_id = args.get("lembrete_id")
    if isinstance(lembrete_id, float) and lembrete_id.is_integer():
        lembrete_id = int(lembrete_id)
    if not isinstance(lembrete_id, int):
        raise ValueError("lembrete_id deve ser um número inteiro.")
    cancelado = cancelar_lembrete(
        lembrete_id,
        ctx.chat_id,
        **({"caminho": ctx.caminho_banco} if ctx.caminho_banco else {}),
    )
    if not cancelado:
        return {"erro": "Lembrete não encontrado entre os pendentes deste usuário."}
    if ctx.desagendar is not None:
        ctx.desagendar(lembrete_id)
    return {"status": "cancelado", "lembrete_id": lembrete_id}


def _localizacao(ctx: ContextoExecucao, args: dict) -> dict:
    ctx.localizacao_solicitada = True
    return {"status": "o mapa da UBS será enviado logo após a sua resposta"}


def _caderneta(ctx: ContextoExecucao, args: dict) -> dict:
    ctx.caderneta_solicitada = True
    return {"status": "a foto da caderneta será enviada logo após a sua resposta"}


_FUNCOES = {
    "calcular_proxima_dose": _calcular,
    "agendar_lembrete": _agendar,
    "listar_meus_lembretes": _listar,
    "enviar_localizacao": _localizacao,
    "enviar_foto_caderneta": _caderneta,
    "cancelar_lembrete": _cancelar,
}


def executar(nome: str, args: dict | None, ctx: ContextoExecucao) -> dict:
    """Executa uma ferramenta e sempre devolve um dicionário, mesmo em erro.

    Erros de validação voltam ao modelo como {"erro": ...}, para que ele
    possa pedir ao usuário a informação correta em vez de interromper a conversa.
    """
    funcao = _FUNCOES.get(nome)
    if funcao is None:
        return {"erro": f"Ferramenta desconhecida: {nome}."}
    try:
        return funcao(ctx, dict(args or {}))
    except (TypeError, ValueError) as erro:
        return {"erro": str(erro)}
