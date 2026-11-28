"""Assistente da UBS baseado em modelo de linguagem com ferramentas.

Fluxo de cada mensagem:
1. o modelo recebe as instruções, a base de conhecimento da UBS, o histórico
   recente da conversa e a nova mensagem;
2. se precisar agir no sistema, ele pede uma ferramenta (function calling);
3. o código executa a ferramenta (ferramentas.py) e devolve o resultado;
4. o ciclo se repete até o modelo responder em texto ao usuário.

Há duas implementações com o mesmo comportamento: Claude (Anthropic) e
Gemini (Google). As ferramentas, as instruções e a memória são compartilhadas.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Awaitable, Callable

import ferramentas
from ferramentas import ContextoExecucao


LOGGER = logging.getLogger(__name__)
CAMINHO_BASE_UBS = Path(__file__).resolve().parent / "data" / "base_ubs.md"
MODELO_PADRAO_CLAUDE = "claude-opus-5-5"
MODELO_PADRAO_GEMINI = "gemini-flash-latest"
MODELO_PADRAO_GROQ = "qwen/qwen3.8-27b"
MODELO_TRANSCRICAO_GROQ = "whisper-large-v3-turbo"
# Tempo máximo de cada requisição ao provedor. Sem limite, um provedor
# sobrecarregado pode deixar o usuário minutos sem resposta.
TEMPO_LIMITE_SEGUNDOS = 25.0
# Modelos Claude que aceitam o reenvio automático para outro modelo quando o
# filtro de segurança recusa uma resposta (server-side fallback).
MODELOS_CLAUDE_COM_FALLBACK = {
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
    "claude-fable-5-1",
    "claude-fable-5-2",
}
STATUS_TEMPORARIOS = (429, 500, 502, 503, 504)
MAX_CHAMADAS_FERRAMENTA = 6
MAX_TURNOS_MEMORIA = 8
EXPIRACAO_MEMORIA_SEGUNDOS = 30 * 60
RESPOSTA_FALHA = (
    "Desculpe, não consegui responder agora. Tente novamente em instantes ou "
    "use o menu com /start. Se precisar de atendimento, procure a recepção da "
    "UBS Maria Luiza."
)
RESPOSTA_RECUSA = (
    "Não posso ajudar com esse assunto por aqui. Para orientação, procure a "
    "equipe da UBS Maria Luiza. Em caso de emergência, ligue 192 (SAMU)."
)

INSTRUCOES = """\
Você é o assistente virtual da UBS Maria Luiza (Avenida Principal, bairro
Juá, também chamado de Centenário, Riachão – MA), um
assistente que atende pelo Telegram (projeto acadêmico em parceria com a UBS).

Seu papel: ajudar a população a se orientar na UBS — serviços, horários,
documentos, como iniciar atendimentos — e com a vacinação: calcular a próxima
dose e gerenciar lembretes.

Regras obrigatórias:
1. Datas de vacina: use SEMPRE a ferramenta calcular_proxima_dose. Nunca calcule,
   estime ou invente datas ou esquemas vacinais. Se a ferramenta indicar
   "encaminhar_ubs" ou "bloqueado", explique e oriente a procurar a sala de vacina.
2. Sempre que informar uma data calculada, inclua o aviso obrigatório que a
   ferramenta devolver. Se "simulacao" for verdadeiro, diga que é uma simulação do
   protótipo com regras ainda não validadas pela UBS.
3. Informações da UBS: use apenas a base de conhecimento abaixo. Itens marcados
   [A CONFIRMAR] devem ser ditos como ainda não confirmados, sugerindo confirmar
   na recepção. Se a informação não estiver na base, diga que não sabe — não invente.
4. Não dê orientação clínica: nada de diagnóstico, avaliação de sintomas,
   reações, contraindicações ou remédios. Encaminhe para a equipe de saúde. Em
   sinais de emergência, oriente ligar 192 (SAMU) imediatamente.
5. Privacidade: nunca peça nome, CPF, endereço ou número do Cartão do SUS. Peça
   datas apenas quando forem necessárias para o cálculo da dose.
6. Lembretes: ofereça o lembrete depois de calcular uma data, mas só agende se o
   usuário aceitar. Para cancelar, liste os lembretes e confirme qual antes.
