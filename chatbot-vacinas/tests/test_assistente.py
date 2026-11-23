"""Testa o ciclo do assistente com modelos falsos, sem acessar a internet."""

import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace

from google.genai import types

import assistente as modulo
from assistente import (
    RESPOSTA_FALHA,
    RESPOSTA_RECUSA,
    AssistenteClaude,
    AssistenteGemini,
    Memoria,
)
from database import inicializar_banco
from ferramentas import ContextoExecucao
from motor_regras import CAMINHO_REGRAS_PADRAO

REGRAS = json.loads(CAMINHO_REGRAS_PADRAO.read_text(encoding="utf-8"))
HOJE = date.today()
ARGS_PENTA = {
    "data_nascimento": (HOJE - timedelta(days=100)).isoformat(),
    "vacina_id": "pentavalente",
    "ultima_dose": 1,
    "data_ultima_dose": (HOJE - timedelta(days=10)).isoformat(),
}


def _ctx(tmp_path):
    caminho = tmp_path / "lembretes.sqlite3"
    inicializar_banco(caminho)
    return ContextoExecucao(
        chat_id=111, regras=REGRAS, modo_teste=True, caminho_banco=caminho, hoje=HOJE
    )


# --------------------------------------------------------------------------- #
# Claude
# --------------------------------------------------------------------------- #

def _bloco(tipo, **campos):
    return SimpleNamespace(type=tipo, **campos)


def _claude_texto(texto, raciocinio=False):
    conteudo = [_bloco("text", text=texto)]
    if raciocinio:
        conteudo.insert(0, _bloco("thinking", thinking="", signature="sig"))
    return SimpleNamespace(stop_reason="end_turn", content=conteudo)


def _claude_ferramenta(nome, args, id_uso="t1"):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[_bloco("tool_use", id=id_uso, name=nome, input=args)],
    )


class ClaudeFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    async def __call__(self, **parametros):
        # Copia a lista: o assistente continua acrescentando mensagens nela.
        self.chamadas.append({**parametros, "messages": list(parametros["messages"])})
        return self.respostas.pop(0)


def test_claude_ferramentas_usam_schema_estrito():
    assistente = AssistenteClaude(ClaudeFalso([]), REGRAS, base_ubs="")
    for ferramenta in assistente._ferramentas:
        assert ferramenta["strict"] is True
        assert ferramenta["input_schema"]["additionalProperties"] is False


def test_claude_executa_ferramenta_e_devolve_resultado(tmp_path):
    modelo = ClaudeFalso(
        [
            _claude_ferramenta("calcular_proxima_dose", ARGS_PENTA),
            _claude_texto("A 2ª dose está prevista."),
        ]
    )
    assistente = AssistenteClaude(modelo, REGRAS, base_ubs="base de teste")
    ctx = _ctx(tmp_path)

    resposta = asyncio.run(assistente.responder("próxima penta?", Memoria(), ctx))

    assert resposta == "A 2ª dose está prevista."
    assert "base de teste" in modelo.chamadas[0]["system"]
    resultado = modelo.chamadas[1]["messages"][-1]["content"][0]
    assert resultado["type"] == "tool_result"
    assert resultado["tool_use_id"] == "t1"
    assert json.loads(resultado["content"])["data_prevista"] == (
        HOJE + timedelta(days=50)
    ).isoformat()
    assert "pentavalente" in ctx.doses_calculadas


def test_claude_marca_erro_de_ferramenta(tmp_path):
    modelo = ClaudeFalso(
        [
            _claude_ferramenta("agendar_lembrete", {"vacina_id": "pentavalente"}),
            _claude_texto("Preciso calcular antes."),
        ]
    )
    assistente = AssistenteClaude(modelo, REGRAS, base_ubs="")

    asyncio.run(assistente.responder("me lembra", Memoria(), _ctx(tmp_path)))

    assert modelo.chamadas[1]["messages"][-1]["content"][0]["is_error"] is True


