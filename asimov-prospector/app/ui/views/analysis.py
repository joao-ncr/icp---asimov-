"""Tela 'Nova análise': empresas do Ploomes (somente leitura) e leads novos (CNPJ aberto, com aprovação humana)
analisados em lotes; lista própria e empresa única como contingência."""
from __future__ import annotations
import pandas as pd
import streamlit as st
from app.core.auth import User
from app.database.run_lock import RunInProgress
from app.discovery import generation as discovery_generation
from app.discovery.feed import FeedError
from app.integrations.ploomes.client import PloomesError
from app.integrations.ploomes.sync import SyncReport, SyncTooSoon
from app.ui import data, theme
from app.ui.inputs import MAX_COMPANIES_PER_RUN, TEMPLATE_CSV, dataframe_to_candidates, normalize_input_df, read_uploaded
from app.ui.views.common import RunProgress, explain_busy

DEFAULT_BATCH = 50
BATCH_STEP = 10
SYNC_MESSAGE_KEY = "ploomes_sync_message"
DISCOVERY_MESSAGE_KEY = "discovery_generation_message"


def render(service: str, user: User) -> None:
    theme.hero("Nova análise", "As empresas vêm do Ploomes. Escolha quantas analisar agora; o restante é feito pelo sistema.")
    _steps()
    holder = data.running_now()
    if holder:
        st.warning(f"Há uma tarefa em andamento ({holder['label']}, iniciada em {holder['started_at']}). Novas análises ficam bloqueadas até ela terminar.")
    _ploomes_source(service, user)
    st.divider()
    _discovery_source(service, user)
    st.divider()
    with st.expander("Usar uma lista própria ou testar uma empresa"):
        st.download_button("⬇️ Baixar modelo de lista", TEMPLATE_CSV, "modelo_prospeccao_asimov.csv", "text/csv")
        uploaded = st.file_uploader("Envie uma lista de empresas", type=["csv", "xlsx"], help="Colunas obrigatórias: empresa e site.")
        if uploaded:
            _uploaded_list(uploaded, service, user)
        else:
            _single_company(user)


def _steps() -> None:
    a, b, c = st.columns(3)
    with a:
        theme.step(1, "Sincronize o Ploomes", "Empresas e negócios são lidos do CRM. Nada é alterado no Ploomes.")
    with b:
        theme.step(2, "Escolha o lote", "Analise aos poucos: lotes de 20–50 empresas levam alguns minutos.")
    with c:
        theme.step(3, "Analise", "O sistema visita os sites, identifica sinais e monta o ranking automaticamente.")
    st.write("")


def _ploomes_source(service: str, user: User) -> None:
    st.subheader("📇 Empresas do Ploomes")
    if not data.ploomes_configured():
        st.info("A integração com o Ploomes ainda não está configurada (PLOOMES_USER_KEY). Enquanto isso, use uma lista própria abaixo.")
        return
    message = st.session_state.pop(SYNC_MESSAGE_KEY, None)
    if message:
        st.success(message)
    overview = data.ploomes_overview()
    _last_sync(overview["last_sync"])
    if user.is_admin:
        _sync_button(user)
    else:
        st.caption("A sincronização com o Ploomes é feita por um administrador.")
    summary = overview["summary"]
    if not summary["total"]:
        st.info("Nenhuma empresa sincronizada ainda.")
        return
    _summary_metrics(summary)
    _analyze_pending(summary, service, user)


def _last_sync(last: dict | None) -> None:
    if not last:
        st.caption("O Ploomes ainda não foi sincronizado.")
    elif last["status"] == "error":
        st.warning(f"A última sincronização não terminou: {last['error']}")
    elif last["status"] == "ok":
        st.caption(f"Última sincronização: {_when(last['finished_at'])} (UTC), por {last['triggered_by']}.")


def _when(iso: str | None) -> str:
    return (iso or "")[:16].replace("T", " ")


