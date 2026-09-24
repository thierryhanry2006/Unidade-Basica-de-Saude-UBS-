VACINA – Digitalização do Histórico Vacinal e Lembretes Automáticos para a UBS Centenário

Projeto desenvolvido nas disciplinas de Inteligência Artificial e Big Data e Ciência de Dados, tendo como referência a realidade da UBS Centenário, localizada no bairro Juá, em Riachão – Maranhão.

Equipe

Emilly Karoline Cunha Fernandes

Thierry Hanry Ribeiro da Silva Cardoso

Hágape Latan Mendonça de Sousa

César Kayoma Sousa de Oliveira

Orientador: Alex Rogaleski Marques
Instituição: UNIBALSAS – Balsas, Maranhão
Ano: 2026

1. Sobre o projeto

O projeto surgiu a partir de uma situação observada na sala de vacinação da UBS Centenário. A unidade já utiliza recursos digitais para registrar parte dos atendimentos e das vacinações, mas ainda podem existir registros antigos somente em carteiras ou cadernetas físicas.

Quando essas informações não estão digitalizadas, a consulta do histórico pode ficar mais demorada, principalmente quando é necessário verificar quais vacinas já foram aplicadas, quais doses foram registradas e quais informações ainda precisam ser atualizadas.

A proposta do projeto é facilitar a digitalização, a organização e a consulta desse histórico, diminuindo a dependência de registros exclusivamente físicos.

2. Problema identificado

O problema definido para o projeto é:

Como facilitar a digitalização, organização e consulta do histórico de vacinação dos pacientes da UBS Centenário, reduzindo a dependência de registros exclusivamente físicos?

A situação pode ocorrer quando uma pessoa possui informações antigas em uma caderneta que ainda não foram inseridas no sistema utilizado pela unidade. Além disso, documentos físicos podem ser perdidos, danificados ou apresentar informações difíceis de consultar.

3. Solução proposta

A solução prevê a transformação de informações antigas das cadernetas de vacinação em registros digitais estruturados.

Entre os recursos planejados estão:

uso de OCR para auxiliar na leitura de informações presentes em cartões e cadernetas;

organização dos dados em campos estruturados;

conferência das informações reconhecidas antes da confirmação do cadastro;

consulta do histórico vacinal de forma organizada;

possibilidade de utilizar regras relacionadas a vacina, dose, idade e histórico para futuras orientações;

possibilidade de integração com chatbot e outros canais em etapas futuras.

4. Produto Mínimo Viável (MVP)

O MVP definido para o projeto tem como foco o registro assistido do histórico vacinal.

Fluxo previsto:

Caderneta/cartão
      ||
      \/
      OCR
      ||
      \/
Identificação dos dados
      ||
      \/
Conferência pelo profissional
      ||
      \/
Registro digital estruturado
      ||
      \/
Consulta do histórico

Os principais campos considerados no MVP são:

nome da vacina;

data da aplicação;

dose;

idade;

informações relacionadas ao registro.

A utilização de OCR não elimina a conferência humana. A tecnologia será utilizada como apoio ao profissional, mantendo uma etapa de validação antes da confirmação.

TED 01 – DEFINIÇÃO DO PROBLEMA DE DADOS E SELEÇÃO DO CONJUNTO DE DADOS

5. Conjunto de dados selecionado

Na primeira etapa foram pesquisadas diferentes bases públicas relacionadas às doses aplicadas pelo Programa Nacional de Imunizações. Foram consideradas principalmente as bases do PNI referentes aos anos de 2021, 2023, 2024 e 2025.

Após a comparação, foi selecionada a base:

Doses aplicadas pelo Programa Nacional de Imunizações (PNI) – 2025

A escolha ocorreu pela relação direta com o problema do projeto, pela atualidade dos dados em relação às alternativas analisadas e pela disponibilidade em arquivos e API.

6. Fonte dos dados

Fonte institucional: Ministério da Saúde
Departamento: Departamento do Programa Nacional de Imunizações (DPNI)
Portal: Portal de Dados Abertos do SUS

Acesso ao conjunto

https://dadosabertos.saude.gov.br/dataset/doses-aplicadas-pelo-programa-de-nacional-de-imunizacoes-pni-2025

API utilizada na etapa inicial

https://apidadosabertos.saude.gov.br/vacinacao/doses-aplicadas-pni-2025

Na primeira consulta realizada pela API foi utilizado limit=1000, resultando em 1.000 registros retornados naquela consulta. Esse valor não representa o total da base PNI 2025.

