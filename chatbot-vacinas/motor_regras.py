"""Motor determinístico de cálculo de próximas doses a partir das regras JSON."""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from dateutil.relativedelta import relativedelta


StatusCalculo = Literal["proxima_dose", "esquema_completo", "encaminhar_ubs"]
CAMINHO_REGRAS_PADRAO = Path(__file__).resolve().parent / "data" / "regras_pni.json"


@dataclass(frozen=True)
class ResultadoCalculo:
    status: StatusCalculo
    vacina_id: str
    dose_seguinte: int | None
    data_proxima_dose: date | None
    mensagem: str
    aviso_seguranca: str
    validacao_clinica_pendente: bool


def _carregar_regras(caminho: Path) -> dict:
    with caminho.open(encoding="utf-8") as arquivo:
        regras = json.load(arquivo)
    if not isinstance(regras.get("vacinas"), list):
        raise ValueError("O arquivo de regras deve conter uma lista 'vacinas'.")
    return regras


def _resultado(
    status: StatusCalculo,
    vacina_id: str,
    regras: dict,
    mensagem: str,
    dose_seguinte: int | None = None,
    data_proxima_dose: date | None = None,
) -> ResultadoCalculo:
    return ResultadoCalculo(
        status=status,
        vacina_id=vacina_id,
        dose_seguinte=dose_seguinte,
        data_proxima_dose=data_proxima_dose,
        mensagem=mensagem,
        aviso_seguranca=regras["orientacao_segura"]["aviso_obrigatorio"],
        validacao_clinica_pendente=(
            regras.get("status_validacao_clinica") != "validado"
        ),
    )


def _idade_limite(nascimento: date, regra: dict, prefixo: str) -> date | None:
    """Converte campos como idade_minima_meses / idade_minima_anos em uma data."""
    meses = regra.get(f"{prefixo}_meses")
    anos = regra.get(f"{prefixo}_anos")
    if meses is not None:
        return nascimento + relativedelta(months=meses)
    if anos is not None:
        return nascimento + relativedelta(years=anos)
    return None


def _fora_da_faixa_etaria(
    regra: dict, nascimento: date, data_referencia: date
) -> bool:
    """Verifica os limites de idade de uma vacina ou de uma dose específica.

    O limite mínimo é inclusivo e o máximo é exclusivo (por exemplo, "até 4 anos,
    11 meses e 29 dias" é cadastrado como idade_maxima_meses_exclusiva = 60).
    """
    if data_referencia < nascimento:
        return True
    minimo = _idade_limite(nascimento, regra, "idade_minima")
    if minimo is not None and data_referencia < minimo:
        return True
    if regra.get("idade_maxima_meses_exclusiva") is not None:
        maximo = nascimento + relativedelta(months=regra["idade_maxima_meses_exclusiva"])
    elif regra.get("idade_maxima_anos_exclusiva") is not None:
        maximo = nascimento + relativedelta(years=regra["idade_maxima_anos_exclusiva"])
    else:
        return False
    return data_referencia >= maximo


def _proxima_data(nascimento: date, data_ultima_dose: date, dose: dict) -> date:
    """Data prevista = a mais tardia entre a idade-alvo e o intervalo desde a última dose.

    Segue a lógica da "agenda oportuna" do PNI: quem está em dia toma na idade
    recomendada; quem tomou a dose anterior com atraso respeita o intervalo.
    """
    if dose.get("intervalo_recomendado_anos") is not None:
        pelo_intervalo = data_ultima_dose + relativedelta(
            years=dose["intervalo_recomendado_anos"]
        )
    elif dose.get("intervalo_recomendado_meses") is not None:
        pelo_intervalo = data_ultima_dose + relativedelta(
            months=dose["intervalo_recomendado_meses"]
        )
    else:
        pelo_intervalo = data_ultima_dose + timedelta(
            days=dose.get("intervalo_recomendado_dias", 0)
        )
    idade_alvo = dose.get("idade_alvo_meses")
    if idade_alvo is None:
        return pelo_intervalo
    return max(pelo_intervalo, nascimento + relativedelta(months=idade_alvo))


