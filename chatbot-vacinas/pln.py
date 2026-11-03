"""Classificação leve e local de intenção para mensagens em texto livre."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


Intencao = Literal["proxima_dose", "faq", "falar_com_unidade", "desconhecida"]
CAMINHO_INTENCOES = Path(__file__).resolve().parent / "data" / "intencoes_pln.json"


@dataclass(frozen=True)
class ClassificacaoIntencao:
    intencao: Intencao
    similaridade: float


def _carregar_exemplos(caminho: Path) -> tuple[dict, list[str], list[str]]:
    with caminho.open(encoding="utf-8") as arquivo:
        configuracao = json.load(arquivo)

    frases: list[str] = []
    intencoes: list[str] = []
    for grupo in configuracao["exemplos"]:
        for frase in grupo["frases"]:
            frases.append(frase)
            intencoes.append(grupo["intencao"])
    if not frases:
        raise ValueError("O arquivo de intenções não contém frases de exemplo.")
    return configuracao, frases, intencoes


CONFIGURACAO, _FRASES, _INTENCOES = _carregar_exemplos(CAMINHO_INTENCOES)
_VETORIZADOR = TfidfVectorizer(
    lowercase=True,
    strip_accents="unicode",
    ngram_range=(1, 2),
)
_MATRIZ_EXEMPLOS = _VETORIZADOR.fit_transform(_FRASES)
_LIMIAR = float(CONFIGURACAO["limiar_confianca"])
_INTENCOES_VALIDAS = {
    "proxima_dose",
    "faq",
    "falar_com_unidade",
}


def classificar_intencao(texto: str) -> ClassificacaoIntencao:
    """Classifica apenas a intenção; não extrai nem infere dados clínicos."""
    if not isinstance(texto, str):
        raise TypeError("texto deve ser uma string.")
    if not texto.strip():
        return ClassificacaoIntencao("desconhecida", 0.0)

    vetor = _VETORIZADOR.transform([texto])
    similaridades = cosine_similarity(vetor, _MATRIZ_EXEMPLOS).ravel()
    indice = int(similaridades.argmax())
    similaridade = min(1.0, max(0.0, float(similaridades[indice])))
    intencao_candidata = _INTENCOES[indice]

    if similaridade < _LIMIAR or intencao_candidata not in _INTENCOES_VALIDAS:
        return ClassificacaoIntencao("desconhecida", similaridade)
    return ClassificacaoIntencao(intencao_candidata, similaridade)
