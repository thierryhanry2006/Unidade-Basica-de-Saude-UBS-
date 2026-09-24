from pathlib import Path
from collections import Counter, defaultdict
import math
import time

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


CHUNK_SIZE = 200_000

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Colunas existentes no cabeçalho real do PNI 2025
USECOLS = [
    "co_documento",
    "co_paciente",
    "tp_sexo_paciente",
    "co_municipio_paciente",
    "no_municipio_paciente",
    "sg_uf_paciente",
    "co_cnes_estabelecimento",
    "no_municipio_estabelecimento",
    "sg_uf_estabelecimento",
    "co_vacina",
    "sg_imunobiologico",
    "dt_vacina",
    "co_dose_vacina",
    "ds_tipo_dose",
    "ds_vacina_fabricante",
    "dt_entrada_rnds",
    "co_sistema_origem",
    "ds_sistema_origem",
    "nu_idade_paciente",
    "no_uf_paciente",
    "ds_nome",
    "ds_tipo_estabelecimento",
    "co_estrategia_vacinacao",
    "no_estrategia",
    "ds_via_administracao",
    "ds_local_aplicacao",
    "ds_categoria",
    "ds_condicao_maternal",
    "dt_deletado_rnds",
]

files = sorted(RAW_DIR.glob("*.csv"))

if not files:
    raise SystemExit(
        f"Nenhum CSV encontrado em: {RAW_DIR}"
    )

print("=" * 75)
print("TED 02 - PNI 2025 | PROCESSAMENTO EM CHUNKS")
print("=" * 75)
print(f"Arquivos encontrados: {len(files)}")

for f in files:
    print(f" - {f.name} | {f.stat().st_size / (1024**3):.2f} GB")

# acumuladores 
total_rows = 0
duplicate_extras = 0
invalid_dates = 0
missing_dates = 0
invalid_ages = 0
missing_ages = 0
valid_ages = 0
deleted_marked = 0

file_counts = Counter()
month_counts = Counter()
vaccine_counts = Counter()
dose_counts = Counter()
uf_counts = Counter()
sex_counts = Counter()

# Frequência global de idade (0 a 120)
age_counts = Counter()

# Idade por vacina:
# chave -> [n, soma, soma_quadrado, mínimo, máximo, Counter(idade)]
age_by_vaccine = defaultdict(
    lambda: [0, 0.0, 0.0, math.inf, -math.inf, Counter()]
)

missing_counts = {c: 0 for c in USECOLS}

sample_saved = False
start = time.perf_counter()


def clean_text(s):
    return s.astype("string").str.strip()


def weighted_quantile(counter, q):
    total = sum(counter.values())
    if total == 0:
        return np.nan

    target = q * (total - 1)
    acc = 0

    for value in sorted(counter):
        freq = counter[value]
        if acc + freq > target:
            return float(value)
        acc += freq

    return float(max(counter))


def std_from_sums(n, total, total_sq):
    if n <= 1:
        return np.nan

    variance = (
        total_sq - (total * total) / n
    ) / (n - 1)

    return math.sqrt(max(variance, 0))


def counter_to_csv(counter, columns, filename, limit=None):
    items = counter.most_common(limit)
    rows = []

    for key, value in items:
        if not isinstance(key, tuple):
            key = (key,)

        row = {
            column: (
                "Não informado"
                if pd.isna(key[i]) or key[i] == ""
                else key[i]
            )
            for i, column in enumerate(columns)
        }
        row["registros"] = int(value)
        rows.append(row)

    pd.DataFrame(rows).to_csv(
        OUT_DIR / filename,
        index=False,
        encoding="utf-8-sig",
    )



def criar_leitor_csv(path):
   
    codificacoes = [
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin1",
    ]

    ultimo_erro = None

    for encoding in codificacoes:
        try:
            # Validação rápida do cabeçalho e de algumas linhas.
            pd.read_csv(
                path,
                sep=";",
                encoding=encoding,
                usecols=USECOLS,
                dtype="string",
                nrows=10,
                low_memory=True,
            )

            print(f"   Codificação identificada: {encoding}")

            return pd.read_csv(
                path,
                sep=";",
                encoding=encoding,
                usecols=USECOLS,
                dtype="string",
                chunksize=CHUNK_SIZE,
                low_memory=True,
                on_bad_lines="warn",
            )

        except Exception as exc:
            ultimo_erro = exc

    raise RuntimeError(
        f"Não foi possível identificar a codificação de {path.name}. "
        f"Último erro: {ultimo_erro}"
    )


