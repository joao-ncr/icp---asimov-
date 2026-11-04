"""Tela 'Avaliar': evidências de uma empresa e a avaliação do time em 3 níveis (a base do aprendizado)."""
from __future__ import annotations
import streamlit as st
from app.core.auth import LOCAL_USER, User
from app.feedback.store import LEVEL_LABELS
from app.ui import data, theme
from app.ui.views.common import LEVEL_ICONS, level_text, service_name


def _next_pending(rows: list[dict], current_org_id: int) -> int | None:
    """Próxima empresa sem avaliação, seguindo a ordem do ranking a partir da atual (e dando a volta)."""
    ids = [r["org_id"] for r in rows]
    start = ids.index(current_org_id) + 1 if current_org_id in ids else 0
    for r in rows[start:] + rows[:start]:
        if not r["feedback"] and r["org_id"] != current_org_id:
            return r["org_id"]
    return None


def render(service: str, user: User) -> None:
    theme.hero("Avaliar oportunidade", "Veja por que a empresa apareceu e diga se ela é uma boa oportunidade. Sua avaliação calibra o ranking.")
    rows = data.ranking_rows(None if service == "Geral" else service)
    if not rows:
        st.info("Faça uma análise para ter empresas aqui.")
        return
    selected = st.session_state.get("selected_org_id")
    default_idx = next((i for i, r in enumerate(rows) if r["org_id"] == selected), 0)
    pick = st.selectbox("Empresa", rows, index=default_idx,
                        format_func=lambda r: f"#{r['rank']} · {r['name']} · {r['score']:.0f} {'✔' if r['feedback'] else ''}")
    st.session_state["selected_org_id"] = pick["org_id"]

    _summary(pick)
    _evidence(pick)
    _evaluation_form(pick, rows, user)


def _summary(pick: dict) -> None:
    ex = pick["explanation"]
    a, b = st.columns(2)
    a.metric("Pontuação", f"{pick['score']:.0f}/100")
    b.metric("Melhor oportunidade", service_name(ex.get("best_service")))
    theme.company_card(pick["name"], pick["domain"])
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
    _history(data.history_for(pick["org_id"]))


def _history(history: dict | None) -> None:
    """Contexto comercial (Ploomes ou base histórica): só aparece o que existe."""
    if not history:
        return
    items = [("Oferta sugerida no CRM", history["best_offer"]), ("Situação no CRM", history["commercial_status"]),
             ("Score legado (referência)", f"{history['legacy_score']:.0f}" if history["legacy_score"] is not None else None)]
    present = [(label, value) for label, value in items if value]
    if present:
        for column, (label, value) in zip(st.columns(len(present)), present):
            column.metric(label, value)
    if history["registration_alert"]:
        st.warning(history["registration_alert"])


def _evidence(pick: dict) -> None:
    st.subheader("📚 Evidências")
    evidence = data.evidence_for(pick["analysis_id"])
    if evidence.empty:
        st.info("Nenhuma evidência verificável suficiente foi registrada.")
    else:
        st.dataframe(evidence, hide_index=True, width="stretch")


def _evaluation_form(pick: dict, rows: list[dict], user: User) -> None:
    st.divider()
    st.subheader("👤 Sua avaliação")
    previous = data.evaluation_for(pick["org_id"])
    if previous:
        st.caption(f"Avaliação anterior: {level_text(previous['quality'])}" + (f" por {previous['author']}" if previous["author"] else "") + ". Você pode atualizá-la.")
    with st.form(f"evaluation_{pick['org_id']}"):
        level = st.radio("Esta empresa é uma boa oportunidade para a Asimov?", list(LEVEL_LABELS), horizontal=True, index=None,
                         format_func=lambda k: f"{LEVEL_ICONS[k]} {LEVEL_LABELS[k]}")
        reason = st.text_input("Comentário (opcional)", placeholder="Por que boa, neutra ou ruim?")
        author = _author_field(user)
        submitted = st.form_submit_button("Salvar e ir para a próxima", type="primary")
    if not submitted:
        return
    if level is None:
        st.warning("Escolha uma das três opções para salvar.")
        return
    data.save_evaluation(pick["org_id"], pick["analysis_id"], level, reason, author)
    st.session_state["author"] = author
    following = _next_pending(rows, pick["org_id"])
    if following:
        st.session_state["selected_org_id"] = following
    st.toast("Avaliação registrada. Obrigado!")
    st.rerun()


def _author_field(user: User) -> str:
    """Com login, o autor é o usuário autenticado (auditável); no modo local, o nome é opcional."""
    if user is not LOCAL_USER:
        st.caption(f"Avaliando como **{user.username}**.")
        return user.username
    return st.text_input("Seu nome (opcional)", value=st.session_state.get("author", ""))
