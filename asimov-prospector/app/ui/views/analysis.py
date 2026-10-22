"""Tela 'Nova análise': importar empresas (planilha, base histórica ou uma só) e disparar a análise."""
from __future__ import annotations
import pandas as pd
import streamlit as st
from app.core.utils import norm_domain
from app.database.run_lock import RunInProgress
from app.discovery.historical import HISTORICAL_XLSX
from app.ui import data, theme
from app.ui.inputs import MAX_COMPANIES_PER_RUN, TEMPLATE_CSV, dataframe_to_candidates, normalize_input_df, read_uploaded
from app.ui.views.common import RunProgress, explain_busy


def render(service: str) -> None:
    theme.hero("Nova análise", "Você só precisa fornecer uma lista de empresas. O restante é feito pelo sistema.")
    _steps()
    holder = data.running_now()
    if holder:
        st.warning(f"Há uma análise em andamento ({holder['label']}, iniciada em {holder['started_at']}). Novas análises ficam bloqueadas até ela terminar.")
    _historical_base(service)
    uploaded = st.file_uploader("Envie sua lista de empresas", type=["csv", "xlsx"],
                                help="Aceita a planilha histórica original ou uma lista com colunas empresa e site.")
    if uploaded:
        _uploaded_list(uploaded, service)
    elif not st.session_state.get("use_historical_base"):
        _single_company()


def _steps() -> None:
    a, b, c = st.columns(3)
    with a:
        theme.step(1, "Prepare sua lista", "Baixe o modelo e preencha empresa e site. Município, UF e segmento são opcionais.")
        st.download_button("⬇️ Baixar modelo", TEMPLATE_CSV, "modelo_prospeccao_asimov.csv", "text/csv", use_container_width=True)
    with b:
        theme.step(2, "Envie a lista", "Aceitamos Excel ou CSV. Para o piloto, recomendamos 20–50 empresas.")
    with c:
        theme.step(3, "Analise", "O sistema visita os sites, identifica sinais e monta o ranking automaticamente.")
    st.write("")


def _historical_base(service: str) -> None:
    if HISTORICAL_XLSX.exists() and st.button("📚 Carregar os leads do histórico comercial", use_container_width=True):
        try:
            with st.spinner("Importando a base histórica para o banco…"):
                st.session_state["historical_report"] = data.import_history_base()
            st.session_state["use_historical_base"] = True
        except Exception as exc:
            st.error(f"Não foi possível importar a base histórica: {exc}")
    if not st.session_state.get("use_historical_base"):
        return
    report = st.session_state["historical_report"]
    candidates = data.load_historical_candidates()
    st.success(f"Base histórica no banco: {report.total} leads ({report.with_site} com site, {report.without_site} sem site). "
               f"{report.new_orgs} novos e {report.already_known} já conhecidos; leads de nome ou site semelhante são analisados uma única vez.")
    if report.cnpj_suspect:
        st.warning(f"{report.cnpj_suspect} lead(s) com alerta de CNPJ: o CNPJ não foi usado como identidade e a validação cadastral aparece na avaliação.")
    if report.unmapped_segments:
        st.info("Segmentos sem equivalente no modelo (usarão o perfil padrão): " + ", ".join(report.unmapped_segments))
    st.dataframe(pd.DataFrame([c.model_dump() for c in candidates[:20]]), hide_index=True, use_container_width=True)
    st.caption("Prévia das primeiras 20 linhas. Ao iniciar, o sistema processará a base completa.")
    if st.button("🚀 Analisar base histórica completa", type="primary", use_container_width=True):
        if _run(candidates, {"mode": "historical_base", "count": len(candidates), "service": service}):
            st.session_state["use_historical_base"] = False


def _uploaded_list(uploaded, service: str) -> None:
    try:
        df, warnings = normalize_input_df(read_uploaded(uploaded))
    except Exception as exc:
        st.error(f"Não foi possível ler a planilha: {exc}")
        return
    for w in warnings:
        st.warning(w)
    if df.empty or "name" not in df.columns or "domain" not in df.columns:
        return
    if len(df) > MAX_COMPANIES_PER_RUN:
        st.warning(f"O limite por rodada é {MAX_COMPANIES_PER_RUN} empresas. Apenas as primeiras serão usadas.")
        df = df.head(MAX_COMPANIES_PER_RUN)
    st.success(f"{len(df)} empresa(s) prontas para análise.")
    st.dataframe(df, hide_index=True, use_container_width=True, height=min(360, 55 + len(df) * 35))
    theme.notice("A análise pode levar alguns minutos porque cada site é consultado individualmente. O sistema não envia mensagens para as empresas.")
    st.write("")
    if st.button("🚀 Iniciar análise", type="primary", use_container_width=True):
        _run(dataframe_to_candidates(df), {"mode": "operation_ui", "count": len(df), "service": service})


def _run(candidates: list, run_cfg: dict) -> bool:
    """Executa a rodada com progresso. Devolve True se concluiu (falhas individuais não impedem a conclusão)."""
    progress = RunProgress(len(candidates))
    try:
        with st.spinner("Analisando. Sites indisponíveis são registrados individualmente e não interrompem a rodada…"):
            run_id = data.run_analysis(candidates, run_cfg, progress)
    except RunInProgress as exc:
        explain_busy(exc)
        return False
    except Exception as exc:
        st.error(f"A rodada foi interrompida: {exc}. O que já foi analisado ficou salvo; é seguro iniciar novamente.")
        return False
    progress.finish()
    st.session_state["last_run_id"] = run_id
    notes = f"{progress.problems} sem análise completa ou excluídas" + (f", {progress.skipped} semelhantes a outro lead (analisado só um)" if progress.skipped else "")
    st.success(f"Rodada concluída: {len(candidates)} leads processados; {notes}. Abra **Ranking** para revisar e avaliar.")
    return True


def _single_company() -> None:
    st.divider()
    st.subheader("Quer testar só uma empresa?")
    c1, c2 = st.columns([2, 1])
    url = c1.text_input("Site da empresa", placeholder="https://empresa.com.br")
    name = c2.text_input("Nome", placeholder="Empresa")
    if not st.button("Analisar uma empresa", disabled=not url):
        return
    try:
        with st.spinner("Analisando o site…"):
            result = data.analyze_single(name, url)
    except RunInProgress as exc:
        explain_busy(exc)
    except Exception as exc:
        st.error(f"Não foi possível analisar o site: {exc}")
    else:
        if result["status"] == "ranked":
            st.success("Empresa analisada. Abra Ranking para revisar o resultado.")
        else:
            st.warning(f"A análise terminou como {result['status']}: {result.get('reason') or 'sem detalhes'}")
