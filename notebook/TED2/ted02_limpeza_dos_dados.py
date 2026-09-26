from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE = 200_000
SAMPLE_PER_MONTH = 5_000
RANDOM_SEED = 2026

# Campos lidos da fonte. Identificadores são usados somente para
# deduplicação e amostragem.
USECOLS = [
    "co_documento",
    "tp_sexo_paciente",
    "co_municipio_paciente",
    "no_municipio_paciente",
    "sg_uf_paciente",
    "co_cnes_estabelecimento",
    "no_municipio_estabelecimento",
    "sg_uf_estabelecimento",
    "co_vacina",
    "sg_imunobiologico",
    "ds_nome",
    "dt_vacina",
    "co_dose_vacina",
    "ds_tipo_dose",
    "ds_vacina_fabricante",
    "dt_entrada_rnds",
    "co_sistema_origem",
    "ds_sistema_origem",
    "nu_idade_paciente",
    "ds_via_administracao",
    "ds_local_aplicacao",
    "co_estrategia_vacinacao",
    "no_estrategia",
]

PUBLIC_COLUMNS = [
    "tp_sexo_paciente",
    "co_municipio_paciente",
    "no_municipio_paciente",
    "sg_uf_paciente",
    "co_cnes_estabelecimento",
    "no_municipio_estabelecimento",
    "sg_uf_estabelecimento",
    "co_vacina",
    "sg_imunobiologico",
    "ds_nome",
    "dt_vacina",
    "co_dose_vacina",
    "ds_tipo_dose",
    "ds_vacina_fabricante",
    "nu_idade_paciente",
    "ds_via_administracao",
    "ds_local_aplicacao",
    "co_estrategia_vacinacao",
    "no_estrategia",
    "mes_vacinacao",
    "flag_outlier_idade",
]

REQUIRED_COLUMNS = [
    "co_documento",
    "co_vacina",
    "ds_nome",
    "dt_vacina",
    "co_dose_vacina",
    "ds_tipo_dose",
    "nu_idade_paciente",
]

FILES = sorted(RAW_DIR.glob("vacinacao_*_2025.csv"))

if len(FILES) != 12:
    raise SystemExit(
        f"Esperados 12 CSVs mensais do PNI 2025, encontrados: {len(FILES)} em {RAW_DIR}"
    )

# Frequência de idades 0..120 para calcular Q1/Q3/IQR de forma exata
# sem guardar todos os registros na memória.
age_counts = np.zeros(121, dtype=np.int64)

# Amostra determinística por mês: guardamos as menores hashes de co_documento.
samples_by_month = {}
reports = []

global_totals = {
    "registros_lidos": 0,
    "datas_invalidas": 0,
    "idades_ausentes": 0,
    "idades_invalidas": 0,
    "registros_sem_campos_essenciais": 0,
    "duplicidades_nos_blocos": 0,
}


def read_chunks(path):
    encodings = ["cp1252", "utf-8-sig", "utf-8", "latin1"]
    last_error = None

    for enc in encodings:
        try:
            # Valida o cabeçalho antes do processamento completo.
            pd.read_csv(
                path,
                sep=";",
                encoding=enc,
                usecols=USECOLS,
                dtype="string",
                nrows=5,
                low_memory=True,
            )

            print(f"   Codificação: {enc}")

            return pd.read_csv(
                path,
                sep=";",
                encoding=enc,
                usecols=USECOLS,
                dtype="string",
                chunksize=CHUNK_SIZE,
                low_memory=True,
                on_bad_lines="warn",
            )
        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        f"Não foi possível ler {path.name}: {last_error}"
    )


def normalize_text(df):
    text_cols = df.select_dtypes(include=["string", "object"]).columns
    for col in text_cols:
        df[col] = df[col].astype("string").str.strip()
        df[col] = df[col].replace(
            {"": pd.NA, "nan": pd.NA, "None": pd.NA, "NULL": pd.NA, "null": pd.NA}
        )

    for col in ["tp_sexo_paciente", "sg_uf_paciente", "sg_uf_estabelecimento"]:
        df[col] = df[col].str.upper()

    return df


def add_sample_candidates(current, cleaned, month_key):
    """Mantém, de forma determinística, as 5.000 menores hashes do mês."""
    if cleaned.empty:
        return current

    work = cleaned.copy()
    # Hash do identificador é usado apenas para amostragem e não é exportado.
    work["_sample_hash"] = pd.util.hash_pandas_object(
        work["co_documento"].fillna(""), index=False
    ).astype("uint64")

    if current is not None and not current.empty:
        work = pd.concat([current, work], ignore_index=True)

    work = work.nsmallest(SAMPLE_PER_MONTH, "_sample_hash")
    return work


