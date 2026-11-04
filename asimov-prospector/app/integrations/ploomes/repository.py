"""Leituras do estado da integracao no banco local: ultima sincronizacao, resumo e empresas pendentes de analise."""
from __future__ import annotations
import json
from app.models.schemas import Candidate

_LINKED = "EXISTS (SELECT 1 FROM ploomes_company pc WHERE pc.org_id=o.id)"
_ANALYZED = "EXISTS (SELECT 1 FROM analysis a WHERE a.org_id=o.id)"


def last_successful_sync(conn) -> dict | None:
    row = conn.execute("SELECT * FROM ploomes_sync WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
    return _with_report(row)


def last_sync(conn) -> dict | None:
    return _with_report(conn.execute("SELECT * FROM ploomes_sync ORDER BY id DESC LIMIT 1").fetchone())


def _with_report(row) -> dict | None:
    if not row:
        return None
    data = dict(row)
    data["report"] = json.loads(data["report"] or "{}")
    return data


def summary(conn) -> dict:
    """Contagens das empresas vindas do Ploomes para a tela de analise."""
    row = conn.execute(f"""SELECT COUNT(*) total,
              SUM(o.domain IS NOT NULL) with_site,
              SUM({_ANALYZED}) analyzed,
              SUM(EXISTS (SELECT 1 FROM analysis a WHERE a.org_id=o.id AND a.status='ranked')) ranked,
              SUM(NOT {_ANALYZED} AND o.domain IS NOT NULL) pending_with_site,
              SUM(NOT {_ANALYZED} AND o.domain IS NULL) pending_without_site
            FROM organization o WHERE {_LINKED}""").fetchone()
    counts = {k: int(row[k] or 0) for k in row.keys()}
    counts["without_site"] = counts["total"] - counts["with_site"]
    return counts


def pending_candidates(conn, limit: int) -> list[Candidate]:
    """Empresas do Ploomes ainda nunca analisadas: primeiro as com site, depois as atualizadas mais recentemente no CRM."""
    rows = conn.execute(f"""SELECT o.name, o.domain, o.cnpj, o.municipio, o.uf, o.segment FROM organization o
            WHERE {_LINKED} AND NOT {_ANALYZED}
            ORDER BY (o.domain IS NULL), (SELECT MAX(pc.last_update) FROM ploomes_company pc WHERE pc.org_id=o.id) DESC, o.id
            LIMIT ?""", (limit,)).fetchall()
    return [Candidate(name=r["name"], domain=r["domain"], cnpj=r["cnpj"], municipio=r["municipio"], uf=r["uf"],
                      segment=r["segment"], source="ploomes") for r in rows]
