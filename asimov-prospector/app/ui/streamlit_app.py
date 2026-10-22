"""Frontend operacional do Asimov Prospector (ponto de entrada do Streamlit).

Fluxo: importar empresas -> analisar -> ranking -> o time comercial avalia em 3 níveis -> o sistema aprende.
Cada tela vive em app/ui/views; acesso a dados em app/ui/data.py; o motor de inteligência fica fora desta camada."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from app.database.db import ensure_ready
from app.scoring.explain import SERVICE_NAMES
from app.ui import data, theme
from app.ui.views import analysis, ranking, review
from app.ui.views.common import learning_panel

PAGES = {"Nova análise": analysis.render, "Ranking": ranking.render, "Avaliar": review.render}

st.set_page_config(page_title="Asimov Jr. · Prospector", page_icon=theme.page_icon(), layout="wide", initial_sidebar_state="expanded")
theme.apply()
ensure_ready()

if "page" not in st.session_state:
    st.session_state["page"] = "Ranking" if data.ranking_rows() else "Nova análise"

with st.sidebar:
    theme.brand()
    page = st.radio("Navegação", list(PAGES), key="page", label_visibility="collapsed")
    st.divider()
    service = st.selectbox("Prioridade de serviço", ["Geral"] + list(SERVICE_NAMES), format_func=lambda s: SERVICE_NAMES.get(s, s))
    st.divider()
    learning_panel(compact=True)
    st.caption("O Prospector pesquisa informações públicas e sugere oportunidades. A decisão comercial continua humana.")

PAGES[page](service)
