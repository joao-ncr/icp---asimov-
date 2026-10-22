"""Persistencia do feedback do time comercial e do ciclo de calibracao (fit -> snapshot auditavel -> uso no scoring)."""
from __future__ import annotations
from app.core.utils import jdump
from app.database.db import now
from app.intelligence.signals import taxonomy
from app.scoring.calibration import LEVELS, NEUTRAL, Calibration, LabeledLead, fit_calibration, is_ready, label_counts
from app.scoring.score import cfg

LEVEL_LABELS = {"boa": "Boa oportunidade", "neutra": "Neutra", "ruim": "Ruim"}


def record_feedback(conn, org_id: int, analysis_id: int, level: str, reason: str = "", author: str = "") -> int:
    if level not in LEVELS:
        raise ValueError(f"Nível de satisfação inválido: {level!r} (use {', '.join(LEVELS)})")
    cur = conn.execute("INSERT INTO human_feedback(org_id,analysis_id,quality,status,reason,author,created_at) VALUES(?,?,?,?,?,?,?)",
                       (org_id, analysis_id, level, "novo", reason.strip(), author.strip(), now()))
    conn.commit()
    return cur.lastrowid


def latest_feedback(conn, org_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM human_feedback WHERE org_id=? ORDER BY id DESC LIMIT 1", (org_id,)).fetchone()
    return dict(row) if row else None


def labeled_leads(conn) -> tuple[list[LabeledLead], int]:
    """Uma amostra por empresa (avaliacao mais recente), com os sinais verificados da analise que o avaliador viu.
    Devolve tambem o maior id de feedback considerado (chave de idempotencia do snapshot)."""
    need = {code for code, s in taxonomy().items() if s["kind"] == "need"}
    rows = conn.execute(f"""SELECT f.id fid, f.quality, o.segment,
              (SELECT GROUP_CONCAT(DISTINCT e.signal_code) FROM evidence e WHERE e.analysis_id=f.analysis_id AND e.verified=1) codes
            FROM human_feedback f JOIN organization o ON o.id=f.org_id
            WHERE f.id=(SELECT MAX(id) FROM human_feedback WHERE org_id=f.org_id)
              AND f.analysis_id IS NOT NULL AND f.quality IN ({",".join("?" * len(LEVELS))})""", tuple(LEVELS)).fetchall()
    samples = [LabeledLead(LEVELS[r["quality"]], frozenset(set((r["codes"] or "").split(",")) & need), r["segment"] or "default")
               for r in rows]
    return samples, max((r["fid"] for r in rows), default=0)


def refresh_calibration(conn) -> Calibration:
    """Gera um novo snapshot quando ha feedback novo desde o ultimo; senao reaproveita. Retorna a calibracao vigente."""
    samples, last_id = labeled_leads(conn)
    row = conn.execute("SELECT * FROM calibration ORDER BY id DESC LIMIT 1").fetchone()
    if row and row["last_feedback_id"] == last_id and row["n_labels"] == len(samples):
        return Calibration.from_row(row)
    if not row and not samples:
        return NEUTRAL
    fitted = fit_calibration(samples)
    cur = conn.execute("INSERT INTO calibration(created_at,n_labels,last_feedback_id,active,params) VALUES(?,?,?,?,?)",
                       (now(), len(samples), last_id, int(fitted.active), jdump(fitted.to_params())))
    conn.commit()
    return Calibration(cur.lastrowid, fitted.active, fitted.n_labels, fitted.counts, fitted.signal_mult, fitted.segment_mult)


def applied_version(conn) -> int:
    """Versao de calibracao usada na analise mais recente (0 = nenhuma)."""
    row = conn.execute("SELECT json_extract(result,'$.calibration_version') v FROM analysis WHERE status='ranked' ORDER BY id DESC LIMIT 1").fetchone()
    return int(row["v"] or 0) if row else 0


def learning_status(conn) -> dict:
    """Resumo para a interface: quantas avaliacoes, quanto falta e se o aprendizado ja esta ativo."""
    c = cfg()["calibration"]
    current = refresh_calibration(conn)
    samples, _ = labeled_leads(conn)
    counts = label_counts(samples)
    applied = applied_version(conn)
    return {"total": len(samples), "counts": counts, "min_labels": c["min_labels"], "min_per_class": c["min_per_class"],
            "ready": is_ready(counts, c), "active_version": current.version if current.active else 0, "applied_version": applied,
            "lead_generation_min_labels": c["lead_generation_min_labels"],
            "needs_reapply": current.active and current.version != applied}
