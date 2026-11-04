"""Ranking de oportunidades: leitura direta do banco (ordenacao e limite em SQL; JSON so das linhas devolvidas)."""
from __future__ import annotations
import json
from app.scoring.score import AXES


FINAL = "FINAL"

_QUERY = """
SELECT o.id org_id, o.name, o.domain, o.segment, a.id analysis_id, a.run_id, a.result, a.created_at,
       (SELECT quality FROM human_feedback WHERE org_id=o.id ORDER BY id DESC LIMIT 1) feedback
FROM analysis a
JOIN organization o ON o.id=a.org_id
JOIN score s ON s.analysis_id=a.id AND s.service_id=?
WHERE a.status='ranked'
  AND a.id=(SELECT MAX(id) FROM analysis WHERE org_id=o.id AND status='ranked')
  {run_filter}
ORDER BY s.value DESC, a.id
{limit}"""


def ranking(conn, run_id: int | None = None, service: str | None = None, limit: int | None = None) -> list[dict]:
    """Ultima analise 'ranked' de cada empresa, da maior para a menor pontuacao (geral ou de um servico)."""
    if service is not None and service not in AXES:
        raise ValueError(f"Serviço desconhecido: {service!r}")
    params: list = [service or FINAL]
    if run_id:
        params.append(run_id)
    if limit:
        params.append(limit)
    sql = _QUERY.format(run_filter="AND a.run_id=?" if run_id else "", limit="LIMIT ?" if limit else "")
    rows = []
    for rank, r in enumerate(conn.execute(sql, params), 1):
        res = json.loads(r["result"])
        rows.append({"rank": rank, "org_id": r["org_id"], "analysis_id": r["analysis_id"], "name": r["name"], "domain": r["domain"],
                     "segment": r["segment"], "score": res["service_scores"][service] if service else res["final"], "final": res["final"],
                     "b1": res["baseline_b1"], "best_service": res["best_service"], "service_scores": res["service_scores"],
                     "evidence_multiplier": res["evidence_multiplier"], "reactivation": res.get("reactivation_candidate", False),
                     "explanation": res["explanation"], "feedback": r["feedback"]})
    return rows


def data_version(conn) -> tuple[int, int, int]:
    """Muda sempre que o ranking pode mudar (nova analise, novo feedback ou nova calibracao): chave de cache da interface."""
    return tuple(conn.execute("""SELECT (SELECT COALESCE(MAX(id),0) FROM analysis), (SELECT COALESCE(MAX(id),0) FROM human_feedback),
                                        (SELECT COALESCE(MAX(id),0) FROM calibration)""").fetchone())