def _sync_button(user: User) -> None:
    if not st.button("🔄 Sincronizar com o Ploomes", help="Lê empresas e negócios do CRM. Nenhuma informação é alterada no Ploomes."):
        return
    try:
        with st.spinner("Lendo o Ploomes (somente leitura). Pode levar até 2 minutos…"):
            report = data.sync_ploomes(user.username)
    except RunInProgress as exc:
        explain_busy(exc, user)
        return
    except SyncTooSoon as exc:
        st.info(str(exc))
        return
    except PloomesError as exc:
        st.error(f"Não foi possível sincronizar com o Ploomes: {exc}")
        return
    st.session_state[SYNC_MESSAGE_KEY] = _sync_message(report)
    st.rerun()


def _sync_message(r: SyncReport) -> str:
    kind = "completa" if r.full_sync else "incremental"
    return (f"Sincronização {kind} concluída: {r.companies} empresa(s) lidas ({r.with_site} com site, {r.without_site} sem site), "
            f"{r.deals_won} ganho(s), {r.deals_lost} perdido(s) e {r.deals_open} em aberto. "
            f"{r.deals_ignored_pipeline} negócio(s) de outros funis foram ignorados.")


def _summary_metrics(summary: dict) -> None:
    a, b, c, d = st.columns(4)
    a.metric("Empresas no Ploomes", summary["total"])
    b.metric("Com site", summary["with_site"])
    c.metric("Já analisadas", summary["analyzed"])
    d.metric("Aguardando análise", summary["pending_with_site"] + summary["pending_without_site"])
    if summary["without_site"]:
        st.caption(f"{summary['without_site']} empresa(s) estão sem site no CRM: são mantidas e registradas como “sem site”, sem interromper a análise.")


def _analyze_pending(summary: dict, service: str, user: User) -> None:
    pending = summary["pending_with_site"] + summary["pending_without_site"]
    if not pending:
        st.success("Todas as empresas sincronizadas já foram analisadas. Abra **Ranking** para avaliar.")
        return
    limit = min(MAX_COMPANIES_PER_RUN, pending)
    batch = st.number_input("Quantas empresas analisar agora", min_value=1, max_value=limit, value=min(DEFAULT_BATCH, limit), step=BATCH_STEP,
                            help="Empresas com site são analisadas primeiro. Você pode continuar de onde parou a qualquer momento.")
    theme.notice("Cada site é consultado individualmente, por isso a análise leva alguns minutos. O sistema não envia mensagens às empresas e não altera o Ploomes.")
    st.write("")
    if st.button("🚀 Analisar próximas empresas", type="primary", width="stretch"):
        candidates = data.ploomes_pending(int(batch))
        _run(candidates, {"mode": "ploomes", "count": len(candidates), "service": service}, user)


def _discovery_source(service: str, user: User) -> None:
    st.subheader("🧭 Gerar leads novos (dados abertos de CNPJ)")
    if not data.discovery_configured():
        st.caption("Nenhum ICP configurado em config/icp.yaml ainda.")
        return
    message = st.session_state.pop(DISCOVERY_MESSAGE_KEY, None)
    if message:
        st.success(message)
    overview = data.discovery_overview()
    _last_generation(overview["last"])
    if user.is_admin:
        _generation_actions(user)
    else:
        st.caption("A geração de novos leads é feita por um administrador.")
    _pending_review(overview["pending"], service, user)


def _last_generation(last: dict | None) -> None:
    if not last:
        st.caption("Nenhuma geração de leads novos ainda.")
    elif last["status"] == "error":
        st.warning(f"A última geração não terminou: {last['error']}")
    elif last["status"] == "ok":
        st.caption(f"Última geração: {_when(last['finished_at'])} (UTC), por {last['triggered_by']}.")


def _generation_actions(user: User) -> None:
    if not data.discovery_feed_configured():
        _generation_uploader(user)
        return
    st.caption("A lista de empresas é atualizada todo mês a partir da base da Receita, já filtrada pelos ICPs.")
    if st.button("🧭 Buscar lista atualizada e gerar candidatos", type="primary"):
        _generate(user, "Baixando a lista do mês e filtrando pelos ICPs…", lambda: data.run_discovery_from_feed(user.username))
    with st.expander("Enviar um CSV manualmente (contingência)"):
        _generation_uploader(user)


