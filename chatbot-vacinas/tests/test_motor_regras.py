from datetime import date

import pytest

from motor_regras import calcular_proxima_dose


HOJE = date(2025, 1, 1)


@pytest.mark.parametrize(
    ("vacina", "nascimento", "dose", "data_dose", "dose_seguinte", "data_esperada"),
    [
        # Em dia: vale a idade recomendada (penta aos 4 meses).
        ("pentavalente", date(2024, 1, 1), 1, date(2024, 3, 1), 2, date(2024, 5, 1)),
        # Dose anterior atrasada: vale o intervalo de 60 dias.
        ("pentavalente", date(2024, 1, 1), 1, date(2024, 6, 1), 2, date(2024, 7, 31)),
        # VIP: 1º reforço aos 15 meses e 2º aos 4 anos.
        ("vip", date(2024, 1, 1), 3, date(2024, 7, 1), 4, date(2025, 4, 1)),
        ("vip", date(2024, 1, 1), 4, date(2025, 4, 1), 5, date(2028, 1, 1)),
        ("rotavirus", date(2024, 1, 1), 1, date(2024, 3, 1), 2, date(2024, 5, 1)),
        ("pneumococica", date(2024, 1, 1), 2, date(2024, 5, 1), 3, date(2025, 1, 1)),
        ("meningococica", date(2024, 1, 1), 1, date(2024, 4, 1), 2, date(2024, 6, 1)),
        ("febre_amarela", date(2024, 1, 1), 1, date(2024, 10, 1), 2, date(2028, 1, 1)),
        ("triplice_viral", date(2024, 1, 1), 1, date(2025, 1, 1), 2, date(2025, 4, 1)),
        # Adulto até 29 anos: segunda dose 30 dias depois.
        ("triplice_viral", date(2000, 1, 1), 1, date(2024, 1, 1), 2, date(2024, 1, 31)),
        ("varicela", date(2022, 1, 1), 1, date(2023, 4, 1), 2, date(2026, 1, 1)),
        ("hepatite_b", date(2000, 1, 1), 1, date(2024, 1, 1), 2, date(2024, 2, 1)),
        ("hepatite_b", date(2000, 1, 1), 2, date(2024, 2, 1), 3, date(2024, 7, 1)),
        ("dengue", date(2013, 1, 1), 1, date(2024, 1, 10), 2, date(2024, 4, 10)),
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
    assert resultado.validacao_clinica_pendente is False
    assert "meramente informativa" in resultado.aviso_seguranca


@pytest.mark.parametrize(
    ("vacina", "nascimento", "dose", "data_dose"),
    [
        ("pentavalente", date(2020, 1, 1), 1, date(2020, 3, 1)),
        ("hepatite_b", date(2020, 1, 1), 1, date(2024, 1, 1)),
        ("dengue", date(2005, 1, 1), 1, date(2024, 1, 1)),
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


@pytest.mark.parametrize(
    ("vacina", "nascimento", "dose", "data_dose", "trecho"),
    [
        ("pentavalente", date(2024, 1, 1), 3, date(2024, 7, 1), "DTP"),
        ("vip", date(2020, 1, 1), 5, date(2024, 1, 1), "2 reforços"),
        ("meningococica", date(2023, 1, 1), 3, date(2024, 1, 1), "ACWY"),
    ],
)
def test_esquema_completo_traz_mensagem_da_vacina(
    vacina, nascimento, dose, data_dose, trecho
):
    resultado = calcular_proxima_dose(
        nascimento, vacina, dose, data_dose, hoje=HOJE
    )

    assert resultado.status == "esquema_completo"
    assert resultado.data_proxima_dose is None
    assert trecho in resultado.mensagem


def test_encaminha_data_prevista_que_ultrapassa_limite_infantil():
    resultado = calcular_proxima_dose(
        date(2018, 2, 1),
        "pentavalente",
        2,
        date(2025, 1, 1),
        hoje=HOJE,
    )

    assert resultado.status == "encaminhar_ubs"
    assert resultado.data_proxima_dose is None


def test_encaminha_rotavirus_fora_da_janela_da_segunda_dose():
    # 2ª dose só até 23 meses e 29 dias.
    resultado = calcular_proxima_dose(
        date(2023, 1, 1),
        "rotavirus",
        1,
        date(2024, 12, 1),
        hoje=date(2024, 12, 1),
    )

    assert resultado.status == "encaminhar_ubs"


def test_encaminha_historico_com_mais_doses_que_o_esquema():
    resultado = calcular_proxima_dose(
        date(2024, 1, 1), "pentavalente", 5, date(2024, 12, 1), hoje=HOJE
    )

    assert resultado.status == "encaminhar_ubs"


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
