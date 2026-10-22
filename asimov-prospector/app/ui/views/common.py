"""Componentes compartilhados entre as telas: progresso de rodada, aviso de rodada ocupada e andamento do aprendizado."""
from __future__ import annotations
import streamlit as st
from app.database.run_lock import RunInProgress
from app.feedback.store import LEVEL_LABELS
from app.scoring.explain import SERVICE_NAMES
from app.ui import data

LEVEL_ICONS = {"boa": "👍", "neutra": "😐", "ruim": "👎"}
NOT_ANALYZED = {"error", "blocked", "inconclusive", "excluded"}


def service_name(service_id: str | None) -> str:
    return SERVICE_NAMES.get(service_id, service_id or "—")


def level_text(level: str | None) -> str:
    return f"{LEVEL_ICONS[level]} {LEVEL_LABELS[level]}" if level in LEVEL_LABELS else "—"


class RunProgress:
    """Callback de progresso para `run_pipeline`: barra, empresa atual e contagem de itens sem análise completa."""

    def __init__(self, total: int):
        self.total, self.done, self.problems, self.skipped = max(1, total), 0, 0, 0
        self.bar, self.box = st.progress(0.0), st.empty()

    def __call__(self, name: str, result: dict | None) -> None:
        status = (result or {}).get("status")
        self.done += 1
        self.problems += status in NOT_ANALYZED
        self.skipped += status == "duplicate"
        self.bar.progress(min(1.0, self.done / self.total))
        self.box.caption(f"Analisando {self.done} de {self.total} · {name}")

    def finish(self) -> None:
        self.bar.progress(1.0)
        self.box.empty()


def explain_busy(exc: RunInProgress) -> None:
    """Outra rodada está ativa (nesta ou em outra aba): avisa e oferece liberar a trava só se for seguro."""
    st.warning(f"{exc} Aguarde terminar e tente novamente.")
    with st.expander("A análise anterior foi interrompida?"):
        st.caption("A trava libera sozinha alguns minutos após a última atividade. Só libere agora se tiver certeza de que nenhuma análise está rodando.")
        if st.button("Liberar trava"):
            data.release_lock()
            st.rerun()


def learning_panel(compact: bool = False) -> dict:
    """Andamento do aprendizado: avaliações coletadas x necessárias para o ajuste automático do ranking."""
    info = data.learning()
    progress = min(1.0, info["total"] / info["min_labels"])
    counts = info["counts"]
    st.progress(progress, text=f"Avaliações: {info['total']} de {info['min_labels']} para ativar o aprendizado")
    if compact:
        return info
    c1, c2, c3 = st.columns(3)
    c1.metric(level_text("boa"), counts["boa"])
    c2.metric(level_text("neutra"), counts["neutra"])
    c3.metric(level_text("ruim"), counts["ruim"])
    if info["active_version"]:
        st.success(f"Aprendizado ativo (versão {info['active_version']}).")
    elif info["total"] >= info["min_labels"]:
        st.info(f"Faltam avaliações de uma classe: são necessárias ao menos {info['min_per_class']} 'boa' e {info['min_per_class']} 'ruim'.")
    else:
        st.caption("Avalie os leads do ranking. Com avaliações suficientes, o sistema passa a ajustar o ranking sozinho.")
    st.caption(f"Geração de novos leads com os parâmetros aprendidos: a partir de {info['lead_generation_min_labels']} avaliações.")
    return info
