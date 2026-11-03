import bot


def test_menu_principal_exibe_as_tres_acoes():
    botoes = [
        botao
        for linha in bot._teclado_menu().inline_keyboard
        for botao in linha
    ]

    assert [botao.text for botao in botoes] == [
        "Próxima dose",
        "Perguntas frequentes",
        "Falar com a unidade",
    ]
    assert [botao.callback_data for botao in botoes] == [
        "proxima_dose",
        "faq",
        "unidade",
    ]


def test_submenu_faq_tem_quatro_perguntas_editaveis_no_json():
    perguntas = bot.FAQ["perguntas"]
    botoes = [
        botao
        for linha in bot._teclado_faq().inline_keyboard
        for botao in linha
    ]

    assert len(perguntas) == 4
    assert [botao.text for botao in botoes[:-1]] == [
        item["pergunta"] for item in perguntas
    ]
    assert botoes[-1].text == "Voltar ao menu"


def test_mensagem_de_contato_reserva_campo_para_contato_oficial():
    assert "[INSERIR TELEFONE/CONTATO OFICIAL]" in FAQ_CONTATO


FAQ_CONTATO = bot.FAQ["contato_unidade"]