# PROCESSAMENTO

for file_number, path in enumerate(files, start=1):

    print(
        f"\n[{file_number}/{len(files)}] "
        f"Processando {path.name}"
    )

    rows_this_file = 0

    try:
        reader = criar_leitor_csv(path)
    except Exception as exc:
        raise SystemExit(
            f"\nErro ao abrir {path.name}:\n{exc}"
        )

    for chunk_number, chunk in enumerate(reader, start=1):

        if chunk.empty:
            continue

        # 1. Limpeza textual e valores ausentes
        for col in USECOLS:
            chunk[col] = clean_text(chunk[col])

            missing_counts[col] += int(
                chunk[col].isna().sum()
                + chunk[col].eq("").sum()
            )

        n = len(chunk)
        total_rows += n
        rows_this_file += n

        # 2. Duplicidades por co_documento dentro de cada bloco
       
        duplicate_extras += int(
            chunk["co_documento"]
            .dropna()
            .duplicated(keep="first")
            .sum()
        )

        
        # 3. Data da vacinação

        raw_date = chunk["dt_vacina"]
        nonempty_date = (
            raw_date.notna()
            & raw_date.ne("")
        )

        date = pd.to_datetime(
            raw_date,
            errors="coerce"
        )

        missing_dates += int(
            (~nonempty_date).sum()
        )

        invalid_dates += int(
            (nonempty_date & date.isna()).sum()
        )

        valid_date = date.notna()

        if valid_date.any():
            months = (
                date.loc[valid_date]
                .dt.to_period("M")
                .astype(str)
            )
            month_counts.update(
                months.value_counts().to_dict()
            )

        
        # 4. Idade
        
        raw_age = chunk["nu_idade_paciente"]
        nonempty_age = (
            raw_age.notna()
            & raw_age.ne("")
        )

        age = pd.to_numeric(
            raw_age,
            errors="coerce"
        )

        valid_age = (
            age.notna()
            & age.between(0, 120)
        )

        invalid_age = (
            nonempty_age
            & (
                age.isna()
                | ~age.between(0, 120)
            )
        )

        missing_ages += int((~nonempty_age).sum())
        invalid_ages += int(invalid_age.sum())

        valid = age.loc[valid_age]

        valid_ages += len(valid)

        if len(valid):
            age_int = valid.round().astype(int)
            age_counts.update(
                age_int.value_counts().to_dict()
            )

        
        # 5. Vacinas
        
        g = (
            chunk.groupby(
                [
                    "co_vacina",
                    "sg_imunobiologico",
                    "ds_nome",
                ],
                dropna=False
            )
            .size()
        )

        for key, value in g.items():
            vaccine_counts[
                tuple(
                    "Não informado"
                    if pd.isna(v) or v == ""
                    else str(v)
                    for v in key
                )
            ] += int(value)

        
        # 6. Doses
        
        g = (
            chunk.groupby(
                [
                    "co_dose_vacina",
                    "ds_tipo_dose",
                ],
                dropna=False
            )
            .size()
        )

        for key, value in g.items():
            dose_counts[
                tuple(
                    "Não informado"
                    if pd.isna(v) or v == ""
                    else str(v)
                    for v in key
                )
            ] += int(value)

        # 7. UF e sexo

        uf_counts.update(
            chunk["sg_uf_paciente"]
            .fillna("Não informado")
            .replace("", "Não informado")
            .value_counts()
            .to_dict()
        )

        sex_counts.update(
            chunk["tp_sexo_paciente"]
            .fillna("Não informado")
            .replace("", "Não informado")
            .value_counts()
            .to_dict()
        )

        # 8. Idade por vacina

        age_part = chunk.loc[
            valid_age,
            [
                "co_vacina",
                "sg_imunobiologico",
                "ds_nome",
            ]
        ].copy()

        age_part["idade"] = valid.values

        if not age_part.empty:
            grouped = (
                age_part.groupby(
                    [
                        "co_vacina",
                        "sg_imunobiologico",
                        "ds_nome",
                    ],
                    dropna=False
                )
            )

            for key, part in grouped:

                normalized_key = tuple(
                    "Não informado"
                    if pd.isna(v) or v == ""
                    else str(v)
                    for v in key
                )

                ages = part["idade"].round().astype(int)

                state = age_by_vaccine[
                    normalized_key
                ]

                state[0] += len(ages)
                state[1] += float(ages.sum())
                state[2] += float(
                    (ages ** 2).sum()
                )
                state[3] = min(
                    state[3],
                    int(ages.min())
                )
                state[4] = max(
                    state[4],
                    int(ages.max())
                )
                state[5].update(
                    ages.value_counts().to_dict()
                )

        # 9. Indicador dt_deletado_rnds

        deleted_marked += int(
            (
                chunk["dt_deletado_rnds"].notna()
                & chunk["dt_deletado_rnds"].ne("")
            ).sum()
        )

        # 10. Pequena amostra tratada para documentação

        if not sample_saved:

            sample = chunk.head(1000).copy()

            sample["dt_vacina"] = pd.to_datetime(
                sample["dt_vacina"],
                errors="coerce"
            ).dt.strftime("%Y-%m-%d")

            sample["nu_idade_paciente"] = pd.to_numeric(
                sample["nu_idade_paciente"],
                errors="coerce"
            )

            sample.to_csv(
                OUT_DIR / "amostra_tratada_1000.csv",
                index=False,
                encoding="utf-8-sig",
            )

            sample_saved = True

        if chunk_number % 10 == 0:
            print(
                f"   bloco {chunk_number:,} | "
                f"registros no arquivo: {rows_this_file:,}"
            )

    file_counts[path.name] = rows_this_file

    print(
        f"Concluído: {path.name} | "
        f"{rows_this_file:,} registros"
    )