for i, path in enumerate(FILES, start=1):
    month_key = path.stem.replace("vacinacao_", "").replace("_2025", "")
    print(f"\n[{i}/12] Processando {path.name}")

    rows = 0
    invalid_dates = 0
    missing_ages = 0
    invalid_ages = 0
    missing_required = 0
    duplicate_in_chunks = 0
    sample = None

    reader = read_chunks(path)

    for chunk_no, chunk in enumerate(reader, start=1):
        if chunk.empty:
            continue

        rows += len(chunk)
        global_totals["registros_lidos"] += len(chunk)

        chunk = normalize_text(chunk)

        # Data
        dt = pd.to_datetime(chunk["dt_vacina"], errors="coerce")
        raw_date_present = chunk["dt_vacina"].notna()
        invalid_dates_here = int((raw_date_present & dt.isna()).sum())
        invalid_dates += invalid_dates_here
        global_totals["datas_invalidas"] += invalid_dates_here
        chunk["dt_vacina"] = dt

        # Idade
        age = pd.to_numeric(chunk["nu_idade_paciente"], errors="coerce")
        missing_here = int(age.isna().sum())
        missing_ages += missing_here
        global_totals["idades_ausentes"] += missing_here

        invalid_age_mask = age.notna() & ~age.between(0, 120)
        invalid_age_here = int(invalid_age_mask.sum())
        invalid_ages += invalid_age_here
        global_totals["idades_invalidas"] += invalid_age_here
        chunk["nu_idade_paciente"] = age

        # Campos essenciais
        missing_required_mask = chunk[REQUIRED_COLUMNS].isna().any(axis=1)
        missing_required_here = int(missing_required_mask.sum())
        missing_required += missing_required_here
        global_totals["registros_sem_campos_essenciais"] += missing_required_here

        # Remove, para a base preparada, linhas que não podem cumprir o núcleo do registro.
        clean = chunk.loc[~missing_required_mask].copy()
        clean = clean.loc[clean["dt_vacina"].notna()]
        clean = clean.loc[clean["nu_idade_paciente"].between(0, 120)]

        # Duplicidade dentro do chunk, pelo identificador original.
        dup_mask = clean["co_documento"].duplicated(keep="first")
        duplicate_here = int(dup_mask.sum())
        duplicate_in_chunks += duplicate_here
        global_totals["duplicidades_nos_blocos"] += duplicate_here
        clean = clean.loc[~dup_mask].copy()

        # Atualiza distribuição global de idade.
        if not clean.empty:
            ages_int = clean["nu_idade_paciente"].round().astype(int)
            counts = np.bincount(ages_int, minlength=121)
            age_counts += counts[:121]

            sample = add_sample_candidates(sample, clean, month_key)

        if chunk_no % 10 == 0:
            print(f"   bloco {chunk_no:,} | registros lidos: {rows:,}")

    samples_by_month[month_key] = sample

    report = {
        "mes": month_key,
        "arquivo": path.name,
        "registros_lidos": rows,
        "datas_invalidas": invalid_dates,
        "idades_ausentes": missing_ages,
        "idades_invalidas": invalid_ages,
        "registros_sem_campos_essenciais": missing_required,
        "duplicidades_detectadas_nos_blocos": duplicate_in_chunks,
        "registros_selecionados_para_base_preparada": 0 if sample is None else len(sample),
    }
    reports.append(report)

    print(f"   Concluído: {rows:,} registros lidos")

# Quartis exatos de idade e IQR
valid_total = int(age_counts.sum())


def weighted_quantile(counts, q):
    total = int(counts.sum())
    if total == 0:
        return np.nan
    target = q * (total - 1)
    cumulative = 0
    for age_value, freq in enumerate(counts):
        if cumulative + int(freq) > target:
            return float(age_value)
        cumulative += int(freq)
    return float(len(counts) - 1)

q1 = weighted_quantile(age_counts, 0.25)
q3 = weighted_quantile(age_counts, 0.75)
iqr = q3 - q1
lower_bound = q1 - 1.5 * iqr
upper_bound = q3 + 1.5 * iqr

# Monta a base preparada pública
prepared_parts = []

for month_key in sorted(samples_by_month):
    sample = samples_by_month[month_key]
    if sample is None or sample.empty:
        continue

    out = sample.copy()

    out["mes_vacinacao"] = month_key
    out["flag_outlier_idade"] = (
        (out["nu_idade_paciente"] < lower_bound)
        | (out["nu_idade_paciente"] > upper_bound)
    ).astype("int8")

    out["dt_vacina"] = out["dt_vacina"].dt.strftime("%Y-%m-%d")
    out["nu_idade_paciente"] = out["nu_idade_paciente"].round().astype("int16")

    # Para evitar ambiguidade em categorias faltantes, usa-se uma representação explícita.
    categorical_cols = [
        "tp_sexo_paciente",
        "sg_uf_paciente",
        "sg_uf_estabelecimento",
        "ds_vacina_fabricante",
        "ds_via_administracao",
        "ds_local_aplicacao",
        "no_estrategia",
    ]
    for col in categorical_cols:
        out[col] = out[col].fillna("NAO_INFORMADO")

    out = out[PUBLIC_COLUMNS].copy()
    prepared_parts.append(out)