7. Principais atributos identificados

Campo

Descrição

co_vacina

Código da vacina

sg_imunobiologico

Sigla do imunobiológico

ds_nome

Nome da vacina

dt_vacina

Data da vacinação

co_dose_vacina

Código da dose

ds_tipo_dose

Tipo da dose

nu_idade_paciente

Idade do paciente

tp_sexo_paciente

Sexo informado no registro

co_municipio_paciente

Código do município do paciente

no_municipio_paciente

Município do paciente

sg_uf_paciente

UF do paciente

co_cnes_estabelecimento

Código CNES do estabelecimento

no_municipio_estabelecimento

Município do estabelecimento

sg_uf_estabelecimento

UF do estabelecimento

ds_tipo_estabelecimento

Tipo do estabelecimento

ds_vacina_fabricante

Fabricante

ds_via_administracao

Via de administração

ds_local_aplicacao

Local de aplicação

dt_entrada_rnds

Data de entrada do registro na RNDS

co_sistema_origem

Código do sistema de origem

ds_sistema_origem

Sistema de origem

TED 02 – LIMPEZA, SANEAMENTO E ANÁLISE EXPLORATÓRIA

8. Preparação dos dados

Para a TED 02 foram utilizados os 12 arquivos mensais do PNI 2025, correspondentes aos meses de janeiro a dezembro.

vacinacao_jan_2025.csv
vacinacao_fev_2025.csv
vacinacao_mar_2025.csv
vacinacao_abr_2025.csv
vacinacao_mai_2025.csv
vacinacao_jun_2025.csv
vacinacao_jul_2025.csv
vacinacao_ago_2025.csv
vacinacao_set_2025.csv
vacinacao_out_2025.csv
vacinacao_nov_2025.csv
vacinacao_dez_2025.csv

Os arquivos brutos somam aproximadamente 107,7 GB.

Devido ao volume, os dados foram processados em partes (chunks) de 200.000 registros, evitando carregar todo o conjunto na memória de uma única vez.

A leitura também foi ajustada para lidar com diferentes codificações. Por exemplo, o arquivo de abril foi identificado como cp1252.

9. Resultado geral do processamento

Ao final da execução foram processados:

178.451.615 registros

Esse total corresponde à soma dos registros dos 12 arquivos mensais utilizados na análise.

10. Limpeza e saneamento

Durante o processamento foram identificados:

1.056 registros com idade inválida;

0 datas inválidas;

0 registros com dt_deletado_rnds preenchido;

0 duplicidades detectadas na verificação realizada dentro dos blocos de processamento.

As idades válidas totalizaram 178.450.559 registros.

Observação sobre duplicidades

A verificação de duplicidades foi realizada dentro dos blocos utilizados no processamento. Por esse motivo, o resultado deve ser interpretado como 0 duplicidades detectadas nos blocos de processamento, e não como uma deduplicação global completa de todos os registros.

11. Estatísticas da idade

Estatística

Resultado

Quantidade válida

178.450.559

Média

24,22 anos

Mediana

12 anos

Mínimo

0 anos

Máximo

120 anos

Desvio padrão

26,24

Q1

1 ano

Q3

45 anos

IQR

44

A diferença entre média e mediana indica que a distribuição das idades apresenta assimetria, com concentração em idades mais baixas e presença de registros em idades mais elevadas.

12. Outliers

Foi utilizado o método do intervalo interquartil (IQR):

Q1 = 1
Q3 = 45
IQR = 44
Limite superior = 111 anos

Foram identificados:

660 registros acima de 111 anos.

Esses registros foram classificados como valores estatisticamente atípicos pelo critério adotado, mas não foram excluídos automaticamente. A classificação como outlier, por si só, não é suficiente para afirmar que o registro esteja incorreto.

13. Distribuição mensal

Mês

Registros

Janeiro

12.062.476

Fevereiro

9.334.511

Março

9.712.072

Abril

25.913.391

Maio

32.666.708

Junho

20.466.802

Julho

15.226.105

Agosto

11.244.935

Setembro

11.604.457

Outubro

9.973.489

Novembro

10.839.981

Dezembro

9.406.688

Total

178.451.615

O maior volume ocorreu em maio, com 32.666.708 registros. O menor ocorreu em fevereiro, com 9.334.511 registros.

14. Principais vacinas

Vacina

Registros

Influenza trivalente

60.493.978

Hepatite B

11.427.555

dT

11.422.945

VIP

10.601.972