# ESTATÍSTICAS DE IDADE E OUTLIERS


if valid_ages:
    age_sum = sum(
        idade * freq
        for idade, freq in age_counts.items()
    )

    age_sum_sq = sum(
        (idade ** 2) * freq
        for idade, freq in age_counts.items()
    )

    age_mean = age_sum / valid_ages
    age_median = weighted_quantile(
        age_counts,
        0.50
    )
    age_min = min(age_counts)
    age_max = max(age_counts)
    age_std = std_from_sums(
        valid_ages,
        age_sum,
        age_sum_sq
    )

    q1 = weighted_quantile(age_counts, 0.25)
    q3 = weighted_quantile(age_counts, 0.75)
    iqr = q3 - q1

    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    outliers_low = sum(
        freq
        for idade, freq in age_counts.items()
        if idade < lower
    )

    outliers_high = sum(
        freq
        for idade, freq in age_counts.items()
        if idade > upper
    )
else:
    age_mean = age_median = age_min = age_max = age_std = np.nan
    q1 = q3 = iqr = lower = upper = np.nan
    outliers_low = outliers_high = 0


# CSVs DE RESULTADO


pd.DataFrame(
    [
        {
            "arquivo": name,
            "registros": count,
        }
        for name, count in sorted(file_counts.items())
    ]
).to_csv(
    OUT_DIR / "01_contagem_por_arquivo.csv",
    index=False,
    encoding="utf-8-sig",
)

