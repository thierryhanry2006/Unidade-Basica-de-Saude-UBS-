# VACINA — visão geral do protótipo

Este projeto é um protótipo acadêmico de orientação vacinal pelo Telegram
para a UBS Centenário. O bot, o motor de regras e os lembretes são executados
localmente pelo processo `python bot.py`; o protótipo não é um serviço
hospedado permanentemente.

## Situação e limites atuais

- O canal implementado é Telegram. WhatsApp não está integrado.
- As regras em `data/regras_pni.json` são preliminares:
  `status_validacao_clinica` está como `pendente_ubs` e
  `liberado_para_uso_em_producao` está como `false`.
- Sem `VACINA_MODO_TESTE=1`, o bot não calcula nem recomenda datas enquanto as
  regras não forem validadas pela equipe da UBS.
- Com `VACINA_MODO_TESTE=1`, o bot pode calcular e enviar mensagens reais à
  conta Telegram conectada, identificando o resultado como simulação.
- O FAQ e os dados de contato são editáveis em `data/faq.json`. Há texto de
  contato e horário explicitamente pendente de validação local.
- A classificação PLN identifica somente a intenção da mensagem
  (`proxima_dose`, `faq` ou `falar_com_unidade`); ela não calcula doses.

## Fluxo do sistema

1. `bot.py` inicia o polling do Telegram e mostra o menu `/start`.
2. O fluxo de próxima dose coleta data de nascimento, vacina, número da última
   dose e data da aplicação. Esses dados ficam no estado temporário da conversa
   em memória; não são gravados na tabela de lembretes.
3. `pln.py` classifica texto livre e encaminha para um dos fluxos do menu.
4. `motor_regras.py` consulta `data/regras_pni.json` e calcula de forma
   determinística. Casos fora do esquema cadastrado são encaminhados à UBS.
5. Se o usuário aceitar um lembrete, `database.py` grava o registro e
   `scheduler.py` agenda o envio no Telegram.
6. `data/faq.json` contém as respostas administrativas e a mensagem de contato.

Toda orientação de dose deve manter o aviso de caráter informativo e de
confirmação pela sala de vacina. Não usar os intervalos atuais para atendimento
clínico antes da validação da UBS.

## SQLite: o que é guardado

Por padrão, o arquivo é `data/lembretes.sqlite3`. O caminho pode ser alterado
pela variável `VACINA_DB_PATH`. A tabela `lembretes` guarda somente:

| Coluna | Uso |
|---|---|
| `id` | Identificador interno do lembrete |
| `chat_id` | Destino Telegram necessário para enviar a mensagem |
| `vacina_id` | Identificador da vacina |
| `data_prevista` | Data prevista cadastrada para a dose |
| `data_lembrete` | Data e hora do aviso, com fuso |
| `status` | Estado operacional do envio |

O status começa como `pendente` e pode se tornar `enviado`, `falha` ou
`expirado`. O SQLite não guarda nome, CPF ou data de nascimento. O `chat_id`
continua sendo um identificador pseudônimo: deve ter acesso restrito e não deve
ser publicado em logs ou capturas de tela.

`inicializar_banco()` cria a tabela e o índice, se ainda não existirem.
`criar_lembrete()` calcula o envio para um dia antes da data prevista, às 09:00
no fuso `America/Fortaleza`; se esse horário já passou, não cria o lembrete.
`atualizar_status()` só altera um registro que ainda esteja pendente.

## Agendamento e execução

Quando o bot inicia, o hook `iniciar_agendador()`:

1. inicializa o SQLite;
2. marca como `expirado` lembretes pendentes cujo horário já passou;
3. inicia o APScheduler no fuso `America/Fortaleza`;
4. registra novamente os lembretes ainda pendentes.

No horário programado, `enviar_lembrete()` envia a mensagem pelo Telegram e
atualiza o status. Erros da API do Telegram são registrados como falha; não há
política automática de repetição. O hook `encerrar_agendador()` encerra o
agendador quando o processo do bot termina.

O agendador depende do processo estar em execução. Se o computador ou o bot
ficar desligado durante a janela de envio, lembretes vencidos serão expirados
na inicialização seguinte, não enviados retroativamente.

## Arquivos principais

| Arquivo | Responsabilidade |
|---|---|
| `bot.py` | Telegram, menus, fluxo de conversa e integração dos módulos |
| `motor_regras.py` | Cálculo determinístico usando o JSON de regras |
| `pln.py` | Classificação local de intenção com scikit-learn |
| `database.py` | Persistência SQLite dos lembretes |
| `scheduler.py` | APScheduler, envio e atualização dos lembretes |
| `data/regras_pni.json` | Esquemas preliminares e limites de segurança |
| `data/faq.json` | FAQ e mensagem de contato da UBS |
| `data/intencoes_pln.json` | Frases de exemplo do classificador |
| `tests/` | Testes automatizados dos módulos e fluxos |

## Iniciar e testar localmente

No PowerShell, na pasta do projeto:

```powershell
python -m pip install -r requirements.txt
$tokenSeguro = Read-Host "Cole o token do BotFather" -AsSecureString
$env:TELEGRAM_BOT_TOKEN = [System.Net.NetworkCredential]::new("", $tokenSeguro).Password
$env:VACINA_MODO_TESTE = "1"
python bot.py
```

Mantenha o terminal aberto para o polling e os lembretes. Não compartilhe o
token e use somente dados fictícios durante os testes.

Para executar a suíte automatizada:

```powershell
python -m pytest -q
```

## Estado local observado ao escrever este guia

- Não foi encontrado processo `python.exe` executando o bot durante a
  verificação. O bot só está ativo quando `python bot.py` permanece rodando.
- O arquivo `data/lembretes.sqlite3` existe, mas a tabela não tinha registros
  por status no momento da verificação.
- A presença do arquivo SQLite não significa que o bot ou o agendador estejam
  atualmente ativos.
