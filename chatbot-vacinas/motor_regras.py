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


def _fora_da_faixa_etaria(
    vacina: dict, nascimento: date, data_referencia: date
) -> bool:
    if "idade_maxima_meses_exclusiva" in vacina:
        limite = nascimento + relativedelta(
            months=vacina["idade_maxima_meses_exclusiva"]
        )
        return data_referencia < nascimento or data_referencia >= limite

    idade_minima_anos = vacina.get("idade_minima_anos")
    if idade_minima_anos is not None:
        return data_referencia < nascimento + relativedelta(years=idade_minima_anos)
    return data_referencia < nascimento


def _proxima_data(data_ultima_dose: date, dose: dict) -> date:
    anos = dose.get("intervalo_recomendado_anos")
    if anos is not None:
        return data_ultima_dose + relativedelta(years=anos)
    return data_ultima_dose + timedelta(days=dose["intervalo_recomendado_dias"])


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

    if _fora_da_faixa_etaria(vacina, data_nascimento, data_atual):
        return _resultado(
            "encaminhar_ubs",
            vacina_id,
            regras,
            regras["orientacao_segura"]["fora_do_escopo"],
        )
    if _fora_da_faixa_etaria(vacina, data_nascimento, data_ultima_dose):
        return _resultado(
            "encaminhar_ubs",
            vacina_id,
            regras,
            regras["orientacao_segura"]["fora_do_escopo"],
        )

    esquema = vacina["esquema"]
    doses_primarias = esquema["doses"]
    doses_adicionais = esquema.get("doses_adicionais", [])
    quantidade_primaria = len(doses_primarias)

    if ultima_dose < quantidade_primaria:
        proxima_dose = doses_primarias[ultima_dose]
    elif ultima_dose == quantidade_primaria:
        if not doses_adicionais:
            return _resultado(
                "esquema_completo",
                vacina_id,
                regras,
                "O esquema cadastrado está completo.",
            )
        proxima_dose = doses_adicionais[0]
    else:
        reforco_recorrente = next(
            (dose for dose in doses_adicionais if dose.get("recorrente")),
            None,
        )
        if reforco_recorrente is None or ultima_dose < reforco_recorrente["numero"]:
            if any(dose.get("numero") == ultima_dose for dose in doses_adicionais):
                return _resultado(
                    "esquema_completo",
                    vacina_id,
                    regras,
                    "O esquema cadastrado está completo.",
                )
            return _resultado(
                "encaminhar_ubs",
                vacina_id,
                regras,
                regras["orientacao_segura"]["fora_do_escopo"],
            )
        proxima_dose = reforco_recorrente

    numero_seguinte = proxima_dose["numero"]
    if proxima_dose.get("recorrente") and ultima_dose >= numero_seguinte:
        numero_seguinte = ultima_dose + 1

    data_prevista = _proxima_data(data_ultima_dose, proxima_dose)
    if _fora_da_faixa_etaria(vacina, data_nascimento, data_prevista):
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
