"""Deduplicacao de organizacoes. O indice em memoria evita reler e varrer a tabela inteira a cada candidato."""
from __future__ import annotations
from app.core.utils import identity_domain, norm_name, similarity
from app.database.db import now
from app.models.schemas import Candidate

NAME_SIMILARITY = 0.93      # acima disso (e nome com mais de 6 caracteres) duas empresas sao tratadas como a mesma (MVP)
MIN_FUZZY_LEN = 6


class OrgIndex:
    """Busca por dominio proprio -> CNPJ -> nome (exato, depois aproximado), na ordem de cadastro."""

    def __init__(self, rows):
        self._by_domain: dict[str, int] = {}
        self._by_cnpj: dict[str, int] = {}
        self._names: list[tuple[int, str]] = []
        for r in rows:
            self.add(r["id"], r["domain"], r["cnpj"], r["name_norm"])

    @classmethod
    def from_db(cls, conn) -> "OrgIndex":
        return cls(conn.execute("SELECT id, domain, cnpj, name_norm FROM organization ORDER BY id"))

    def add(self, org_id: int, domain: str | None, cnpj: str | None, name_norm: str | None) -> None:
        if domain:
            self._by_domain.setdefault(domain, org_id)
        if cnpj:
            self._by_cnpj.setdefault(cnpj, org_id)
        if name_norm is not None:
            self._names.append((org_id, name_norm))

    def find(self, c: Candidate) -> int | None:
        domain = identity_domain(c.domain)
        if domain and domain in self._by_domain:
            return self._by_domain[domain]
        if c.cnpj and c.cnpj in self._by_cnpj:
            return self._by_cnpj[c.cnpj]
        nn = norm_name(c.name)
        for org_id, other in self._names:
            if other == nn or (len(nn) > MIN_FUZZY_LEN and similarity(nn, other, NAME_SIMILARITY) > NAME_SIMILARITY):
                return org_id
        return None


def find_existing(conn, c: Candidate):
    org_id = OrgIndex.from_db(conn).find(c)
    return conn.execute("SELECT * FROM organization WHERE id=?", (org_id,)).fetchone() if org_id else None


def upsert_org(conn, c: Candidate, index: OrgIndex | None = None) -> tuple[int, bool]:
    """Devolve (org_id, criada?). Passe um `index` reutilizado em lotes para evitar varreduras repetidas."""
    index = index or OrgIndex.from_db(conn)
    domain = identity_domain(c.domain)
    existing = index.find(c)
    if existing:
        row = conn.execute("SELECT domain FROM organization WHERE id=?", (existing,)).fetchone()
        if domain and not row["domain"]:
            conn.execute("UPDATE organization SET domain=? WHERE id=?", (domain, existing))
            conn.commit()
            index.add(existing, domain, None, None)
        return existing, False
    name_norm = norm_name(c.name)
    cur = conn.execute("INSERT INTO organization(name,name_norm,domain,cnpj,municipio,uf,porte,cnae,segment,source,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (c.name, name_norm, domain, c.cnpj, c.municipio, c.uf, c.porte, c.cnae, c.segment, c.source, now()))
    conn.commit()
    index.add(cur.lastrowid, domain, c.cnpj, name_norm)
    return cur.lastrowid, True
