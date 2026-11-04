"""Decisao humana sobre candidatos gerados (app/discovery/generation.py): aprovar cria organizacao e devolve o
Candidate para a UI disparar a analise; rejeitar so registra a decisao. Nenhum candidato vira organizacao nem
entra na fila de analise sem essa decisao explicita."""
from __future__ import annotations
import sqlite3
from app.database.db import now
from app.discovery.dedup import OrgIndex, upsert_org
from app.models.schemas import Candidate

PENDING_FIELDS = "id,name,cnpj,cnae,uf,municipio,segment,icp_id,rationale,created_at"


def pending_candidates(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(f"SELECT {PENDING_FIELDS} FROM discovery_candidate WHERE status='pending' ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def _candidate_of(row: sqlite3.Row) -> Candidate:
    return Candidate(name=row["name"], cnpj=row["cnpj"], cnae=row["cnae"], uf=row["uf"], municipio=row["municipio"],
                     porte=row["porte"], segment=row["segment"], source="discovery_cnpj")


def decide(conn: sqlite3.Connection, candidate_ids: list[int], approve: bool, decided_by: str) -> list[Candidate]:
    """Marca approved/rejected para os ids pendentes informados. Aprovados ganham organizacao (dedup contra o que ja
    existe) e sao devolvidos para a UI disparar a analise; rejeitados nao criam organizacao nem entram na fila."""
    if not candidate_ids:
        return []
    placeholders = ",".join("?" * len(candidate_ids))
    rows = conn.execute(f"SELECT * FROM discovery_candidate WHERE id IN ({placeholders}) AND status='pending'",
                        candidate_ids).fetchall()
    approved: list[Candidate] = []
    org_index = OrgIndex.from_db(conn) if approve else None
    status, stamp = ("approved" if approve else "rejected"), now()
    for row in rows:
        org_id = None
        if approve:
            candidate = _candidate_of(row)
            org_id, _ = upsert_org(conn, candidate, org_index)
            approved.append(candidate)
        conn.execute("UPDATE discovery_candidate SET status=?, org_id=?, decided_by=?, decided_at=? WHERE id=?",
                     (status, org_id, decided_by, stamp, row["id"]))
    conn.commit()
    return approved
