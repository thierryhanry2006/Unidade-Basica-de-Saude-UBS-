from datetime import date

import pytest

from motor_regras import calcular_proxima_dose


HOJE = date(2025, 1, 1)


@pytest.mark.parametrize(
    ("vacina", "nascimento", "dose", "data_dose", "dose_seguinte", "data_esperada"),
    [
        ("pentavalente", date(2024, 1, 1), 1, date(2024, 3, 1), 2, date(2024, 4, 30)),
        ("vip", date(2024, 1, 1), 3, date(2024, 7, 1), 4, date(2025, 3, 28)),
        ("hepatite_b", date(2000, 1, 1), 1, date(2024, 1, 1), 2, date(2024, 1, 31)),
        ("hepatite_b", date(2000, 1, 1), 2, date(2024, 2, 1), 3, date(2024, 6, 30)),
        ("dt", date(2000, 1, 1), 3, date(2024, 2, 29), 4, date(2034, 2, 28)),
        ("dt", date(2000, 1, 1), 4, date(2024, 2, 29), 5, date(2034, 2, 28)),
    ],
)
def test_calcula_data_da_proxima_dose(
    vacina, nascimento, dose, data_dose, dose_seguinte, data_esperada
):
    resultado = calcular_proxima_dose(
        nascimento, vacina, dose, data_dose, hoje=data_dose
    )

    assert resultado.status == "proxima_dose"
    assert resultado.dose_seguinte == dose_seguinte
    assert resultado.data_proxima_dose == data_esperada
    assert resultado.validacao_clinica_pendente is True
    assert "meramente informativa" in resultado.aviso_seguranca


@pytest.mark.parametrize(
    ("vacina", "nascimento", "dose", "data_dose"),
    [
        ("pentavalente", date(2020, 1, 1), 1, date(2020, 3, 1)),
        ("hepatite_b", date(2020, 1, 1), 1, date(2024, 1, 1)),
        ("vacina_nao_cadastrada", date(2000, 1, 1), 1, date(2024, 1, 1)),
    ],
)
def test_encaminha_idades_ou_vacinas_fora_do_escopo(
    vacina, nascimento, dose, data_dose
):
    resultado = calcular_proxima_dose(
        nascimento, vacina, dose, data_dose, hoje=HOJE
    )

    assert resultado.status == "encaminhar_ubs"
    assert resultado.data_proxima_dose is None


def test_encaminha_esquema_completo_sem_reforco():
    resultado = calcular_proxima_dose(
        date(2024, 1, 1),
        "pentavalente",
        3,
        date(2024, 7, 1),
        hoje=HOJE,
    )

    assert resultado.status == "esquema_completo"
    assert resultado.data_proxima_dose is None


def test_encaminha_data_prevista_que_ultrapassa_limite_infantil():
    resultado = calcular_proxima_dose(
        date(2020, 2, 1),
        "pentavalente",
        2,
        date(2025, 1, 1),
        hoje=HOJE,
    )

    assert resultado.status == "encaminhar_ubs"
    assert resultado.data_proxima_dose is None


def test_encaminha_esquema_atrasado_em_vez_de_inventar_recuperacao():
    resultado = calcular_proxima_dose(
        date(2000, 1, 1),
        "hepatite_b",
        1,
        date(2024, 1, 1),
        hoje=HOJE,
    )

    assert resultado.status == "encaminhar_ubs"
    assert "já passou" in resultado.mensagem


def test_rejeita_data_de_dose_no_futuro():
    with pytest.raises(ValueError, match="não pode estar no futuro"):
        calcular_proxima_dose(
            date(2000, 1, 1),
            "hepatite_b",
            1,
            date(2025, 1, 2),
            hoje=HOJE,
        )
