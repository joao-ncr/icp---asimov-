"""Fontes de candidatos (todas opcionais):
 1. CSV manual de seeds (name,domain,...)    -> sempre disponivel
 2. CSV de dados abertos de CNPJ (Receita)   -> universo enumeravel (filtro CNAE/UF/municipio)
 3. SearXNG self-hosted                      -> resolve dominio e executa queries por problema"""
from __future__ import annotations
import csv, re
from pathlib import Path
import httpx
from app.core.settings import Settings
from app.core.utils import norm_domain
from app.models.schemas import Candidate

SKIP_DOMAINS = ("facebook.com", "instagram.com", "linkedin.com", "youtube.com", "wikipedia.org", "mercadolivre.com", "olx.com",
                "telelistas", "guiamais", "apontador", "cnpj.", "econodata", "casadosdados", "google.", "twitter.com", "x.com")


def from_seed_csv(path: Path) -> list[Candidate]:
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("name") or "").strip():
                out.append(Candidate(name=r["name"].strip(), domain=norm_domain(r.get("domain")), municipio=r.get("municipio") or None,
                                     uf=r.get("uf") or None, segment=r.get("segment") or None, source="seed_csv"))
    return out


def from_cnpj_csv(path: Path, cnae_prefixes: list[str], uf: str | None, municipios: list[str] | None, limit: int = 500) -> list[Candidate]:
    """Espera CSV ja tratado com colunas: cnpj,razao_social,nome_fantasia,cnae,uf,municipio,porte,situacao.
    (Nao armazena socios nem contatos de pessoas fisicas - minimizacao LGPD.)"""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("situacao") or "ATIVA").upper() not in ("ATIVA", "02"):
                continue
            if cnae_prefixes and not any((r.get("cnae") or "").startswith(p) for p in cnae_prefixes):
                continue
            if uf and (r.get("uf") or "").upper() != uf.upper():
                continue
            if municipios and (r.get("municipio") or "").lower() not in [m.lower() for m in municipios]:
                continue
            out.append(Candidate(name=(r.get("nome_fantasia") or r.get("razao_social") or "").strip(), cnpj=re.sub(r"\D", "", r.get("cnpj") or "") or None,
                                 cnae=r.get("cnae"), uf=r.get("uf"), municipio=r.get("municipio"), porte=r.get("porte"), source="cnpj_open_data"))
            if len(out) >= limit:
                break
    return out


def searx(s: Settings, query: str, n: int = 10) -> list[dict]:
    if not s.searxng_url:
        return []
    try:
        r = httpx.get(s.searxng_url.rstrip("/") + "/search", params={"q": query, "format": "json", "language": "pt-BR"}, timeout=20,
                      headers={"User-Agent": s.user_agent})
        return r.json().get("results", [])[:n]
    except Exception:
        return []


def resolve_domain(s: Settings, name: str, municipio: str | None) -> str | None:
    for res in searx(s, f'"{name}" {municipio or ""} site oficial', 5):
        d = norm_domain(res.get("url"))
        if d and not any(k in d for k in SKIP_DOMAINS):
            return d
    return None


def discover_by_query(s: Settings, q: dict, n: int = 10) -> list[Candidate]:
    out = []
    for res in searx(s, q["query"], n):
        d = norm_domain(res.get("url"))
        if d and not any(k in d for k in SKIP_DOMAINS):
            out.append(Candidate(name=(res.get("title") or d)[:80], domain=d, source=f"searx:{q['icp_id']}"))
    return out
