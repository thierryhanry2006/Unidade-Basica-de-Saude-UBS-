# VACINA — visão geral do protótipo

Este projeto é um protótipo acadêmico de assistente virtual pelo Telegram
para a UBS Maria Luiza. Um modelo de linguagem (Claude, Groq ou Google
Gemini) conversa com o
usuário, consulta a base de conhecimento da UBS e aciona ferramentas do
sistema — cálculo da próxima dose pelo motor de regras e gestão de lembretes.
O bot, o motor de regras e os lembretes rodam no processo `python bot.py`.

## Arquitetura do assistente

```
Telegram (texto ou áudio)
   └─► bot.py ─► assistente.py ─► Claude, Groq ou Gemini (entende e decide)
                     │                 │ pede uma ferramenta
                     │◄────────────────┘
                     ├─ ferramentas.py
                     │    • calcular_proxima_dose → motor_regras.py
                     │    • agendar_lembrete / listar_meus_lembretes /
                     │      cancelar_lembrete    → database.py + scheduler.py
                     └─ resposta em linguagem natural ao usuário
```

- **O modelo nunca calcula datas**: as instruções obrigam o uso de
  `calcular_proxima_dose`, e `agendar_lembrete` só aceita datas que o motor
  calculou na própria conversa.
- **Base de conhecimento**: `data/base_ubs.md`, enviada ao modelo a cada
  mensagem. Itens marcados `[A CONFIRMAR]` ainda não foram validados pela UBS.
- **Memória**: os últimos 8 turnos de cada conversa ficam só em memória e
  expiram após 30 minutos sem uso; `/start` apaga a memória.
- **Provedor**, em ordem de prioridade: `ANTHROPIC_API_KEY` (Claude),
  `GROQ_API_KEY` (Groq) e `GEMINI_API_KEY` (Gemini). Sem nenhuma chave, o bot
  volta ao classificador local (`pln.py`).
- **Áudio**: o Gemini entende áudio diretamente. Com Claude ou Groq, o áudio é
  transcrito antes (Whisper no Groq, se houver `GROQ_API_KEY`; senão, Gemini).
- **Tempo limite**: cada requisição ao provedor espera no máximo 25 s e a
  resposta completa, 90 s; depois disso o usuário recebe uma mensagem de falha.
- **Memória com o Claude**: o raciocínio do modelo fica vinculado ao histórico
  exato da conversa. Por isso as instruções ficam fixas durante a conversa e, ao
  cortar mensagens antigas, os blocos de raciocínio guardados são removidos.
- Os botões do `/start` continuam funcionando como atalho.

Variáveis de ambiente:

| Variável | Uso |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token do bot (obrigatória) |
| `ANTHROPIC_API_KEY` | Chave da Anthropic; ativa o assistente com Claude |
| `CLAUDE_MODEL` | Opcional; padrão `claude-opus-5-5` (ex.: `claude-haiku-5-5`, mais barato) |
| `CLAUDE_EFFORT` | Opcional; esforço de raciocínio, padrão `low` |
| `GROQ_API_KEY` | Chave do console.groq.com; ativa o Groq e a transcrição de áudio |
| `GROQ_MODEL` | Opcional; padrão `qwen/qwen3.8-27b` |
| `GROQ_TRANSCRIPTION_MODEL` | Opcional; padrão `whisper-large-v3-turbo` |
| `GEMINI_API_KEY` | Chave do Google AI Studio; ativa o Gemini ou a transcrição de áudio |
| `GEMINI_MODEL` | Opcional; padrão `gemini-flash-latest` |
| `GEMINI_MODEL_RESERVA` | Opcional; modelo usado quando o principal está sobrecarregado |
| `VACINA_MODO_TESTE` | `1` libera cálculos de simulação com regras não validadas |
| `VACINA_DB_PATH` | Caminho do SQLite (no Docker: `/data/lembretes.sqlite3`) |

No plano gratuito do Gemini as mensagens podem ser usadas pelo Google para
melhorar seus modelos: use apenas dados fictícios nos testes.

## Situação e limites atuais

- O canal implementado é Telegram. WhatsApp não está integrado.
- As regras em `data/regras_pni.json` foram transcritas da Instrução Normativa
  do Calendário Nacional de Vacinação 2026 (4ª edição, 08/10/2026) e cobrem 11
  vacinas: pentavalente, VIP, rotavírus, pneumocócica, meningocócica C/ACWY,
  febre amarela, tríplice viral, varicela, hepatite B (a partir de 7 anos),
  dengue e dT. A transcrição ainda precisa ser conferida pela sala de vacina:
  `status_validacao_clinica` está como `pendente_ubs` e
  `liberado_para_uso_em_producao` está como `false`.