def test_claude_recusa_vira_encaminhamento_sem_poluir_memoria(tmp_path):
    recusa = SimpleNamespace(stop_reason="refusal", content=[])
    assistente = AssistenteClaude(ClaudeFalso([recusa]), REGRAS, base_ubs="")
    memoria = Memoria()

    resposta = asyncio.run(assistente.responder("?", memoria, _ctx(tmp_path)))

    assert resposta == RESPOSTA_RECUSA
    assert memoria.turnos == []


def test_claude_mantem_instrucoes_fixas_durante_a_conversa(tmp_path):
    modelo = ClaudeFalso([_claude_texto("Oi"), _claude_texto("Certo")])
    assistente = AssistenteClaude(modelo, REGRAS, base_ubs="")
    memoria = Memoria()
    ctx = _ctx(tmp_path)

    asyncio.run(assistente.responder("Olá", memoria, ctx))
    ctx.hoje = HOJE + timedelta(days=1)  # a data vira no meio da conversa
    asyncio.run(assistente.responder("E agora?", memoria, ctx))

    assert modelo.chamadas[0]["system"] == modelo.chamadas[1]["system"]
    assert [m["role"] for m in modelo.chamadas[1]["messages"]] == [
        "user",
        "assistant",
        "user",
    ]


def test_claude_corte_da_memoria_remove_raciocinio_antigo(tmp_path):
    total = modulo.MAX_TURNOS_MEMORIA + 2
    modelo = ClaudeFalso([_claude_texto(f"r{i}", raciocinio=True) for i in range(total)])
    assistente = AssistenteClaude(modelo, REGRAS, base_ubs="")
    memoria = Memoria()
    ctx = _ctx(tmp_path)

    for i in range(total):
        asyncio.run(assistente.responder(f"m{i}", memoria, ctx))

    assert len(memoria.turnos) == modulo.MAX_TURNOS_MEMORIA
    blocos = [
        bloco
        for mensagem in memoria.conteudos()
        if mensagem["role"] == "assistant"
        for bloco in mensagem["content"]
    ]
    assert all(bloco.type == "text" for bloco in blocos)


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #

def _gemini_texto(texto):
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=types.Content(role="model", parts=[types.Part(text=texto)])
            )
        ],
        function_calls=None,
        text=texto,
    )


def _gemini_ferramenta(nome, args):
    chamada = types.FunctionCall(id="c1", name=nome, args=args)
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=types.Content(
                    role="model", parts=[types.Part(function_call=chamada)]
                )
            )
        ],
        function_calls=[chamada],
        text=None,
    )


class GeminiFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    async def __call__(self, conteudos, config):
        self.chamadas.append((list(conteudos), config))
        return self.respostas.pop(0)


def test_gemini_responde_direto_e_guarda_turno(tmp_path):
    modelo = GeminiFalso([_gemini_texto("A UBS fica no bairro Centenário.")])
    assistente = AssistenteGemini(modelo, REGRAS, base_ubs="base de teste")
    memoria = Memoria()

    resposta = asyncio.run(
        assistente.responder("Onde fica a UBS?", memoria, _ctx(tmp_path))
    )

    assert resposta == "A UBS fica no bairro Centenário."
    assert len(memoria.turnos) == 1
    instrucoes = modelo.chamadas[0][1].system_instruction
    assert "base de teste" in instrucoes
    assert HOJE.strftime("%d/%m/%Y") in instrucoes


def test_gemini_executa_ferramenta(tmp_path):
    modelo = GeminiFalso(
        [
            _gemini_ferramenta("calcular_proxima_dose", ARGS_PENTA),
            _gemini_texto("A 2ª dose está prevista."),
        ]
    )
    assistente = AssistenteGemini(modelo, REGRAS, base_ubs="")

    resposta = asyncio.run(
        assistente.responder("próxima penta?", Memoria(), _ctx(tmp_path))
    )

    assert resposta == "A 2ª dose está prevista."
    retorno = modelo.chamadas[1][0][-1].parts[0].function_response
    assert retorno.name == "calcular_proxima_dose"
    assert retorno.id == "c1"


