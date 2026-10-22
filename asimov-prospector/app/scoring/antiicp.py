"""Anti-ICP configuravel + cruzamento com leads conhecidos (leads.xlsx)."""
from __future__ import annotations
import re
from app.core.utils import norm_domain, norm_name, norm_text, similarity
from app.scoring.score import cfg


KNOWN_MATCH_MIN = 0.85          # similaridade minima de nome para considerar o mesmo lead do CRM
CONTAINED_NAME_RATIO = 0.9      # um nome contido no outro (>= 5 caracteres) vale como 0.9
MIN_CONTAINED_LEN = 5


class KnownLeadIndex:
    """Leads do CRM carregados uma vez por rodada; casamento por dominio (exato) e por nome (aproximado)."""

    def __init__(self, rows):
        self._rows = [r for r in rows if not r["is_person"]]
        self._by_domain: dict[str, object] = {}
        for r in self._rows:
            d = norm_domain(r["domain"])
            if d:
                self._by_domain.setdefault(d, r)

    @classmethod
    def from_db(cls, conn) -> "KnownLeadIndex":
        return cls(conn.execute("SELECT * FROM known_lead").fetchall())

    def match(self, name: str, domain: str | None) -> dict | None:
        d = norm_domain(domain)
        if d and d in self._by_domain:
            return _known(self._by_domain[d], 1.0)
        nn = norm_name(name)
        best, best_r = None, 0.0
        for r in self._rows:
            other = r["name_norm"] or ""
            contained = bool(other) and (other in nn or nn in other) and min(len(nn), len(other)) >= MIN_CONTAINED_LEN
            ratio = similarity(nn, other, max(best_r, KNOWN_MATCH_MIN))
            if contained:
                ratio = max(ratio, CONTAINED_NAME_RATIO)
            if ratio > best_r:
                best, best_r = r, ratio
        return _known(best, best_r) if best is not None and best_r >= KNOWN_MATCH_MIN else None


def match_known_lead(conn, name: str, domain: str | None, index: KnownLeadIndex | None = None) -> dict | None:
    return (index or KnownLeadIndex.from_db(conn)).match(name, domain)


def _known(r, ratio) -> dict:
    return {"outcome": r["outcome"], "category": r["loss_category"], "reason": r["loss_reason"], "funnel": r["funnel"],
            "value": r["value"], "match": round(ratio, 2), "name": r["name"]}


def precheck(known: dict | None) -> tuple[bool, str | None]:
    """Retorna (excluir?, motivo) antes de gastar crawl."""
    a = cfg()["anti_icp"]
    if known:
        if known["outcome"] == "won" and a["exclude_known_clients"]:
            return True, "ja e cliente"
        if known["outcome"] == "lost" and known["category"] in a["exclude_known_loss_categories"]:
            return True, f"lead anterior perdido: {known['category']}"
    return False, None


def is_competitor(text: str) -> bool:
    a = cfg()["anti_icp"]
    t = norm_text(text)
    n = sum(1 for p in a["competitor_terms"] if re.search(p, t))
    return n >= a["competitor_min_matches"]


def reactivation_flag(known: dict | None) -> bool:
    return bool(known and known["outcome"] == "lost" and known["category"] in ("no_response", "not_priority"))
