"""Frontend operacional do Asimov Prospector.

A interface foi desenhada para usuários não técnicos: importar empresas,
analisar, revisar oportunidades e exportar. O motor de inteligência permanece
separado desta camada.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.core.settings import get_settings
from app.core.utils import norm_domain
from app.database.db import connect, init_db, now
from app.discovery.dedup import upsert_org
from app.models.schemas import Candidate
from app.pipeline import WebPageSource, analyze_org, ranking, run_pipeline, start_run
from app.scoring.score import SERVICES


st.set_page_config(
    page_title="Asimov Prospector",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Visual identity
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .stApp { background: #f6f7f9; }
    [data-testid="stSidebar"] { background: #111827; }
    [data-testid="stSidebar"] * { color: #f3f4f6 !important; }
    .brand { padding: 8px 0 22px 0; }
    .brand-mark { font-size: 28px; font-weight: 800; letter-spacing: -1px; }
    .brand-sub { color: #9ca3af; font-size: 13px; margin-top: 2px; }
    .hero { background: white; border: 1px solid #e5e7eb; border-radius: 18px; padding: 28px 30px; margin-bottom: 20px; }
    .hero h1 { margin: 0 0 8px 0; font-size: 34px; letter-spacing: -1.2px; color: #111827; }
    .hero p { margin: 0; color: #6b7280; font-size: 16px; }
    .card { background: white; border: 1px solid #e5e7eb; border-radius: 16px; padding: 20px; margin-bottom: 14px; }
    .card-title { font-size: 18px; font-weight: 700; color: #111827; margin-bottom: 5px; }
    .muted { color: #6b7280; font-size: 13px; }
    .pill { display:inline-block; padding: 4px 9px; border-radius: 999px; font-size: 12px; font-weight: 700; background:#eef2ff; color:#3730a3; }
    .score { font-size: 32px; font-weight: 800; color: #111827; line-height: 1; }
    .score-label { color:#6b7280; font-size:12px; margin-top:4px; }
    .step { background:white; border:1px solid #e5e7eb; border-radius:14px; padding:16px; height:100%; }
    .step-num { display:inline-flex; width:28px; height:28px; align-items:center; justify-content:center; border-radius:50%; background:#111827; color:white; font-weight:700; margin-bottom:10px; }
    .step-title { font-weight:700; color:#111827; }
    .step-text { color:#6b7280; font-size:13px; margin-top:4px; }
    div[data-testid="stMetric"] { background: white; border: 1px solid #e5e7eb; padding: 14px 16px; border-radius: 14px; }
    .notice { background:#f3f4f6; border-radius:12px; padding:12px 14px; color:#4b5563; font-size:13px; }
    </style>
    """,
    unsafe_allow_html=True,
)

conn = connect()
init_db(conn)
s = get_settings()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def confidence_label(mult: float, facts: int) -> str:
    if mult >= 0.78 and facts >= 2:
        return "Alta"
    if mult >= 0.62 and facts >= 1:
        return "Média"
    return "Baixa"


def confidence_icon(label: str) -> str:
    return {"Alta": "🟢", "Média": "🟡", "Baixa": "🔴"}.get(label, "⚪")