7. Quando perguntarem onde fica a UBS ou como chegar, informe o endereço e use
   a ferramenta enviar_localizacao para mandar o mapa. Quando perguntarem sobre a
   caderneta ou carteirinha da criança, explique e use enviar_foto_caderneta.
8. Converta datas ditas de forma natural ("mês passado", "5 de maio") para
   AAAA-MM-DD usando a data de hoje. Se faltar alguma informação, pergunte.

Estilo: português simples e acolhedor, mensagens curtas, sem jargão. Escreva em
texto puro, sem Markdown (sem asteriscos, cerquilhas ou tabelas). Se o usuário
quiser os botões, diga que ele pode enviar /start.

Vacinas cadastradas (id: nome): {vacinas}

=== BASE DE CONHECIMENTO DA UBS ===
{base}
=== FIM DA BASE ===

Data de hoje: {hoje}.
"""


class ErroModelo(Exception):
    """Falha ao falar com o provedor do modelo (rede, limite, indisponibilidade)."""


@dataclass(frozen=True)
class Audio:
    dados: bytes
    mime: str = "audio/ogg"


@dataclass
class Memoria:
    """Histórico recente de uma conversa, mantido apenas em memória.

    `sistema` guarda as instruções usadas no início da conversa: elas não mudam
    no meio dela, nem mesmo se a data virar, porque o Claude exige que o início
    da conversa permaneça idêntico entre as mensagens.
    """

    turnos: list[list[Any]] = field(default_factory=list)
    ultima_atividade: float = field(default_factory=time.monotonic)
    sistema: str | None = None

    def conteudos(self) -> list[Any]:
        if time.monotonic() - self.ultima_atividade > EXPIRACAO_MEMORIA_SEGUNDOS:
            self.turnos.clear()
            self.sistema = None
        return [conteudo for turno in self.turnos for conteudo in turno]

    def registrar(
        self,
        turno: list[Any],
        limpar: Callable[[Any], Any] | None = None,
    ) -> None:
        self.turnos.append(turno)
        if len(self.turnos) > MAX_TURNOS_MEMORIA:
            # Corta turnos inteiros, para nunca separar uma chamada de
            # ferramenta do seu resultado.
            del self.turnos[:-MAX_TURNOS_MEMORIA]
            if limpar is not None:
                self.turnos = [[limpar(item) for item in t] for t in self.turnos]
        self.ultima_atividade = time.monotonic()


class _AssistenteBase:
    aceita_audio = False

    def __init__(self, regras: dict, base_ubs: str | None = None) -> None:
        self._regras = regras
        self._base = (
            base_ubs
            if base_ubs is not None
            else CAMINHO_BASE_UBS.read_text(encoding="utf-8")
        )

    def _instrucoes(self, hoje: date) -> str:
        vacinas = "; ".join(f"{v['id']}: {v['nome']}" for v in self._regras["vacinas"])
        return INSTRUCOES.format(
            hoje=hoje.strftime("%d/%m/%Y"), vacinas=vacinas, base=self._base
        )


# --------------------------------------------------------------------------- #
# Claude (Anthropic)
# --------------------------------------------------------------------------- #

def _tipo(bloco: Any) -> str | None:
    return bloco.get("type") if isinstance(bloco, dict) else getattr(bloco, "type", None)


def _sem_raciocinio(mensagem: dict) -> dict:
    """Remove os blocos de raciocínio de uma mensagem já respondida.

    Ao cortar o início do histórico, os blocos de raciocínio que sobram deixam de
    corresponder à conversa original e a API os rejeitaria. Remover todos eles é
    permitido; o texto e as chamadas de ferramenta permanecem.
    """
    conteudo = mensagem.get("content")
    if mensagem.get("role") != "assistant" or isinstance(conteudo, str):
        return mensagem
    return {
        **mensagem,
        "content": [
            bloco
            for bloco in conteudo
            if _tipo(bloco) not in ("thinking", "redacted_thinking")
        ],
    }


class AssistenteClaude(_AssistenteBase):
    def __init__(
        self,
        criar: Callable[..., Awaitable[Any]],
        regras: dict,
        *,
        base_ubs: str | None = None,
    ) -> None:
        super().__init__(regras, base_ubs)
        self._criar = criar
        self._ferramentas = [
            {
                "name": item["name"],
                "description": item["description"],
                "input_schema": {
                    **item["parameters_json_schema"],
                    "additionalProperties": False,
                    "required": item["parameters_json_schema"].get("required", []),
                },
                "strict": True,
            }
            for item in ferramentas.declaracoes(regras)
        ]

    @classmethod
    def com_api(
        cls,
        api_key: str,
        regras: dict,
        modelo: str | None = None,
        esforco: str = "low",
    ) -> "AssistenteClaude":
        import anthropic

        cliente = anthropic.AsyncAnthropic(api_key=api_key, max_retries=4)
        nome_modelo = modelo or MODELO_PADRAO_CLAUDE
        betas = ["thinking-binding-controls-2026-08-01"]
        extras: dict[str, Any] = {}
        if nome_modelo in MODELOS_CLAUDE_COM_FALLBACK:
            betas.append("server-side-fallback-2026-07-01")
            extras["fallbacks"] = "default"

        async def criar(**parametros):
            try:
                return await cliente.beta.messages.create(
                    model=nome_modelo,
                    max_tokens=16000,
                    betas=betas,
                    # Se o histórico divergir, descarta o raciocínio antigo em
                    # vez de recusar a mensagem.
                    thinking={
                        "type": "adaptive",
                        "block_binding": {"prefix_mismatch_behavior": "drop_block"},
                    },
                    # Conversa de atendimento: esforço baixo responde mais rápido
                    # e mais barato. Ajustável por CLAUDE_EFFORT.
                    output_config={"effort": esforco},
                    cache_control={"type": "ephemeral"},
                    **extras,
                    **parametros,
                )
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as erro:
                raise ErroModelo(f"Claude: {type(erro).__name__}") from erro

        return cls(criar, regras)

    async def responder(
        self, entrada: str, memoria: Memoria, ctx: ContextoExecucao
    ) -> str:
        historico = memoria.conteudos()
        sistema = memoria.sistema or self._instrucoes(ctx.hoje or date.today())
        memoria.sistema = sistema
        turno: list[dict] = [{"role": "user", "content": entrada}]

        for _ in range(MAX_CHAMADAS_FERRAMENTA + 1):
            resposta = await self._criar(
                system=sistema, tools=self._ferramentas, messages=historico + turno
            )
            if resposta.stop_reason == "refusal":
                LOGGER.info("Modelo recusou a mensagem.")
                return RESPOSTA_RECUSA
            turno.append({"role": "assistant", "content": resposta.content})

            usos = [bloco for bloco in resposta.content if bloco.type == "tool_use"]
            if not usos:
                texto = "".join(
                    bloco.text for bloco in resposta.content if bloco.type == "text"
                ).strip()
                if not texto:
                    return RESPOSTA_FALHA
                memoria.registrar(turno, limpar=_sem_raciocinio)
                return texto

            resultados = []
            for uso in usos:
                LOGGER.info("Ferramenta solicitada: %s", uso.name)
                resultado = ferramentas.executar(uso.name, uso.input, ctx)
                bloco = {
                    "type": "tool_result",
                    "tool_use_id": uso.id,
                    "content": json.dumps(resultado, ensure_ascii=False),
                }
                if "erro" in resultado:
                    bloco["is_error"] = True
                resultados.append(bloco)
            turno.append({"role": "user", "content": resultados})

        LOGGER.warning("Limite de chamadas de ferramenta atingido.")
        return RESPOSTA_FALHA


# --------------------------------------------------------------------------- #
# Groq (modelos abertos, plano gratuito)
# --------------------------------------------------------------------------- #

class AssistenteGroq(_AssistenteBase):
    def __init__(
        self,
        criar: Callable[..., Awaitable[Any]],
        regras: dict,
        *,
        base_ubs: str | None = None,
    ) -> None:
        super().__init__(regras, base_ubs)
        self._criar = criar
        self._ferramentas = [
            {
                "type": "function",
                "function": {
                    "name": item["name"],
                    "description": item["description"],
                    "parameters": item["parameters_json_schema"],
                },
            }
            for item in ferramentas.declaracoes(regras)
        ]

    @classmethod
    def com_api(
        cls, api_key: str, regras: dict, modelo: str | None = None
    ) -> "AssistenteGroq":
        import groq

        cliente = groq.AsyncGroq(
            api_key=api_key, max_retries=3, timeout=TEMPO_LIMITE_SEGUNDOS
        )
        nome_modelo = modelo or MODELO_PADRAO_GROQ

        async def criar(**parametros):
            try:
                return await cliente.chat.completions.create(
                    model=nome_modelo,
                    tool_choice="auto",
                    temperature=0.3,
                    max_completion_tokens=1024,
                    **parametros,
                )
            except (groq.APIStatusError, groq.APIConnectionError) as erro:
                raise ErroModelo(f"Groq: {type(erro).__name__}: {erro}") from erro

        return cls(criar, regras)

    async def responder(
        self, entrada: str, memoria: Memoria, ctx: ContextoExecucao
    ) -> str:
        historico = memoria.conteudos()
        sistema = memoria.sistema or self._instrucoes(ctx.hoje or date.today())
        memoria.sistema = sistema
        turno: list[dict] = [{"role": "user", "content": entrada}]

        for _ in range(MAX_CHAMADAS_FERRAMENTA + 1):
            resposta = await self._criar(
                messages=[{"role": "system", "content": sistema}, *historico, *turno],
                tools=self._ferramentas,
            )
            mensagem = resposta.choices[0].message
            chamadas = mensagem.tool_calls or []
            registro: dict[str, Any] = {"role": "assistant"}
            if mensagem.content:
                registro["content"] = mensagem.content
            if chamadas:
                registro["tool_calls"] = [
                    {
                        "id": chamada.id,
                        "type": "function",
                        "function": {
                            "name": chamada.function.name,
                            "arguments": chamada.function.arguments or "{}",
                        },
                    }
                    for chamada in chamadas
                ]
            turno.append(registro)

            if not chamadas:
                texto = (mensagem.content or "").strip()
                if not texto:
                    return RESPOSTA_FALHA
                memoria.registrar(turno)
                return texto

            for chamada in chamadas:
                LOGGER.info("Ferramenta solicitada: %s", chamada.function.name)
                try:
                    args = json.loads(chamada.function.arguments or "{}")
                except json.JSONDecodeError:
                    resultado = {"erro": "Argumentos da ferramenta não são JSON válido."}
                else:
                    resultado = ferramentas.executar(chamada.function.name, args, ctx)
                turno.append(
                    {
                        "role": "tool",
                        "tool_call_id": chamada.id,
                        "content": json.dumps(resultado, ensure_ascii=False),
                    }
                )

        LOGGER.warning("Limite de chamadas de ferramenta atingido.")
        return RESPOSTA_FALHA


def transcritor_groq(
    api_key: str, modelo: str | None = None
) -> Callable[[Audio], Awaitable[str]]:
    """Transcreve áudio com o Whisper hospedado pelo Groq."""
    import groq

    cliente = groq.AsyncGroq(
        api_key=api_key, max_retries=3, timeout=TEMPO_LIMITE_SEGUNDOS
    )
    nome_modelo = modelo or MODELO_TRANSCRICAO_GROQ

    async def transcrever(audio: Audio) -> str:
        extensao = audio.mime.rsplit("/", 1)[-1] or "ogg"
        try:
            resultado = await cliente.audio.transcriptions.create(
                model=nome_modelo,
                file=(f"audio.{extensao}", audio.dados),
                language="pt",
                response_format="text",
            )
        except (groq.APIStatusError, groq.APIConnectionError) as erro:
            raise ErroModelo(f"Groq: {type(erro).__name__}: {erro}") from erro
        texto = resultado if isinstance(resultado, str) else getattr(resultado, "text", "")
        return (texto or "").strip()

    return transcrever


# --------------------------------------------------------------------------- #
# Gemini (Google)
# --------------------------------------------------------------------------- #

def _cliente_gemini(api_key: str):
    from google import genai
    from google.genai import types

    # Sobrecarga (503) e limite momentâneo (429) são comuns no plano
    # gratuito: o SDK tenta de novo com espera crescente antes de desistir.
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=int(TEMPO_LIMITE_SEGUNDOS * 1000),  # em milissegundos
            retry_options=types.HttpRetryOptions(
                attempts=4,
                initial_delay=1.0,
                max_delay=8.0,
                http_status_codes=list(STATUS_TEMPORARIOS),
            )
        ),
    )


class AssistenteGemini(_AssistenteBase):
    aceita_audio = True

    def __init__(self, gerar, regras: dict, *, base_ubs: str | None = None) -> None:
        from google.genai import types

        super().__init__(regras, base_ubs)
        self._gerar = gerar
        self._ferramentas = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(**declaracao)
                    for declaracao in ferramentas.declaracoes(regras)
                ]
            )
        ]

    @classmethod
    def com_api(
        cls,
        api_key: str,
        regras: dict,
        modelo: str | None = None,
        modelo_reserva: str | None = None,
    ) -> "AssistenteGemini":
        from google.genai import errors

        cliente = _cliente_gemini(api_key)
        modelos = [modelo or MODELO_PADRAO_GEMINI]
        if modelo_reserva and modelo_reserva not in modelos:
            modelos.append(modelo_reserva)

        async def gerar(conteudos, config):
            for indice, nome_modelo in enumerate(modelos):
                try:
                    return await cliente.aio.models.generate_content(
                        model=nome_modelo, contents=conteudos, config=config
                    )
                except errors.APIError as erro:
                    ultimo = indice == len(modelos) - 1
                    if ultimo or erro.code not in STATUS_TEMPORARIOS:
                        raise ErroModelo(f"Gemini: {erro.code} {erro.status}") from erro
                    LOGGER.warning(
                        "Modelo %s indisponível (%s); usando o reserva.",
                        nome_modelo,
                        erro.code,
                    )
                except Exception as erro:  # tempo esgotado ou falha de rede
                    if indice == len(modelos) - 1:
                        raise ErroModelo(f"Gemini: {type(erro).__name__}") from erro
                    LOGGER.warning(
                        "Modelo %s sem resposta (%s); usando o reserva.",
                        nome_modelo,
                        type(erro).__name__,
                    )

        return cls(gerar, regras)

    async def responder(
        self, entrada: str | Audio, memoria: Memoria, ctx: ContextoExecucao
    ) -> str:
        from google.genai import types

        historico = memoria.conteudos()
        sistema = memoria.sistema or self._instrucoes(ctx.hoje or date.today())
        memoria.sistema = sistema
        config = types.GenerateContentConfig(
            system_instruction=sistema, tools=self._ferramentas
        )
        parte = (
            types.Part.from_bytes(data=entrada.dados, mime_type=entrada.mime)
            if isinstance(entrada, Audio)
            else types.Part.from_text(text=entrada)
        )
        turno = [types.Content(role="user", parts=[parte])]

        for _ in range(MAX_CHAMADAS_FERRAMENTA + 1):
            resposta = await self._gerar(historico + turno, config)
            candidatos = resposta.candidates or []
            if not candidatos or candidatos[0].content is None:
                LOGGER.warning("Modelo não retornou conteúdo.")
                return RESPOSTA_FALHA
            turno.append(candidatos[0].content)

            chamadas = resposta.function_calls or []
            if not chamadas:
                texto = (resposta.text or "").strip()
                if not texto:
                    return RESPOSTA_FALHA
                memoria.registrar(turno)
                return texto

            partes_resultado = []
            for chamada in chamadas:
                LOGGER.info("Ferramenta solicitada: %s", chamada.name)
                resultado = ferramentas.executar(chamada.name, chamada.args, ctx)
                partes_resultado.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=chamada.id, name=chamada.name, response=resultado
                        )
                    )
                )
            turno.append(types.Content(role="user", parts=partes_resultado))

        LOGGER.warning("Limite de chamadas de ferramenta atingido.")
        return RESPOSTA_FALHA


def transcritor_gemini(
    api_key: str, modelo: str | None = None
) -> Callable[[Audio], Awaitable[str]]:
    """Transcreve áudio com o Gemini, para modelos que não recebem áudio (Claude)."""
    from google.genai import errors, types

    cliente = _cliente_gemini(api_key)
    nome_modelo = modelo or MODELO_PADRAO_GEMINI

    async def transcrever(audio: Audio) -> str:
        try:
            resposta = await cliente.aio.models.generate_content(
                model=nome_modelo,
                contents=[
                    types.Part.from_bytes(data=audio.dados, mime_type=audio.mime),
                    types.Part.from_text(
                        text="Transcreva fielmente este áudio em português. "
                        "Responda apenas com a transcrição."
                    ),
                ],
            )
        except errors.APIError as erro:
            raise ErroModelo(f"Gemini: {erro.code} {erro.status}") from erro
        except Exception as erro:  # tempo esgotado ou falha de rede
            raise ErroModelo(f"Gemini: {type(erro).__name__}") from erro
        return (resposta.text or "").strip()

    return transcrever