def test_gemini_resposta_vazia_vira_falha(tmp_path):
    vazio = SimpleNamespace(candidates=[], function_calls=None, text=None)
    assistente = AssistenteGemini(GeminiFalso([vazio]), REGRAS, base_ubs="")
    memoria = Memoria()

    resposta = asyncio.run(assistente.responder("?", memoria, _ctx(tmp_path)))

    assert resposta == RESPOSTA_FALHA
    assert memoria.turnos == []


def test_limite_de_ferramentas_evita_laco_infinito(tmp_path):
    repeticoes = [_gemini_ferramenta("listar_meus_lembretes", {})] * 20
    assistente = AssistenteGemini(GeminiFalso(repeticoes), REGRAS, base_ubs="")

    resposta = asyncio.run(
        assistente.responder("meus lembretes", Memoria(), _ctx(tmp_path))
    )

    assert resposta == RESPOSTA_FALHA


def test_gemini_modelo_reserva_assume_na_sobrecarga(monkeypatch):
    from google import genai
    from google.genai import errors

    chamados = []

    class ModelosFalsos:
        async def generate_content(self, model, contents, config):
            chamados.append(model)
            if model == "principal":
                raise errors.APIError(503, {"error": {"status": "UNAVAILABLE"}})
            return _gemini_texto("ok")

    class ClienteFalso:
        def __init__(self, **kwargs):
            self.aio = SimpleNamespace(models=ModelosFalsos())

    monkeypatch.setattr(genai, "Client", ClienteFalso)
    assistente = AssistenteGemini.com_api(
        "chave", REGRAS, modelo="principal", modelo_reserva="reserva"
    )

    resposta = asyncio.run(assistente._gerar([], None))

    assert resposta.text == "ok"
    assert chamados == ["principal", "reserva"]


# --------------------------------------------------------------------------- #
# Groq
# --------------------------------------------------------------------------- #

from assistente import AssistenteGroq


def _groq(conteudo=None, chamadas=None):
    mensagem = SimpleNamespace(content=conteudo, tool_calls=chamadas)
    return SimpleNamespace(choices=[SimpleNamespace(message=mensagem)])


def _groq_chamada(nome, argumentos, id_chamada="g1"):
    return SimpleNamespace(
        id=id_chamada,
        function=SimpleNamespace(name=nome, arguments=argumentos),
    )


class GroqFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    async def __call__(self, **parametros):
        self.chamadas.append({**parametros, "messages": list(parametros["messages"])})
        return self.respostas.pop(0)


def test_groq_executa_ferramenta_e_responde(tmp_path):
    modelo = GroqFalso(
        [
            _groq(chamadas=[_groq_chamada("calcular_proxima_dose", json.dumps(ARGS_PENTA))]),
            _groq("A 2ª dose está prevista."),
        ]
    )
    assistente = AssistenteGroq(modelo, REGRAS, base_ubs="base de teste")
    memoria = Memoria()
    ctx = _ctx(tmp_path)

    resposta = asyncio.run(assistente.responder("próxima penta?", memoria, ctx))

    assert resposta == "A 2ª dose está prevista."
    primeira = modelo.chamadas[0]["messages"]
    assert primeira[0]["role"] == "system" and "base de teste" in primeira[0]["content"]
    retorno = modelo.chamadas[1]["messages"][-1]
    assert retorno["role"] == "tool" and retorno["tool_call_id"] == "g1"
    assert json.loads(retorno["content"])["status"] == "proxima_dose"
    assert "pentavalente" in ctx.doses_calculadas
    assert len(memoria.turnos) == 1


def test_groq_argumentos_invalidos_voltam_como_erro(tmp_path):
    modelo = GroqFalso(
        [
            _groq(chamadas=[_groq_chamada("calcular_proxima_dose", "{quebrado")]),
            _groq("Pode repetir as datas?"),
        ]
    )
    assistente = AssistenteGroq(modelo, REGRAS, base_ubs="")

    asyncio.run(assistente.responder("penta", Memoria(), _ctx(tmp_path)))

    retorno = json.loads(modelo.chamadas[1]["messages"][-1]["content"])
    assert "erro" in retorno