prepared = pd.concat(prepared_parts, ignore_index=True)

# Limpeza global somente dentro da base preparada (que é pequena e versionável).
prepared = prepared.drop_duplicates(
    subset=["dt_vacina", "co_vacina", "co_dose_vacina", "ds_nome",
            "nu_idade_paciente", "sg_uf_paciente", "co_municipio_paciente",
            "co_cnes_estabelecimento", "tp_sexo_paciente"],
    keep="first"
)

prepared = prepared.sort_values(
    ["dt_vacina", "co_vacina", "co_dose_vacina"]
).reset_index(drop=True)

# Arquivos de saída
prepared_path = OUT_DIR / "PNI_2025_preparado_github.csv"
prepared.to_csv(
    prepared_path,
    index=False,
    encoding="utf-8-sig",
)

# Relatório baseado no processamento de TODOS os 12 arquivos.
report_df = pd.DataFrame(reports)
report_df.to_csv(
    OUT_DIR / "relatorio_limpeza_completo.csv",
    index=False,
    encoding="utf-8-sig",
)

# Regras aplicadas.
rules = pd.DataFrame([
    ["Dados originais", "Arquivos de data/raw preservados sem alteração."],
    ["Leitura", "CSV lido em chunks de 200.000 registros."],
    ["Texto", "Espaços externos removidos; strings vazias e marcadores de ausência normalizados."],
    ["Sexo/UF", "Valores textuais padronizados em letras maiúsculas."],
    ["Data", "dt_vacina convertida para data; datas inválidas não entram na base preparada."],
    ["Idade", "nu_idade_paciente convertida para número; somente 0 a 120 anos entram na base preparada."],
    ["Campos essenciais", "Registros sem os campos essenciais definidos foram excluídos da base preparada."],
    ["Duplicidades", "Duplicidades detectadas dentro dos chunks foram retiradas da base preparada durante o processamento."],
    ["Outliers", "Valores acima do limite do IQR são sinalizados em flag_outlier_idade; não são apagados automaticamente."],
    ["Privacidade/versionamento", "Identificadores de paciente não são gravados na base preparada para o GitHub."],
    ["Volume", "A base preparada do GitHub contém até 5.000 registros válidos por mês, total máximo de 60.000."],
], columns=["etapa", "tratamento"])
rules.to_csv(
    OUT_DIR / "regras_limpeza_dos_dados.csv",
    index=False,
    encoding="utf-8-sig",
)

summary = pd.DataFrame([
    ["Registros lidos nos 12 arquivos", global_totals["registros_lidos"]],
    ["Datas inválidas identificadas", global_totals["datas_invalidas"]],
    ["Idades ausentes identificadas", global_totals["idades_ausentes"]],
    ["Idades inválidas identificadas", global_totals["idades_invalidas"]],
    ["Registros sem campos essenciais", global_totals["registros_sem_campos_essenciais"]],
    ["Duplicidades detectadas nos chunks", global_totals["duplicidades_nos_blocos"]],
    ["Idades válidas para estatísticas", valid_total],
    ["Q1", q1],
    ["Q3", q3],
    ["IQR", iqr],
    ["Limite inferior de outlier", lower_bound],
    ["Limite superior de outlier", upper_bound],
    ["Registros na base preparada para GitHub", len(prepared)],
], columns=["indicador", "valor"])
summary.to_csv(
    OUT_DIR / "resumo_base_preparada.csv",
    index=False,
    encoding="utf-8-sig",
)

print("\n" + "=" * 70)
print("LIMPEZA E PREPARAÇÃO CONCLUÍDAS")
print("=" * 70)
print(f"Registros lidos nos 12 arquivos: {global_totals['registros_lidos']:,}")
print(f"Idades inválidas identificadas: {global_totals['idades_invalidas']:,}")
print(f"Datas inválidas identificadas: {global_totals['datas_invalidas']:,}")
print(f"Duplicidades detectadas nos chunks: {global_totals['duplicidades_nos_blocos']:,}")
print(f"IQR: {iqr}")
print(f"Limite superior de outlier: {upper_bound}")
print(f"Base preparada para GitHub: {len(prepared):,} registros")
print(f"Arquivo: {prepared_path}")
print(f"Tamanho do arquivo preparado: {prepared_path.stat().st_size / (1024**2):.2f} MB")
print("=" * 70)