def calcular_proxima_dose(
    data_nascimento: date,
    vacina_id: str,
    ultima_dose: int,
    data_ultima_dose: date,
    *,
    hoje: date | None = None,
    caminho_regras: Path | None = None,
) -> ResultadoCalculo:
    """Calcula a data recomendada ou encaminha casos não cobertos à UBS.

    Os intervalos no JSON são preliminares. A função é determinística, mas
    seus resultados não devem ser usados clinicamente até validação da UBS.
    """
    if isinstance(data_nascimento, datetime) or not isinstance(data_nascimento, date):
        raise TypeError("data_nascimento deve ser datetime.date.")
    if isinstance(data_ultima_dose, datetime) or not isinstance(data_ultima_dose, date):
        raise TypeError("data_ultima_dose deve ser datetime.date.")
    if isinstance(ultima_dose, bool) or not isinstance(ultima_dose, int) or ultima_dose < 1:
        raise ValueError("ultima_dose deve ser um inteiro positivo.")

    data_atual = hoje or date.today()
    if isinstance(data_atual, datetime) or not isinstance(data_atual, date):
        raise TypeError("hoje deve ser datetime.date.")
    if data_nascimento > data_atual:
        raise ValueError("A data de nascimento não pode estar no futuro.")
    if data_ultima_dose > data_atual:
        raise ValueError("A data da última dose não pode estar no futuro.")
    if data_ultima_dose < data_nascimento:
        raise ValueError("A data da última dose não pode anteceder o nascimento.")

    regras = _carregar_regras(caminho_regras or CAMINHO_REGRAS_PADRAO)
    vacina = next(
        (item for item in regras["vacinas"] if item.get("id") == vacina_id),
        None,
    )
    if vacina is None:
        return _resultado(
            "encaminhar_ubs",
            vacina_id,
            regras,
            regras["orientacao_segura"]["fora_do_escopo"],
        )

    # A idade atual não é verificada aqui: um esquema completo vale em qualquer
    # idade, e a data prevista abaixo passa pelos limites e precisa estar no futuro.
    if _fora_da_faixa_etaria(vacina, data_nascimento, data_ultima_dose):
        return _resultado(
            "encaminhar_ubs",
            vacina_id,
            regras,
            regras["orientacao_segura"]["fora_do_escopo"],
        )

    esquema = vacina["esquema"]
    todas_as_doses = sorted(
        esquema["doses"] + esquema.get("doses_adicionais", []),
        key=lambda dose: dose["numero"],
    )
    reforco_recorrente = next(
        (dose for dose in todas_as_doses if dose.get("recorrente")), None
    )
    proxima_dose = next(
        (dose for dose in todas_as_doses if dose["numero"] == ultima_dose + 1), None
    )
    numero_seguinte = ultima_dose + 1

    if proxima_dose is None:
        if reforco_recorrente is not None and ultima_dose >= reforco_recorrente["numero"]:
            proxima_dose = reforco_recorrente
        elif ultima_dose == todas_as_doses[-1]["numero"]:
            return _resultado(
                "esquema_completo",
                vacina_id,
                regras,
                esquema.get(
                    "mensagem_esquema_completo", "O esquema cadastrado está completo."
                ),
            )
        else:
            return _resultado(
                "encaminhar_ubs",
                vacina_id,
                regras,
                regras["orientacao_segura"]["fora_do_escopo"],
            )

    data_prevista = _proxima_data(data_nascimento, data_ultima_dose, proxima_dose)
    if _fora_da_faixa_etaria(
        vacina, data_nascimento, data_prevista
    ) or _fora_da_faixa_etaria(proxima_dose, data_nascimento, data_prevista):
        return _resultado(
            "encaminhar_ubs",
            vacina_id,
            regras,
            regras["orientacao_segura"]["fora_do_escopo"],
        )
    if data_prevista < data_atual:
        return _resultado(
            "encaminhar_ubs",
            vacina_id,
            regras,
            "A data calculada já passou e a regra de recuperação não está cadastrada. "
            + regras["orientacao_segura"]["fora_do_escopo"],
        )

    return _resultado(
        "proxima_dose",
        vacina_id,
        regras,
        "Data recomendada preliminar calculada pelo esquema cadastrado.",
        dose_seguinte=numero_seguinte,
        data_proxima_dose=data_prevista,
    )