pd.DataFrame(
    [
        {
            "indicador": "Registros inicialmente lidos",
            "quantidade": total_rows,
            "tratamento": "Mantidos; a fonte original não é alterada.",
        },
        {
            "indicador": "Duplicidades detectadas nos blocos",
            "quantidade": duplicate_extras,
            "tratamento": "Identificadas para avaliação; não removidas da fonte.",
        },
        {
            "indicador": "Datas ausentes",
            "quantidade": missing_dates,
            "tratamento": "Mantidas e ignoradas apenas nos cálculos dependentes de data.",
        },
        {
            "indicador": "Datas inválidas",
            "quantidade": invalid_dates,
            "tratamento": "Convertidas para valor inválido/NaT nas análises.",
        },
        {
            "indicador": "Idades ausentes",
            "quantidade": missing_ages,
            "tratamento": "Mantidas; ignoradas apenas nas estatísticas de idade.",
        },
        {
            "indicador": "Idades inválidas",
            "quantidade": invalid_ages,
            "tratamento": "Não utilizadas nas estatísticas; intervalo válido adotado: 0 a 120.",
        },
        {
            "indicador": "Registros com dt_deletado_rnds preenchida",
            "quantidade": deleted_marked,
            "tratamento": "Sinalizados como indicador de qualidade; não removidos automaticamente.",
        },
    ]
).to_csv(
    OUT_DIR / "02_resumo_limpeza.csv",
    index=False,
    encoding="utf-8-sig",
)

pd.DataFrame(
    [
        {
            "total_inicial": total_rows,
            "duplicidades_nos_blocos": duplicate_extras,
            "datas_ausentes": missing_dates,
            "datas_invalidas": invalid_dates,
            "idades_ausentes": missing_ages,
            "idades_invalidas": invalid_ages,
            "idade_validas": valid_ages,
            "registros_dt_deletado_rnds": deleted_marked,
        }
    ]
).to_csv(
    OUT_DIR / "03_totais_limpeza.csv",
    index=False,
    encoding="utf-8-sig",
)

pd.DataFrame(
    [
        {
            "coluna": col,
            "registros": total_rows,
            "valores_ausentes": missing_counts[col],
            "percentual_ausentes": (
                missing_counts[col] / total_rows * 100
                if total_rows else np.nan
            ),
        }
        for col in USECOLS
    ]
).sort_values(
    "percentual_ausentes",
    ascending=False
).to_csv(
    OUT_DIR / "04_qualidade_colunas.csv",
    index=False,
    encoding="utf-8-sig",
)

pd.DataFrame(
    [
        ["Quantidade válida", valid_ages],
        ["Média", age_mean],
        ["Mediana", age_median],
        ["Mínimo", age_min],
        ["Máximo", age_max],
        ["Desvio padrão", age_std],
        ["Q1", q1],
        ["Q3", q3],
        ["IQR", iqr],
        ["Limite inferior de outlier", lower],
        ["Limite superior de outlier", upper],
        ["Outliers inferiores", outliers_low],
        ["Outliers superiores", outliers_high],
    ],
    columns=["estatistica", "valor"]
).to_csv(
    OUT_DIR / "05_estatisticas_idade.csv",
    index=False,
    encoding="utf-8-sig",
)

pd.DataFrame(
    [
        {"mes": m, "registros": c}
        for m, c in sorted(month_counts.items())
    ]
).to_csv(
    OUT_DIR / "06_registros_por_mes.csv",
    index=False,
    encoding="utf-8-sig",
)

counter_to_csv(
    vaccine_counts,
    [
        "co_vacina",
        "sg_imunobiologico",
        "ds_nome",
    ],
    "07_top_vacinas.csv",
    limit=None,
)

counter_to_csv(
    dose_counts,
    [
        "co_dose_vacina",
        "ds_tipo_dose",
    ],
    "08_distribuicao_doses.csv",
    limit=None,
)

counter_to_csv(
    uf_counts,
    ["uf"],
    "09_registros_por_uf.csv",
    limit=None,
)

counter_to_csv(
    sex_counts,
    ["sexo"],
    "10_distribuicao_sexo.csv",
    limit=None,
)

age_vaccine_rows = []

for key, state in age_by_vaccine.items():

    n, total, total_sq, min_age, max_age, freq = state

    age_vaccine_rows.append(
        {
            "co_vacina": key[0],
            "sg_imunobiologico": key[1],
            "ds_nome": key[2],
            "quantidade_idade_valida": n,
            "media_idade": total / n,
            "mediana_idade": weighted_quantile(freq, 0.50),
            "minimo_idade": min_age,
            "maximo_idade": max_age,
            "desvio_padrao_idade": std_from_sums(
                n,
                total,
                total_sq
            ),
        }
    )

