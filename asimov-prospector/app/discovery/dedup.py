from __future__ import annotations
from difflib import SequenceMatcher
from app.core.utils import norm_domain, norm_name
from app.database.db import now
from app.models.schemas import Candidate


def find_existing(conn, c: Candidate):
    d = norm_domain(c.domain)
    if d:
        r = conn.execute("SELECT * FROM organization WHERE domain=?", (d,)).fetchone()
        if r: return r
    if c.cnpj:
        r = conn.execute("SELECT * FROM organization WHERE cnpj=?", (c.cnpj,)).fetchone()
        if r: return r
    nn = norm_name(c.name)
    for r in conn.execute("SELECT * FROM organization"):
        if r["name_norm"] == nn or (len(nn) > 6 and SequenceMatcher(None, nn, r["name_norm"]).ratio() > 0.93):
            return r
    return None


def upsert_org(conn, c: Candidate) -> tuple[int, bool]:
    ex = find_existing(conn, c)
    if ex:
        if c.domain and not ex["domain"]:
            conn.execute("UPDATE organization SET domain=? WHERE id=?", (norm_domain(c.domain), ex["id"]))
        return ex["id"], False
    cur = conn.execute("INSERT INTO organization(name,name_norm,domain,cnpj,municipio,uf,porte,cnae,segment,source,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (c.name, norm_name(c.name), norm_domain(c.domain), c.cnpj, c.municipio, c.uf, c.porte, c.cnae, c.segment, c.source, now()))
    conn.commit()
    return cur.lastrowid, True
