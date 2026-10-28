"""TED 03 - Modelagem Preditiva e Machine Learning

Projeto UBS Centenário - base preparada na TED 02.

A tarefa exploratória é classificar o imunobiológico registrado a partir de
idade, sexo, tipo de dose, mês da vacinação e UF do paciente. O modelo não
indica qual vacina uma pessoa deve receber; ele apenas investiga padrões nos
registros nacionais usados nesta atividade.

Execute a partir de qualquer diretório. O script espera estar em:
notebook/TED3/ted03_modelagem.py
"""
from pathlib import Path
import sys
import warnings

import matplotlib.pyplot as plt
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import (
    StratifiedKFold,
    cross_validate,
    train_test_split,
)
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

RANDOM_STATE = 42
TEST_SIZE = 0.20
MIN_CLASS_COUNT = 20
MAX_CV_ROWS = 15000
TARGET = "sg_imunobiologico"
NUMERIC_FEATURES = ["nu_idade_paciente"]
CATEGORICAL_FEATURES = [
    "tp_sexo_paciente",
    "ds_tipo_dose",
    "mes_vacinacao",
    "sg_uf_paciente",
]
REQUIRED_COLUMNS = [TARGET, *NUMERIC_FEATURES, *CATEGORICAL_FEATURES]


def main() -> int:
    # Este script deve ficar em <raiz>/notebook/TED3/.
    project_root = Path(__file__).resolve().parents[2]
    data_path = project_root / "data" / "processed" / "PNI_2025_preparado_github.csv"
    output_dir = project_root / "data" / "processed" / "TED3_resultados"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("TED 03 — CLASSIFICAÇÃO DE REGISTROS DE VACINAÇÃO")
    print("=" * 72)
    print(f"Projeto: {project_root}")
    print(f"Base:    {data_path}")

    if not data_path.exists():
        print("\nERRO: o CSV não foi encontrado no caminho acima.")
        print("Confirme se a base está em data/processed/PNI_2025_preparado_github.csv.")
        return 1

    df = pd.read_csv(data_path, low_memory=False)
    initial_rows = len(df)
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        print("\nERRO: faltam colunas necessárias na base:")
        for col in missing_columns:
            print(f" - {col}")
        print("Colunas disponíveis:", df.columns.tolist())
        return 1

    # Padronização simples dos tipos.
    df[TARGET] = df[TARGET].astype("string").str.strip()
    df["nu_idade_paciente"] = pd.to_numeric(df["nu_idade_paciente"], errors="coerce")
    df = df.dropna(subset=[TARGET])
    df = df[df[TARGET].ne("")].copy()

    # Idades já marcadas como outliers na preparação da TED 02 são excluídas
    # do experimento; a quantidade removida fica registrada para transparência.
    outliers_removed = 0
    if "flag_outlier_idade" in df.columns:
        flags = pd.to_numeric(df["flag_outlier_idade"], errors="coerce").fillna(0)
        outlier_mask = flags.eq(1)
        outliers_removed = int(outlier_mask.sum())
        df = df.loc[~outlier_mask].copy()

    # Evita classes com pouquíssimos exemplos, para que a divisão treino/teste
    # e a validação cruzada estratificadas sejam viáveis. A regra é documentada.
    counts_before_filter = df[TARGET].value_counts()
    eligible_classes = counts_before_filter[counts_before_filter >= MIN_CLASS_COUNT].index
    rare_rows_removed = int((~df[TARGET].isin(eligible_classes)).sum())
    df = df[df[TARGET].isin(eligible_classes)].copy()

    if df[TARGET].nunique() < 2:
        print("\nERRO: restaram menos de duas classes após a preparação.")
        print("Inspecione a distribuição de sg_imunobiologico e ajuste a regra de frequência mínima.")
        return 1

    # Categorias ausentes ou vazias são preservadas como uma categoria explícita.
    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype("string").fillna("Não informado").str.strip()
        df[col] = df[col].replace("", "Não informado").astype(str)

    df["nu_idade_paciente"] = pd.to_numeric(df["nu_idade_paciente"], errors="coerce")

    X = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES].copy()
    y = df[TARGET].astype(str).copy()

    # Resumo dos dados realmente usados.
    resumo = pd.DataFrame(
        {
            "indicador": [
                "registros_originais",
                "registros_sem_alvo_ausente_apos_limpeza",
                "outliers_de_idade_excluidos",
                "registros_de_classes_com_frequencia_menor_que_20_excluidos",
                "registros_usados_na_modelagem",
                "quantidade_de_classes_usadas",
                "idade_ausente_a_ser_imputada",
            ],
            "valor": [
                initial_rows,
                int(len(df) + rare_rows_removed),
                outliers_removed,
                rare_rows_removed,
                len(df),
                y.nunique(),
                int(X["nu_idade_paciente"].isna().sum()),
            ],
        }
    )
    resumo.to_csv(output_dir / "resumo_preparacao.csv", index=False, encoding="utf-8-sig")
    df[TARGET].value_counts().rename_axis(TARGET).reset_index(name="quantidade").to_csv(
        output_dir / "distribuicao_classes.csv", index=False, encoding="utf-8-sig"
    )

    # Gráfico das 15 classes mais frequentes.
    top_classes = df[TARGET].value_counts().head(15).sort_values()
    fig, ax = plt.subplots(figsize=(10, 6))
    top_classes.plot(kind="barh", ax=ax)
    ax.set_title("15 imunobiológicos mais frequentes na amostra usada")
    ax.set_xlabel("Quantidade de registros")
    ax.set_ylabel("Imunobiológico")
    fig.tight_layout()
    fig.savefig(output_dir / "top_15_imunobiologicos.png", dpi=160)
    plt.close(fig)

    # Separação estratificada mantém aproximadamente as proporções das classes.
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,
    )

    numeric_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    categorical_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", numeric_transformer, NUMERIC_FEATURES),
            ("categorical", categorical_transformer, CATEGORICAL_FEATURES),
        ],
        remainder="drop",
    )

    # A validação cruzada usa somente uma amostra do conjunto de treino para
    # manter o K-NN viável em computadores pessoais. O teste fica reservado.
    if len(X_train) > MAX_CV_ROWS:
        X_cv, _, y_cv, _ = train_test_split(
            X_train,
            y_train,
            train_size=MAX_CV_ROWS,
            random_state=RANDOM_STATE,
            stratify=y_train,
        )
    else:
        X_cv, y_cv = X_train, y_train

    min_cv_class = int(y_cv.value_counts().min())
    n_splits = min(3, min_cv_class)
    if n_splits < 2:
        print("\nERRO: não há exemplos suficientes por classe para validação cruzada.")
        print("Considere aumentar a amostra ou rever MIN_CLASS_COUNT.")
        return 1

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE)
    scoring = {
        "acuracia": "accuracy",
        "precisao_macro": "precision_macro",
        "recall_macro": "recall_macro",
        "f1_macro": "f1_macro",
    }

    candidates = []
    for depth in [5, 10, 15]:
        candidates.append(
            (
                f"Arvore_decisao_depth_{depth}",
                Pipeline(
                    steps=[
                        ("preparacao", preprocessor),
                        (
                            "modelo",
                            DecisionTreeClassifier(
                                max_depth=depth,
                                class_weight="balanced",
                                random_state=RANDOM_STATE,
                            ),
                        ),
                    ]
                ),
            )
        )
    for k in [3, 5, 7]:
        candidates.append(
            (
                f"KNN_k_{k}",
                Pipeline(
                    steps=[
                        ("preparacao", preprocessor),
                        ("modelo", KNeighborsClassifier(n_neighbors=k, weights="distance", n_jobs=-1)),
                    ]
                ),
            )
        )

    cv_rows = []
    fitted_candidates = {}
    print(f"\nRegistros para modelagem: {len(df):,}".replace(",", "."))
    print(f"Classes consideradas: {y.nunique()}")
    print(f"Treino: {len(X_train):,} | teste reservado: {len(X_test):,}".replace(",", "."))
    print(f"Validação cruzada: {n_splits} dobras em {len(X_cv):,} registros do treino".replace(",", "."))
    print("\nIniciando comparação por validação cruzada. O K-NN pode demorar mais...\n")

    for name, pipeline in candidates:
        print(f"Avaliando {name}...")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            scores = cross_validate(
                pipeline,
                X_cv,
                y_cv,
                cv=cv,
                scoring=scoring,
                n_jobs=1,
                error_score="raise",
                return_train_score=False,
            )
        row = {"modelo": name}
        for metric in scoring:
            values = scores[f"test_{metric}"]
            row[f"{metric}_media"] = float(values.mean())
            row[f"{metric}_desvio"] = float(values.std())
        row["tempo_fit_segundos_media"] = float(scores["fit_time"].mean())
        row["tempo_avaliacao_segundos_media"] = float(scores["score_time"].mean())
        cv_rows.append(row)
        fitted_candidates[name] = pipeline

    cv_results = pd.DataFrame(cv_rows).sort_values("f1_macro_media", ascending=False)
    cv_results.to_csv(output_dir / "comparacao_validacao_cruzada.csv", index=False, encoding="utf-8-sig")
    print("\nResumo da validação cruzada (ordenado por F1 macro):")
    print(
        cv_results[["modelo", "acuracia_media", "precisao_macro_media", "recall_macro_media", "f1_macro_media"]]
        .round(4)
        .to_string(index=False)
    )

    # Seleção pelo F1 macro da validação cruzada; o teste não participa da escolha.
    selected_name = str(cv_results.iloc[0]["modelo"])
    selected_model = fitted_candidates[selected_name]
    print(f"\nModelo selecionado pela validação cruzada: {selected_name}")
    selected_model.fit(X_train, y_train)
    y_pred = selected_model.predict(X_test)

    dummy = DummyClassifier(strategy="most_frequent")
    dummy.fit(X_train, y_train)
    y_dummy = dummy.predict(X_test)

    def metrics_row(name: str, actual, predicted) -> dict:
        return {
            "modelo": name,
            "acuracia": accuracy_score(actual, predicted),
            "precisao_macro": precision_score(actual, predicted, average="macro", zero_division=0),
            "recall_macro": recall_score(actual, predicted, average="macro", zero_division=0),
            "f1_macro": f1_score(actual, predicted, average="macro", zero_division=0),
        }

    test_metrics = pd.DataFrame(
        [metrics_row("Linha_de_base_classe_mais_frequente", y_test, y_dummy),
         metrics_row(selected_name, y_test, y_pred)]
    )
    test_metrics.to_csv(output_dir / "metricas_teste.csv", index=False, encoding="utf-8-sig")

    labels = sorted(y.unique())
    matrix = confusion_matrix(y_test, y_pred, labels=labels)
    matrix_df = pd.DataFrame(matrix, index=labels, columns=labels)
    matrix_df.index.name = "real_previsto"
    matrix_df.to_csv(output_dir / "matriz_confusao.csv", encoding="utf-8-sig")

    report = classification_report(y_test, y_pred, labels=labels, zero_division=0)
    (output_dir / "relatorio_classificacao.txt").write_text(
        f"Modelo selecionado: {selected_name}\n\n{report}\n",
        encoding="utf-8",
    )

    print("\nMétricas no teste reservado:")
    print(test_metrics.round(4).to_string(index=False))
    print("\nRelatório de classificação do modelo selecionado:")
    print(report)
    print("\nArquivos gerados em:", output_dir)
    print("- resumo_preparacao.csv")
    print("- distribuicao_classes.csv")
    print("- top_15_imunobiologicos.png")
    print("- comparacao_validacao_cruzada.csv")
    print("- metricas_teste.csv")
    print("- matriz_confusao.csv")
    print("- relatorio_classificacao.txt")
    print("\nAtenção: interprete os números com cautela. A base é uma amostra nacional, não o histórico individual de pacientes da UBS.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nExecução interrompida pelo usuário. Nenhum arquivo da base original foi modificado.")
        raise SystemExit(130)