def _generation_uploader(user: User) -> None:
    uploaded = st.file_uploader(
        "Enviar extrato de CNPJ (CSV da Receita, colunas: cnpj,razao_social,nome_fantasia,cnae,uf,municipio,porte,situacao)",
        type=["csv"], key="discovery_csv", help="Filtrado pelos CNAE/UF/município de cada ICP em config/icp.yaml.")
    if uploaded and st.button("🧭 Gerar candidatos a partir do CSV"):
        _generate(user, "Filtrando o CSV pelos ICPs configurados…",
                  lambda: data.run_discovery_generation(uploaded, uploaded.name, user.username))


def _generate(user: User, waiting_message: str, generate) -> None:
    try:
        with st.spinner(waiting_message):
            report = generate()
    except RunInProgress as exc:
        explain_busy(exc, user)
        return
    except discovery_generation.GenerationTooSoon as exc:
        st.info(str(exc))
        return
    except FeedError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"Não foi possível gerar candidatos: {exc}")
        return
    st.session_state[DISCOVERY_MESSAGE_KEY] = (
        f"{report.matched} linha(s) casaram com algum ICP; {report.new_candidates} candidato(s) novo(s) para aprovar "
        f"({report.duplicates} já conhecido(s), {report.skipped_without_cnpj} sem CNPJ).")
    st.rerun()


def _pending_review(pending: list[dict], service: str, user: User) -> None:
    if not pending:
        return
    st.caption(f"{len(pending)} candidato(s) aguardando aprovação. Nenhum entra na análise sem aprovação.")
    df = pd.DataFrame([{"Empresa": r["name"], "CNPJ": r["cnpj"], "Município": r["municipio"] or "—", "UF": r["uf"] or "—",
                        "Por que foi sugerida": r["rationale"]} for r in pending])
    event = st.dataframe(df, hide_index=True, width="stretch", height=min(360, 70 + len(df) * 36),
                         on_select="rerun", selection_mode="multi-row", key="discovery_table")
    picked = [pending[i]["id"] for i in event.selection.rows]
    if not picked:
        st.caption("Selecione uma ou mais linhas para aprovar ou rejeitar.")
        return
    a, b = st.columns(2)
    if a.button(f"✅ Aprovar e analisar {len(picked)} selecionada(s)", type="primary", width="stretch"):
        candidates = data.decide_discovery(picked, True, user.username)
        _run(candidates, {"mode": "discovery", "count": len(candidates), "service": service}, user)
    if b.button(f"❌ Rejeitar {len(picked)} selecionada(s)", width="stretch"):
        data.decide_discovery(picked, False, user.username)
        st.rerun()


def _uploaded_list(uploaded, service: str, user: User) -> None:
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
    st.dataframe(df, hide_index=True, width="stretch", height=min(360, 55 + len(df) * 35))
    if st.button("🚀 Iniciar análise da lista", type="primary", width="stretch"):
        _run(dataframe_to_candidates(df), {"mode": "operation_ui", "count": len(df), "service": service}, user)


def _run(candidates: list, run_cfg: dict, user: User) -> bool:
    """Executa a rodada com progresso. Devolve True se concluiu (falhas individuais não impedem a conclusão)."""
    progress = RunProgress(len(candidates))
    try:
        with st.spinner("Analisando. Sites indisponíveis são registrados individualmente e não interrompem a rodada…"):
            run_id = data.run_analysis(candidates, {**run_cfg, "user": user.username}, progress)
    except RunInProgress as exc:
        explain_busy(exc, user)
        return False
    except Exception as exc:
        st.error(f"A rodada foi interrompida: {exc}. O que já foi analisado ficou salvo; é seguro iniciar novamente.")
        return False
    progress.finish()
    st.session_state["last_run_id"] = run_id
    notes = f"{progress.problems} sem análise completa, sem site ou excluídas" + (f", {progress.skipped} semelhantes a outro lead (analisado só um)" if progress.skipped else "")
    st.success(f"Rodada concluída: {len(candidates)} leads processados; {notes}. Abra **Ranking** para revisar e avaliar.")
    return True


def _single_company(user: User) -> None:
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
        explain_busy(exc, user)
    except Exception as exc:
        st.error(f"Não foi possível analisar o site: {exc}")
    else:
        if result["status"] == "ranked":
            st.success("Empresa analisada. Abra Ranking para revisar o resultado.")
        else:
            st.warning(f"A análise terminou como {result['status']}: {result.get('reason') or 'sem detalhes'}")
