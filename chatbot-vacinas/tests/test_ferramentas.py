from datetime import date, timedelta

import pytest

import ferramentas
from database import inicializar_banco, listar_lembretes_do_chat
from ferramentas import ContextoExecucao
from motor_regras import CAMINHO_REGRAS_PADRAO

import json

REGRAS = json.loads(CAMINHO_REGRAS_PADRAO.read_text(encoding="utf-8"))
HOJE = date.today()


@pytest.fixture
def banco(tmp_path):
    caminho = tmp_path / "lembretes.sqlite3"
    inicializar_banco(caminho)
    return caminho


def _ctx(banco, chat_id=111, modo_teste=True, **extra):
    return ContextoExecucao(
        chat_id=chat_id,
        regras=REGRAS,
        modo_teste=modo_teste,
        caminho_banco=banco,
        hoje=HOJE,
        **extra,
    )


def _args_penta():
    return {
        "data_nascimento": (HOJE - timedelta(days=100)).isoformat(),
        "vacina_id": "pentavalente",
        "ultima_dose": 1,
        "data_ultima_dose": (HOJE - timedelta(days=10)).isoformat(),
    }


def test_declaracoes_cobrem_todas_as_ferramentas_executaveis():
    nomes = {item["name"] for item in ferramentas.declaracoes(REGRAS)}
    assert nomes == set(ferramentas._FUNCOES)


def test_calculo_bloqueado_sem_modo_teste_enquanto_regras_nao_validadas(banco):
    resultado = ferramentas.executar(
        "calcular_proxima_dose", _args_penta(), _ctx(banco, modo_teste=False)
    )
    assert resultado["status"] == "bloqueado"
    assert "data_prevista" not in resultado


def test_calculo_usa_motor_de_regras_e_marca_simulacao(banco):
    ctx = _ctx(banco)
    resultado = ferramentas.executar("calcular_proxima_dose", _args_penta(), ctx)

    assert resultado["status"] == "proxima_dose"
    assert resultado["dose_seguinte"] == 2
    assert resultado["data_prevista"] == (HOJE + timedelta(days=50)).isoformat()
    assert resultado["simulacao"] is True
    assert resultado["aviso_obrigatorio"]
    assert ctx.doses_calculadas["pentavalente"] == HOJE + timedelta(days=50)


def test_data_invalida_volta_como_erro_para_o_modelo(banco):
    args = _args_penta() | {"data_nascimento": "05/05/2026"}
    resultado = ferramentas.executar("calcular_proxima_dose", args, _ctx(banco))
    assert "AAAA-MM-DD" in resultado["erro"]


def test_nao_agenda_lembrete_sem_data_calculada_na_conversa(banco):
    resultado = ferramentas.executar(
        "agendar_lembrete", {"vacina_id": "pentavalente"}, _ctx(banco)
    )
    assert "calcular_proxima_dose" in resultado["erro"]
    assert listar_lembretes_do_chat(111, caminho=banco) == []


def test_agenda_lista_e_cancela_lembrete_do_proprio_chat(banco):
    agendados, desagendados = [], []
    ctx = _ctx(banco, agendar=agendados.append, desagendar=desagendados.append)
    ferramentas.executar("calcular_proxima_dose", _args_penta(), ctx)

    agendado = ferramentas.executar(
        "agendar_lembrete", {"vacina_id": "pentavalente"}, ctx
    )
    assert agendado["status"] == "agendado"
    assert agendados[0].id == agendado["lembrete_id"]

    lista = ferramentas.executar("listar_meus_lembretes", {}, ctx)
    assert [item["lembrete_id"] for item in lista["lembretes"]] == [
        agendado["lembrete_id"]
    ]

    cancelado = ferramentas.executar(
        "cancelar_lembrete", {"lembrete_id": float(agendado["lembrete_id"])}, ctx
    )
    assert cancelado["status"] == "cancelado"
    assert desagendados == [agendado["lembrete_id"]]
    assert listar_lembretes_do_chat(111, caminho=banco) == []


def test_nao_cancela_nem_lista_lembrete_de_outro_chat(banco):
    ctx_dono = _ctx(banco, chat_id=111)
    ferramentas.executar("calcular_proxima_dose", _args_penta(), ctx_dono)
    agendado = ferramentas.executar(
        "agendar_lembrete", {"vacina_id": "pentavalente"}, ctx_dono
    )

    ctx_outro = _ctx(banco, chat_id=222)
    assert ferramentas.executar("listar_meus_lembretes", {}, ctx_outro) == {
        "lembretes": []
    }
    resultado = ferramentas.executar(
        "cancelar_lembrete", {"lembrete_id": agendado["lembrete_id"]}, ctx_outro
    )
    assert "erro" in resultado
    assert len(listar_lembretes_do_chat(111, caminho=banco)) == 1


def test_ferramenta_desconhecida_nao_quebra_a_conversa(banco):
    assert "erro" in ferramentas.executar("apagar_tudo", {}, _ctx(banco))


def test_enviar_localizacao_marca_pedido_de_mapa(banco):
    ctx = _ctx(banco)
    resultado = ferramentas.executar("enviar_localizacao", {}, ctx)
    assert "mapa" in resultado["status"]
    assert ctx.localizacao_solicitada is True