pd.DataFrame(age_vaccine_rows).sort_values(
    "quantidade_idade_valida",
    ascending=False
).head(50).to_csv(
    OUT_DIR / "11_idade_por_vacina.csv",
    index=False,
    encoding="utf-8-sig",
)

pd.DataFrame(
    [
        ["Total de registros lidos", total_rows],
        ["Arquivos CSV", len(files)],
        ["Idades válidas", valid_ages],
        ["Idades inválidas", invalid_ages],
        ["Datas inválidas", invalid_dates],
        ["Duplicidades detectadas nos blocos", duplicate_extras],
        ["Outliers inferiores de idade", outliers_low],
        ["Outliers superiores de idade", outliers_high],
    ],
    columns=["indicador", "valor"]
).to_csv(
    OUT_DIR / "12_resumo_final.csv",
    index=False,
    encoding="utf-8-sig",
)


# GRÁFICOS


age_plot = pd.DataFrame(
    sorted(age_counts.items()),
    columns=["idade", "registros"]
)

if not age_plot.empty:
    plt.figure(figsize=(10, 6))
    plt.bar(
        age_plot["idade"],
        age_plot["registros"]
    )
    plt.title("Distribuição da idade dos pacientes")
    plt.xlabel("Idade")
    plt.ylabel("Quantidade de registros")
    plt.tight_layout()
    plt.savefig(
        OUT_DIR / "01_distribuicao_idade.png",
        dpi=150
    )
    plt.close()

month_plot = pd.DataFrame(
    sorted(month_counts.items()),
    columns=["mes", "registros"]
)

if not month_plot.empty:
    plt.figure(figsize=(12, 6))
    plt.bar(
        month_plot["mes"],
        month_plot["registros"]
    )
    plt.title("Registros de vacinação por mês - 2025")
    plt.xlabel("Mês")
    plt.ylabel("Quantidade de registros")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(
        OUT_DIR / "02_registros_por_mes.png",
        dpi=150
    )
    plt.close()

top_vaccines = (
    pd.DataFrame(
        [
            {
                "vacina": (
                    key[2]
                    if key[2] != "Não informado"
                    else key[0]
                ),
                "registros": value,
            }
            for key, value in vaccine_counts.items()
        ]
    )
    .sort_values("registros", ascending=False)
    .head(10)
    .sort_values("registros")
)

if not top_vaccines.empty:
    plt.figure(figsize=(10, 6))
    plt.barh(
        top_vaccines["vacina"].astype(str),
        top_vaccines["registros"]
    )
    plt.title("10 principais vacinas registradas")
    plt.xlabel("Quantidade de registros")
    plt.ylabel("Vacina")
    plt.tight_layout()
    plt.savefig(
        OUT_DIR / "03_top_vacinas.png",
        dpi=150
    )
    plt.close()

top_uf = (
    pd.DataFrame(
        [
            {"uf": key, "registros": value}
            for key, value in uf_counts.items()
        ]
    )
    .sort_values("registros", ascending=False)
    .head(15)
    .sort_values("registros")
)

if not top_uf.empty:
    plt.figure(figsize=(10, 6))
    plt.barh(
        top_uf["uf"].astype(str),
        top_uf["registros"]
    )
    plt.title("Registros de vacinação por UF")
    plt.xlabel("Quantidade de registros")
    plt.ylabel("UF")
    plt.tight_layout()
    plt.savefig(
        OUT_DIR / "04_registros_por_uf.png",
        dpi=150
    )
    plt.close()


# FINAL


minutes = (time.perf_counter() - start) / 60

print("\n" + "=" * 75)
print("PROCESSAMENTO CONCLUÍDO")
print("=" * 75)
print(f"Registros lidos: {total_rows:,}")
print(f"Arquivos: {len(files)}")
print(f"Idades válidas: {valid_ages:,}")
print(f"Idades inválidas: {invalid_ages:,}")
print(f"Datas inválidas: {invalid_dates:,}")
print(f"Duplicidades detectadas nos blocos: {duplicate_extras:,}")
print(f"Média de idade: {age_mean:.2f}")
print(f"Mediana de idade: {age_median:.2f}")
print(f"Tempo total: {minutes:.2f} min")
print(f"\nResultados: {OUT_DIR}")
print("=" * 75)