- A data prevista é a mais tardia entre a idade recomendada (agenda oportuna)
  e o intervalo desde a última dose. Doses atrasadas, situações especiais,
  gestantes e grupos prioritários são encaminhados à UBS.
- Sem `VACINA_MODO_TESTE=1`, o bot não calcula nem recomenda datas enquanto as
  regras não forem validadas pela equipe da UBS.
- Com `VACINA_MODO_TESTE=1`, o bot pode calcular e enviar mensagens reais à
  conta Telegram conectada, identificando o resultado como simulação.
- O FAQ e os dados de contato são editáveis em `data/faq.json`; endereço e
  horário já são os oficiais, mas o telefone ainda está pendente.
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
| `assistente.py` | Ciclo com o Gemini: instruções, memória e chamadas de ferramenta |
| `ferramentas.py` | Ferramentas que o modelo pode acionar no sistema |
| `data/base_ubs.md` | Base de conhecimento da UBS usada pelo assistente |
| `motor_regras.py` | Cálculo determinístico usando o JSON de regras |
| `pln.py` | Classificação local de intenção com scikit-learn |
| `database.py` | Persistência SQLite dos lembretes |
| `scheduler.py` | APScheduler, envio e atualização dos lembretes |
| `data/regras_pni.json` | Esquemas do CNV 2026 e limites de segurança |
| `data/faq.json` | FAQ e mensagem de contato da UBS |
| `data/intencoes_pln.json` | Frases de exemplo do classificador |
| `tests/` | Testes automatizados dos módulos e fluxos |

## Iniciar e testar localmente

No PowerShell, na pasta `chatbot-vacinas`:

```powershell
python -m pip install -r requirements-dev.txt
$tokenSeguro = Read-Host "Cole o token do BotFather" -AsSecureString
$env:TELEGRAM_BOT_TOKEN = [System.Net.NetworkCredential]::new("", $tokenSeguro).Password
$env:VACINA_MODO_TESTE = "1"
$chaveSegura = Read-Host "Cole a chave do Gemini" -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new("", $chaveSegura).Password
python bot.py
```

O `Read-Host` não pede senha: ele espera o token do BotFather colado
(Ctrl+V ou botão direito) e o oculta na tela. Mantenha o terminal aberto para
o polling e os lembretes. Não compartilhe o token e use somente dados
fictícios durante os testes.

`requirements.txt` contém apenas as dependências de execução (usadas no
deploy); `requirements-dev.txt` acrescenta o pytest.

Para executar a suíte automatizada:

```powershell
python -m pytest -q
```

## Hospedagem para demonstração (Railway)

O bot roda como um processo contínuo (polling + agendador), em uma única
instância, com o SQLite em um volume persistente. O `Dockerfile` desta pasta
gera a imagem (Python 3.13) e já define `VACINA_DB_PATH=/data/lembretes.sqlite3`.

1. Crie uma conta em https://railway.com e conecte sua conta do GitHub.
2. **New Project → Deploy from GitHub repo** e escolha este repositório.
3. No serviço criado, em **Settings**:
   - **Root Directory**: `chatbot-vacinas`
   - **Branch**: a branch que será demonstrada (por exemplo, `dev`).
   - Não gere domínio público: o bot não recebe acessos HTTP.
4. Em **Variables**, adicione:
   - `TELEGRAM_BOT_TOKEN` = token do BotFather
   - `VACINA_MODO_TESTE` = `1` (enquanto as regras não forem validadas)
   - `ANTHROPIC_API_KEY` = chave da Anthropic (ativa o assistente com Claude)
   - `GEMINI_API_KEY` = chave do Google AI Studio (opcional: transcrição de áudio)
5. Clique com o botão direito no serviço → **Attach Volume** e use o
   mount path `/data`. Sem o volume, os lembretes são apagados a cada deploy.
6. Faça o deploy e acompanhe em **Deployments → View logs**. A inicialização
   correta mostra `Application started`.

Cuidados:

- Mantenha **uma única réplica** e **não rode o bot localmente com o mesmo
  token** enquanto ele estiver no Railway: duas instâncias fazendo polling geram
  erro `Conflict` no Telegram e podem duplicar lembretes. Para testar
  localmente, crie um segundo bot no BotFather.
- O token nunca deve ir para o código ou para o Git; apenas para as variáveis
  do Railway. Os logs do `httpx` (que exibiriam o token na URL) são silenciados
  em `bot.py`.
- Cada push na branch configurada dispara um novo deploy automaticamente.
- Esta configuração serve para demonstração. Uso com pacientes reais exige
  backup do SQLite, monitoramento e, de preferência, servidor no Brasil.