Febre amarela

8.295.176

Penta

6.532.069

Pneumocócica 10-valente

6.248.130

SCR

5.835.854

Meningocócica ACWY

5.016.632

Meningocócica C

4.853.558

A vacina influenza trivalente apresentou aproximadamente 33,90% dos registros analisados.

15. Distribuição das doses

Tipo de dose

Registros

Única

72.246.157

1ª Dose

32.813.074

2ª Dose

24.951.467

Reforço

17.665.180

Dose

14.605.803

3ª Dose

9.155.650

1º Reforço

2.907.869

2º Reforço

2.359.302

Revacinação

801.846

4ª Dose

255.007

A categoria Única foi a mais frequente, com aproximadamente 40,49% do total.

16. Distribuição por sexo

Sexo

Registros

Percentual aproximado

F

96.984.897

54,35%

M

81.459.490

45,65%

I

7.228

0,004%

Total

178.451.615

100%

A categoria I foi mantida exatamente como aparece na base. Não foi atribuída uma interpretação adicional ao código por não ter sido localizada uma definição específica para esse valor na documentação consultada.

17. Distribuição por unidade federativa

UF

Registros

SP

37.532.341

MG

18.339.534

RJ

11.934.495

PR

10.735.663

BA

10.645.711

RS

9.306.957

CE

7.774.212

SC

7.144.636

PE

7.104.152

PA

6.709.744

GO

6.052.722

MA

5.796.555

Também foram encontrados 2.536.082 registros sem UF do paciente informada e 684 registros com o código XX.

O Maranhão apresentou 5.796.555 registros.

18. Valores ausentes

Campo

Ausentes

Percentual

dt_deletado_rnds

178.451.615

100,00%

ds_condicao_maternal

80.533.793

45,13%

ds_categoria

75.593.404

42,36%

ds_via_administracao

7.546.759

4,23%

ds_tipo_estabelecimento

7.491.716

4,20%

ds_local_aplicacao

7.491.219

4,20%

ds_vacina_fabricante

6.917.531

3,88%

sg_uf_paciente

2.536.082

1,42%

Entre as variáveis principais, não foram identificados valores ausentes nos campos co_vacina, co_dose_vacina, dt_vacina, tp_sexo_paciente, nu_idade_paciente, ds_nome, ds_tipo_dose e dt_entrada_rnds.

19. Principais padrões observados

A análise mostrou alguns comportamentos que se destacam:

houve grande variação no volume mensal, com maior concentração em maio;

a vacina influenza trivalente concentrou aproximadamente 33,90% dos registros;

a categoria de dose Única apresentou o maior volume;

a distribuição de idade apresentou diferença significativa entre média e mediana;

existem atributos com alta quantidade de valores ausentes, enquanto os principais campos relacionados diretamente à vacinação apresentam preenchimento completo;

a base possui abrangência nacional, com diferenças consideráveis entre as UFs.

20. Relação com o projeto e o MVP

Os resultados da análise ajudam a compreender quais informações precisam estar presentes em um histórico vacinal estruturado.

A relação principal utilizada pelo projeto pode ser representada como:

Vacina
  ||
  \/
Dose
  ||
  \/
Data
  ||
  \/
Idade / Grupo
  ||
  \/
Histórico
  ||
  \/
Próxima orientação

No MVP, o OCR poderá auxiliar na transformação das informações presentes em uma caderneta física em dados estruturados.

A análise também mostrou a importância de uma etapa de conferência e validação, principalmente porque existem valores inválidos e campos com diferentes níveis de preenchimento.

A base do PNI 2025, entretanto, é utilizada como referência para compreender a estrutura dos registros. Ela não representa o histórico individual dos pacientes da UBS Centenário e não substitui os dados internos da unidade.

21. Limitações

A análise possui algumas limitações:

O conjunto é nacional e não representa diretamente os pacientes da UBS Centenário.

Alguns atributos apresentam grande quantidade de valores ausentes.

Foram identificadas 1.056 idades inválidas.

Foram encontrados 660 valores classificados como outliers superiores pelo método do IQR.

A verificação de duplicidades foi realizada dentro dos blocos de processamento.

O grande volume dos arquivos exige processamento por partes.

Essas características devem ser consideradas nas próximas etapas de desenvolvimento do projeto.

22. Estrutura do repositório

