"""Leitura e normalizacao de planilhas enviadas pelo usuario (sem dependencia do Streamlit; testavel)."""
from __future__ import annotations
import pandas as pd
from app.core.utils import norm_domain
from app.models.schemas import Candidate

MAX_COMPANIES_PER_RUN = 500
COLUMN_ALIASES = {
    "empresa": "name", "nome": "name", "empresa_nome": "name", "lead": "name",
    "site": "domain", "site/canal": "domain", "url": "domain", "website": "domain", "dominio": "domain",
    "município": "municipio", "cidade": "municipio", "estado": "uf", "segmento": "segment",
}
# Marcadores comerciais de ausência de site não devem ser tratados como URLs.
MISSING_SITE_MARKERS = {"sem site/canal informado", "sem site informado", "não informado", "nao informado", "n/a", "-", "inconclusivo", "nan"}
HEADER_ROWS_TO_TRY = (0, 3, 2, 1, 4)     # o histórico consolidado tem o cabeçalho real na 4ª linha

TEMPLATE_CSV = (
    "empresa,site,municipio,uf,segmento\n"
    "Exemplo Industrial,https://exemplo.com.br,Itajubá,MG,industria\n"
).encode("utf-8")


def normalize_input_df(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Padroniza colunas e remove repetidos. Devolve (tabela, avisos); se faltar coluna obrigatória, os avisos são erros."""
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df.rename(columns=COLUMN_ALIASES, inplace=True)
    errors = []
    if "name" not in df.columns:
        errors.append("Inclua uma coluna chamada 'empresa' ou 'Lead'.")
    if "domain" not in df.columns:
        errors.append("Inclua uma coluna chamada 'site' ou 'Site/canal'.")
    if errors:
        return df, errors
    for col in ("municipio", "uf", "segment"):
        if col not in df.columns:
            df[col] = ""
    for col in ("name", "domain", "municipio", "uf", "segment"):
        df[col] = df[col].fillna("").astype(str).str.strip()
    df = df[(df["name"] != "") | (df["domain"] != "")].copy()
    df["domain"] = df["domain"].apply(lambda x: "" if x.lower() in MISSING_SITE_MARKERS else (norm_domain(x) or "" if x else ""))
    # Domínios repetidos são removidos; empresas sem site são preservadas pelo nome.
    with_domain = df[df["domain"] != ""].drop_duplicates(subset=["domain"], keep="first")
    without_domain = df[df["domain"] == ""].drop_duplicates(subset=["name"], keep="first")
    df = pd.concat([with_domain, without_domain], ignore_index=True).drop_duplicates(subset=["name"], keep="first")
    missing = int((df["domain"] == "").sum())
    warnings = [f"{missing} empresa(s) sem site serão preservadas como 'sem site informado', sem interromper a análise."] if missing else []
    return df, warnings


def dataframe_to_candidates(df: pd.DataFrame) -> list[Candidate]:
    return [
        Candidate(name=str(r["name"]), domain=str(r["domain"]), municipio=str(r.get("municipio", "")) or None,
                  uf=str(r.get("uf", "")) or None, segment=str(r.get("segment", "")) or None, source="ui_operation")
        for _, r in df.iterrows()
    ]


def read_uploaded(uploaded) -> pd.DataFrame:
    if not uploaded.name.lower().endswith(".xlsx"):
        return pd.read_csv(uploaded)
    uploaded.seek(0)
    xls = pd.ExcelFile(uploaded)
    for sheet in xls.sheet_names:
        for header_row in HEADER_ROWS_TO_TRY:
            try:
                candidate = pd.read_excel(xls, sheet_name=sheet, header=header_row)
            except Exception:
                continue
            cols = {str(c).strip().lower() for c in candidate.columns}
            if cols & {"empresa", "lead", "name"} and cols & {"site", "site/canal", "domain", "url"}:
                return candidate
    raise ValueError("Não encontrei uma aba com nome da empresa e site. Use o arquivo histórico padronizado ou uma planilha com colunas empresa e site.")