def normalize_input_df(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    aliases = {
        "empresa": "name", "nome": "name", "empresa_nome": "name",
        "site": "domain", "url": "domain", "website": "domain", "dominio": "domain",
        "município": "municipio", "cidade": "municipio", "estado": "uf", "segmento": "segment",
    }
    df.rename(columns={k: v for k, v in aliases.items()}, inplace=True)
    errors: list[str] = []
    if "name" not in df.columns:
        errors.append("Inclua uma coluna chamada 'empresa'.")
    if "domain" not in df.columns:
        errors.append("Inclua uma coluna chamada 'site'.")
    if errors:
        return df, errors
    for col in ("municipio", "uf", "segment"):
        if col not in df.columns:
            df[col] = ""
    for col in ("name", "domain", "municipio", "uf", "segment"):
        df[col] = df[col].fillna("").astype(str).str.strip()
    df = df[(df["name"] != "") | (df["domain"] != "")].copy()
    df["domain"] = df["domain"].apply(lambda x: norm_domain(x) if x else "")
    df = df.drop_duplicates(subset=["domain"], keep="first")
    bad = int((df["domain"] == "").sum())
    if bad:
        errors.append(f"{bad} empresa(s) sem site foram ignoradas.")
        df = df[df["domain"] != ""].copy()
    return df, errors


def dataframe_to_candidates(df: pd.DataFrame) -> list[Candidate]:
    return [
        Candidate(
            name=str(r["name"]), domain=str(r["domain"]),
            municipio=str(r.get("municipio", "")) or None,
            uf=str(r.get("uf", "")) or None,
            segment=str(r.get("segment", "")) or None,
            source="ui_operation",
        )
        for _, r in df.iterrows()
    ]


def read_uploaded(uploaded) -> pd.DataFrame:
    if uploaded.name.lower().endswith(".xlsx"):
        return pd.read_excel(uploaded)
    return pd.read_csv(uploaded)


def template_bytes() -> bytes:
    return (
        "empresa,site,municipio,uf,segmento\n"
        "Exemplo Industrial,https://exemplo.com.br,Itajubá,MG,industria\n"
    ).encode("utf-8")


def current_rows(service: str, top: int):
    return ranking(conn, service=None if service == "Geral" else service)[:top]


def result_dataframe(rows):
    return pd.DataFrame([
        {
            "#": r["rank"],
            "Empresa": r["name"],
            "Fit": round(r["final"], 1),
            "Confiança": f"{confidence_icon(confidence_label(r['evidence_multiplier'], len(r['explanation'].get('facts', []))))} {confidence_label(r['evidence_multiplier'], len(r['explanation'].get('facts', [])))}",
            "Oportunidade": r["best_service"],
            "Hipótese": r["explanation"].get("hypothesis") or "—",
            "Site": r["domain"],
        }
        for r in rows
    ])


def export_csv(rows) -> bytes:
    return result_dataframe(rows).to_csv(index=False).encode("utf-8-sig")


def export_xlsx(rows) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        result_dataframe(rows).to_excel(writer, index=False, sheet_name="Oportunidades")
    return bio.getvalue()


def feedback_count() -> int:
    return int(conn.execute("SELECT COUNT(*) FROM human_feedback").fetchone()[0])


def analysis_count() -> int:
    return int(conn.execute("SELECT COUNT(*) FROM analysis").fetchone()[0])


def last_run():
    return conn.execute("SELECT id, started_at, finished_at, config, metrics FROM search_run ORDER BY id DESC LIMIT 1").fetchone()

# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-mark">◈ Asimov</div><div class="brand-sub">Prospector · Operação</div></div>', unsafe_allow_html=True)
    page = st.radio(
        "",
        ["Visão geral", "Nova prospecção", "Oportunidades", "Detalhe"],
        label_visibility="collapsed",
    )
    st.divider()
    service = st.selectbox("Prioridade de serviço", ["Geral"] + SERVICES, index=0)
    top = st.slider("Oportunidades exibidas", 5, 50, 10)
    st.divider()
    st.caption("O Prospector pesquisa informações públicas e sugere oportunidades. A decisão comercial continua humana.")

rows = current_rows(service, top)

# ---------------------------------------------------------------------------
# Visão geral
# ---------------------------------------------------------------------------
if page == "Visão geral":
    st.markdown(
        '<div class="hero"><h1>Encontre as próximas oportunidades.</h1><p>O Prospector analisa empresas, identifica sinais de problemas e organiza quem merece atenção primeiro.</p></div>',
        unsafe_allow_html=True,
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Oportunidades no ranking", len(rows))
    m2.metric("Alta confiança", sum(confidence_label(r["evidence_multiplier"], len(r["explanation"].get("facts", []))) == "Alta" for r in rows))
    m3.metric("Empresas analisadas", analysis_count())
    m4.metric("Avaliações da equipe", feedback_count())

    st.subheader("Como funciona")
    c1, c2, c3, c4 = st.columns(4)
    for col, n, title, text in [
        (c1, "1", "Escolha empresas", "Use uma planilha com empresas que você quer investigar."),
        (c2, "2", "Deixe o sistema analisar", "O Prospector consulta os sites públicos e procura sinais relevantes."),
        (c3, "3", "Revise o ranking", "Veja quem tem maior Fit, confiança e oportunidade de serviço."),
        (c4, "4", "Dê seu parecer", "A equipe marca o que é bom ou ruim para melhorar a calibração."),
    ]:
        with col:
            st.markdown(f'<div class="step"><div class="step-num">{n}</div><div class="step-title">{title}</div><div class="step-text">{text}</div></div>', unsafe_allow_html=True)

    st.write("")
    st.subheader("Top oportunidades")
    if rows:
        st.dataframe(result_dataframe(rows), hide_index=True, use_container_width=True, height=min(500, 48 + len(rows) * 43))
        st.info("💡 O Fit indica compatibilidade com o perfil de oportunidade da Asimov. Não representa probabilidade de fechamento.")
    else:
        st.info("Ainda não há oportunidades. Vá em **Nova prospecção** para começar.")

# ---------------------------------------------------------------------------
# Nova prospecção
# ---------------------------------------------------------------------------
elif page == "Nova prospecção":
    st.markdown('<div class="hero"><h1>Nova prospecção</h1><p>Você só precisa fornecer uma lista de empresas. O restante é feito pelo sistema.</p></div>', unsafe_allow_html=True)

    a, b, c = st.columns(3)
    with a:
        st.markdown('<div class="step"><div class="step-num">1</div><div class="step-title">Prepare sua lista</div><div class="step-text">Baixe o modelo e preencha empresa e site. Município, UF e segmento são opcionais.</div></div>', unsafe_allow_html=True)
        st.download_button("⬇️ Baixar modelo", template_bytes(), "modelo_prospeccao_asimov.csv", "text/csv", use_container_width=True)
    with b:
        st.markdown('<div class="step"><div class="step-num">2</div><div class="step-title">Envie a lista</div><div class="step-text">Aceitamos Excel ou CSV. Para o piloto, recomendamos 20–50 empresas.</div></div>', unsafe_allow_html=True)
    with c:
        st.markdown('<div class="step"><div class="step-num">3</div><div class="step-title">Analise</div><div class="step-text">O sistema visita os sites, identifica sinais e monta o ranking automaticamente.</div></div>', unsafe_allow_html=True)

    st.write("")
    uploaded = st.file_uploader("Envie sua lista de empresas", type=["csv", "xlsx"], help="Colunas obrigatórias: empresa e site.")
    if uploaded:
        try:
            df, warnings = normalize_input_df(read_uploaded(uploaded))
            for w in warnings:
                st.warning(w)
            if len(df) > 200:
                st.warning("O piloto aceita até 200 empresas por rodada. Apenas as primeiras 200 serão usadas.")
                df = df.head(200)
            if not df.empty:
                st.success(f"{len(df)} empresa(s) prontas para análise.")
                st.dataframe(df, hide_index=True, use_container_width=True, height=min(360, 55 + len(df) * 35))
                st.markdown('<div class="notice">A análise pode levar alguns minutos porque cada site é consultado individualmente. O sistema não envia mensagens para as empresas.</div>', unsafe_allow_html=True)
                st.write("")
                if st.button("🚀 Iniciar análise", type="primary", use_container_width=True):
                    candidates = dataframe_to_candidates(df)
                    progress = st.progress(0.0)
                    status_box = st.empty()
                    state = {"done": 0, "errors": 0}

                    def callback(name, result):
                        state["done"] += 1
                        if result["status"] in {"error", "blocked", "inconclusive"}:
                            state["errors"] += 1
                        progress.progress(state["done"] / len(candidates))
                        status_box.caption(f"Analisando {state['done']} de {len(candidates)} · {name}")

                    from app.crawler.fetcher import Fetcher
                    with st.spinner("Analisando empresas…"):
                        rid = run_pipeline(
                            conn, candidates, WebPageSource(Fetcher(s), s), s,
                            {"mode": "operation_ui", "count": len(candidates), "service": service}, callback,
                        )
                    st.session_state["last_run_id"] = rid
                    st.session_state["last_run_count"] = len(candidates)
                    st.session_state["last_run_errors"] = state["errors"]
                    progress.progress(1.0)
                    status_box.empty()
                    ok = len(candidates) - state["errors"]
                    st.success(f"Análise concluída: {ok} empresa(s) processadas. Vá para **Oportunidades** para revisar.")
                    st.balloons()
        except Exception as exc:
            st.error(f"Não foi possível ler a planilha: {exc}")
    else:
        st.divider()
        st.subheader("Quer testar só uma empresa?")
        c1, c2 = st.columns([2, 1])
        with c1:
            single_url = st.text_input("Site da empresa", placeholder="https://empresa.com.br")
        with c2:
            single_name = st.text_input("Nome", placeholder="Empresa")
        if st.button("Analisar uma empresa", disabled=not single_url):
            try:
                from app.crawler.fetcher import Fetcher
                dom = norm_domain(single_url)
                rid = start_run(conn, {"mode": "operation_single", "url": single_url})
                oid, _ = upsert_org(conn, Candidate(name=single_name or dom, domain=dom, source="ui_operation"))
                with st.spinner("Analisando o site…"):
                    result = analyze_org(conn, oid, rid, WebPageSource(Fetcher(s), s), s, None, {})
                if result["status"] == "ranked":
                    st.success("Empresa analisada. Abra Oportunidades para revisar o resultado.")
                else:
                    st.warning(f"A análise terminou como {result['status']}: {result.get('reason') or 'sem detalhes'}")
            except Exception as exc:
                st.error(f"Não foi possível analisar o site: {exc}")

# ---------------------------------------------------------------------------
# Oportunidades
# ---------------------------------------------------------------------------
elif page == "Oportunidades":
    st.markdown('<div class="hero"><h1>Oportunidades</h1><p>Comece pelas empresas no topo. Elas são as que o motor considera mais compatíveis com o perfil configurado.</p></div>', unsafe_allow_html=True)
    if not rows:
        st.info("Ainda não há oportunidades ranqueadas. Faça uma nova prospecção primeiro.")
    else:
        f1, f2 = st.columns([1, 2])
        with f1:
            min_fit = st.slider("Fit mínimo", 0, 100, 0)
        with f2:
            confidence_filter = st.multiselect("Confiança", ["Alta", "Média", "Baixa"], default=["Alta", "Média", "Baixa"])
        filtered = [
            r for r in rows
            if r["final"] >= min_fit
            and confidence_label(r["evidence_multiplier"], len(r["explanation"].get("facts", []))) in confidence_filter
        ]
        st.caption(f"Mostrando {len(filtered)} de {len(rows)} oportunidades.")
        st.dataframe(result_dataframe(filtered), hide_index=True, use_container_width=True, height=min(650, 70 + len(filtered) * 43))
        x, y = st.columns(2)
        with x:
            st.download_button("⬇️ Baixar Excel", export_xlsx(filtered), "asimov_oportunidades.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, type="primary")
        with y:
            st.download_button("⬇️ Baixar CSV", export_csv(filtered), "asimov_oportunidades.csv", "text/csv", use_container_width=True)

        st.divider()
        st.subheader("Acesse uma oportunidade")
        pick = st.selectbox("Empresa", filtered, format_func=lambda r: f"#{r['rank']} · {r['name']} · Fit {r['final']:.0f}") if filtered else None
        if pick:
            st.session_state["selected_org_id"] = pick["org_id"]
            st.info("Abra **Detalhe** no menu lateral para ver evidências e registrar a avaliação.")

# ---------------------------------------------------------------------------
# Detalhe
# ---------------------------------------------------------------------------
else:
    st.markdown('<div class="hero"><h1>Detalhe da oportunidade</h1><p>Veja por que a empresa apareceu e registre o julgamento da equipe.</p></div>', unsafe_allow_html=True)
    if not rows:
        st.info("Faça uma prospecção para ter empresas aqui.")
    else:
        selected = st.session_state.get("selected_org_id")
        default_idx = next((i for i, r in enumerate(rows) if r["org_id"] == selected), 0)
        pick = st.selectbox("Empresa", rows, index=default_idx, format_func=lambda r: f"#{r['rank']} · {r['name']} · Fit {r['final']:.0f}")
        st.session_state["selected_org_id"] = pick["org_id"]
        ex = pick["explanation"]
        confidence = confidence_label(pick["evidence_multiplier"], len(ex.get("facts", [])))

        a, b, c = st.columns(3)
        a.metric("Fit", f"{pick['final']:.0f}/100")
        b.metric("Confiança", f"{confidence_icon(confidence)} {confidence}")
        c.metric("Melhor oportunidade", ex.get("best_service") or "—")

        st.markdown(f'<div class="card"><div class="card-title">{pick["name"]}</div><div class="muted">{pick["domain"]}</div></div>', unsafe_allow_html=True)
        left, right = st.columns(2)
        with left:
            st.subheader("💡 Hipótese comercial")
            st.write(ex.get("hypothesis") or "Não há evidência suficiente para uma hipótese forte.")
            st.subheader("🔎 O que foi observado")
            for fact in ex.get("facts", []):
                st.write("• " + fact)
        with right:
            st.subheader("🧠 Interpretação")
            for item in ex.get("inferences", []):
                st.write("• " + item)
            if ex.get("absences"):
                st.warning("Itens para confirmar: " + " | ".join(ex["absences"]))
            for caution in ex.get("cautions", []):
                st.info(caution)

        st.subheader("📚 Evidências")
        ev = pd.DataFrame([
            dict(r) for r in conn.execute(
                "SELECT signal_code,claim,source_text,source_url,confidence FROM evidence WHERE analysis_id=? AND verified=1 ORDER BY confidence DESC",
                (pick["analysis_id"],),
            )
        ])
        if ev.empty:
            st.info("Nenhuma evidência verificável suficiente foi registrada.")
        else:
            st.dataframe(ev, hide_index=True, use_container_width=True)

        st.divider()
        st.subheader("👤 Avaliação da equipe")
        st.caption("Seu parecer não altera o ranking passado. Ele será usado para calibrar o sistema nas próximas versões.")
        q = st.radio("Qualidade da oportunidade", ["excelente", "bom", "mediano", "ruim", "sem_fit"], horizontal=True)
        status = st.selectbox("Situação", ["novo", "contatar", "ja_conhecemos", "ja_e_cliente", "descartar"])
        reason = st.text_input("Comentário", placeholder="Por que você considera essa empresa uma boa ou má oportunidade?")
        author = st.text_input("Seu nome", placeholder="Opcional")
        if st.button("Salvar avaliação", type="primary"):
            conn.execute(
                "INSERT INTO human_feedback(org_id,analysis_id,quality,status,reason,author,created_at) VALUES(?,?,?,?,?,?,?)",
                (pick["org_id"], pick["analysis_id"], q, status, reason, author, now()),
            )
            conn.commit()
            st.success("Avaliação registrada. Obrigado — esse feedback melhora a próxima calibração.")
