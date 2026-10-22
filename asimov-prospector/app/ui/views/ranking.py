"""Tela 'Ranking': lista ordenada para o time comercial, andamento do aprendizado e exportação."""
from __future__ import annotations
import io
import pandas as pd
import streamlit as st
from app.database.run_lock import RunInProgress
from app.ui import data, theme
from app.ui.views.common import RunProgress, explain_busy, learning_panel, level_text, service_name


def table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "#": r["rank"], "Empresa": r["name"], "Pontuação": round(r["score"], 1), "Oportunidade": service_name(r["best_service"]),
        "Hipótese": r["explanation"].get("hypothesis") or "—", "Avaliação": level_text(r["feedback"]), "Site": r["domain"],
    } for r in rows])


def _xlsx(df: pd.DataFrame) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Ranking")
    return bio.getvalue()


def _open_review(org_id: int) -> None:
    """Callback de botão: troca de tela antes do rerun (permitido em callbacks)."""
    st.session_state["selected_org_id"] = org_id
    st.session_state["page"] = "Avaliar"


def render(service: str) -> None:
    theme.hero("Ranking", "Comece pelo topo, abra cada empresa e diga se ela é uma boa oportunidade. É assim que o sistema aprende.")
    info = learning_panel()
    if info["needs_reapply"]:
        _reapply_banner()
    rows = data.ranking_rows(None if service == "Geral" else service)
    if not rows:
        st.info("Ainda não há empresas ranqueadas. Faça uma análise primeiro.")
        return

    only_pending = st.checkbox("Mostrar só as que ainda não foram avaliadas")
    shown = [r for r in rows if not (only_pending and r["feedback"])]
    st.caption(f"{len(shown)} de {len(rows)} empresas · {sum(bool(r['feedback']) for r in rows)} já avaliadas")
    df = table(shown)
    event = st.dataframe(df, hide_index=True, use_container_width=True, height=min(650, 70 + len(df) * 36),
                         on_select="rerun", selection_mode="single-row", key="ranking_table",
                         column_config={"#": st.column_config.NumberColumn(width="small"), "Oportunidade": st.column_config.TextColumn(width="medium"),
                                        "Hipótese": st.column_config.TextColumn(width="large")})
    picked = event.selection.rows
    if picked:
        row = shown[picked[0]]
        st.button(f"Avaliar {row['name']} →", type="primary", on_click=_open_review, args=(row["org_id"],))
    else:
        st.caption("Selecione uma linha para avaliar a empresa.")

    x, y = st.columns(2)
    x.download_button("⬇️ Baixar Excel", _xlsx(df), "asimov_ranking.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    y.download_button("⬇️ Baixar CSV", df.to_csv(index=False).encode("utf-8-sig"), "asimov_ranking.csv", "text/csv", use_container_width=True)


def _reapply_banner() -> None:
    st.info("Há um aprendizado novo ainda não aplicado ao ranking. A reaplicação usa as páginas já coletadas (não acessa os sites).")
    if not st.button("Aplicar aprendizado ao ranking", type="primary"):
        return
    progress = RunProgress(len(data.ranking_rows()))
    try:
        with st.spinner("Reprocessando o ranking…"):
            data.reapply(progress)
    except RunInProgress as exc:
        explain_busy(exc)
        return
    progress.finish()
    st.rerun()