Unidade-Basica-de-Saude-UBS-
│
├── data/
│   ├── raw/
│   │   ├── vacinacao_jan_2025.csv
│   │   ├── vacinacao_fev_2025.csv
│   │   ├── vacinacao_mar_2025.csv
│   │   ├── vacinacao_abr_2025.csv
│   │   ├── vacinacao_mai_2025.csv
│   │   ├── vacinacao_jun_2025.csv
│   │   ├── vacinacao_jul_2025.csv
│   │   ├── vacinacao_ago_2025.csv
│   │   ├── vacinacao_set_2025.csv
│   │   ├── vacinacao_out_2025.csv
│   │   ├── vacinacao_nov_2025.csv
│   │   └── vacinacao_dez_2025.csv
│   │
│   └── processed/
│       ├── 01_contagem_por_arquivo.csv
│       ├── 02_resumo_limpeza.csv
│       ├── 03_totais_limpeza.csv
│       ├── 04_qualidade_colunas.csv
│       ├── 05_estatisticas_idade.csv
│       ├── 06_registros_por_mes.csv
│       ├── 07_top_vacinas.csv
│       ├── 08_distribuicao_doses.csv
│       ├── 09_registros_por_uf.csv
│       ├── 10_distribuicao_sexo.csv
│       ├── 11_idade_por_vacina.csv
│       ├── 12_resumo_final.csv
│       ├── amostra_tratada_1000.csv
│       ├── 01_distribuicao_idade.png
│       ├── 02_registros_por_mes.png
│       ├── 03_top_vacinas.png
│       └── 04_registros_por_uf.png
│
├── docs/
│   ├── TED1.pdf
│   └── TED2.pdf
│
├── notebook/
│   ├── TED1/
│   └── TED2/
│       └── ted02_eda.py
│
└── README.md

23. Como executar a análise

O processamento foi desenvolvido em Python utilizando principalmente:

Python 3;

Pandas;

NumPy;

Matplotlib.

Com o ambiente virtual ativado, as dependências podem ser instaladas com:

python -m pip install pandas numpy matplotlib

Depois, com os arquivos CSV do PNI 2025 na pasta data/raw, o processamento pode ser executado com:

python notebook/TED2/ted02_eda.py

Os resultados são salvos automaticamente em:

data/processed/

24. Dados brutos e GitHub

Os arquivos mensais do PNI 2025 possuem grande volume e, por isso, não são recomendados para armazenamento direto em um repositório Git comum.

Os dados devem ser obtidos diretamente da fonte oficial:

https://dadosabertos.saude.gov.br/dataset/doses-aplicadas-pelo-programa-de-nacional-de-imunizacoes-pni-2025

O repositório deve concentrar o código, os documentos, os resultados gerados e as instruções necessárias para reprodução da análise. Os arquivos brutos podem permanecer localmente ou ser obtidos novamente a partir da fonte oficial quando necessário.

Repositório

https://github.com/thierryhanry2006/Unidade-Basica-de-Saude-UBS-.git

25. Segurança e privacidade

A base pública do PNI utilizada nesta etapa é diferente dos dados pessoais que poderão ser trabalhados futuramente pela UBS.

No desenvolvimento do sistema, informações pessoais dos pacientes deverão receber tratamento adequado, com controle de acesso, medidas de segurança e atenção aos princípios da Lei Geral de Proteção de Dados (LGPD).

A base pública utilizada nesta análise serve como referência para a estruturação dos dados e não deve ser tratada como cadastro de pacientes da UBS Centenário.

26. Considerações finais

A TED 02 ampliou o trabalho iniciado na TED 01, passando da seleção da fonte de dados para a análise de um conjunto nacional de grande volume.

O processamento dos 12 arquivos mensais permitiu trabalhar com 178.451.615 registros e identificar características importantes sobre vacinas, doses, idade, sexo, distribuição geográfica e qualidade dos dados.

Os resultados ajudam a orientar a estrutura do projeto VACINA e fornecem uma referência mais concreta para as próximas etapas de desenvolvimento do sistema.

27. Referências

BRASIL. Ministério da Saúde. Portal de Dados Abertos do SUS – Doses aplicadas pelo Programa Nacional de Imunizações (PNI) – 2025. Brasília: Ministério da Saúde. Disponível em:

https://dadosabertos.saude.gov.br/dataset/doses-aplicadas-pelo-programa-de-nacional-de-imunizacoes-pni-2025

BRASIL. Ministério da Saúde. API de Dados Abertos – Vacinação. Brasília: Ministério da Saúde.

BRASIL. Ministério da Saúde. Programa Nacional de Imunizações – PNI. Brasília: Ministério da Saúde.