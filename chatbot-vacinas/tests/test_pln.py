import pytest

from pln import classificar_intencao


@pytest.mark.parametrize(
    ("texto", "intencao"),
    [
        ("Quando devo tomar a próxima dose?", "proxima_dose"),
        ("Quero ver as perguntas frequentes", "faq"),
        ("Quero falar com a unidade", "falar_com_unidade"),
        ("Tive febre depois da vacina", "faq"),
        ("Tenho alergia, posso receber a vacina?", "faq"),
    ],
)
def test_classifica_intencoes_dos_fluxos_principais(texto, intencao):
    resultado = classificar_intencao(texto)

    assert resultado.intencao == intencao
    assert 0.25 <= resultado.similaridade <= 1.0


@pytest.mark.parametrize("texto", ["", "bom dia", "12345"])
def test_mensagem_sem_intencao_reconhecida_vai_para_fallback(texto):
    assert classificar_intencao(texto).intencao == "desconhecida"


def test_classificador_nao_aceita_valor_que_nao_seja_texto():
    with pytest.raises(TypeError, match="texto deve ser uma string"):
        classificar_intencao(None)
