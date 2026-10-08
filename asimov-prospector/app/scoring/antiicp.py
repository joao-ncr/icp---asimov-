"""Anti-ICP configuravel + cruzamento com leads conhecidos (leads.xlsx)."""
from __future__ import annotations
import re
from difflib import SequenceMatcher
from app.core.utils import norm_domain, norm_name, norm_text
from app.scoring.score import cfg


def match_known_lead(conn, name: str, domain: str | None) -> dict | None:
    nn = norm_name(name)
    best, best_r = None, 0.0
    for r in conn.execute("SELECT * FROM known_lead WHERE is_person=0"):
        if domain and r["domain"] and norm_domain(r["domain"]) == norm_domain(domain):
            return _known(r, 1.0)
        ratio = SequenceMatcher(None, nn, r["name_norm"]).ratio()
        if r["name_norm"] and (r["name_norm"] in nn or nn in r["name_norm"]) and min(len(nn), len(r["name_norm"])) >= 5:
            ratio = max(ratio, 0.9)
        if ratio > best_r:
            best, best_r = r, ratio
    return _known(best, best_r) if best is not None and best_r >= 0.85 else None


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
