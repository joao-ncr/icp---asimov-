"""Orquestrador: candidato -> (anti-ICP previo) -> crawl -> texto -> sinais -> score -> ranking.
Etapas gravam no SQLite; metricas ficam em search_run.metrics."""
from __future__ import annotations
import json, time
from typing import Callable, Protocol
from app.core.profile import load_profile
from app.core.settings import Settings
from app.core.utils import jdump, norm_domain
from app.crawler.extract import extract_page, injection_count, rank_links
from app.crawler.fetcher import Fetcher
from app.database.db import now
from app.discovery.dedup import upsert_org
from app.extraction.text import chunk_text, extract_numeric_facts, verify_quote
from app.intelligence.embeddings import Embedder
from app.intelligence.llm import get_backend
from app.intelligence.signals import detect_technical_signals, detect_text_signals, taxonomy
from app.models.schemas import Candidate, Evidence, SignalHit
from app.scoring import antiicp
from app.scoring.explain import build_explanation
from app.scoring.score import cfg as scoring_cfg, compute_scores, config_hash, detect_segment

EXTRACTOR_VERSION = "rules-v1"


class PageSource(Protocol):
    def get_pages(self, domain: str, max_pages: int) -> tuple[list[dict], str | None]: ...


class WebPageSource:
    """Crawler real: home + paginas relevantes do MESMO dominio."""
    def __init__(self, fetcher: Fetcher, s: Settings):
        self.f, self.s = fetcher, s

    def get_pages(self, domain: str, max_pages: int):
        pages, err = [], None
        home = None
        for scheme in ("https", "http"):
            r = self.f.fetch(f"{scheme}://{domain}/")
            if r.ok:
                home = r; break
            err = r.error or f"http_{r.status}"
        if not home:
            return [], err
        pd = extract_page(home.body, home.final_url)
        pages.append({"url": home.final_url, "status_code": home.status, **pd})
        for u in rank_links(pd["links"], max_pages - 1):
            if u.rstrip("/") == home.final_url.rstrip("/"):
                continue
            r = self.f.fetch(u)
            if r.ok:
                pages.append({"url": r.final_url, "status_code": r.status, **extract_page(r.body, r.final_url)})
        return pages, None


class FixtureSource:
    """Paginas locais em tests/fixtures/sites/<dominio>/*.html (demo e testes offline)."""
    def __init__(self, root):
        self.root = root

    def get_pages(self, domain: str, max_pages: int):
        d = self.root / domain
        if not d.exists():
            return [], "dns_failure"
        pages = []
        for p in sorted(d.glob("*.html"), key=lambda p: (p.name != "index.html", p.name))[:max_pages]:
            pages.append({"url": f"https://{domain}/{'' if p.name == 'index.html' else p.name}", "status_code": 200,
                          **extract_page(p.read_text(encoding="utf-8"), f"https://{domain}/")})
        return pages, None


def start_run(conn, config: dict) -> int:
    return conn.execute("INSERT INTO search_run(started_at,config,metrics) VALUES(?,?,?)", (now(), jdump(config), "{}")).lastrowid


def analyze_org(conn, org_id: int, run_id: int, source: PageSource, s: Settings, embedder: Embedder | None = None, metrics: dict | None = None) -> dict:
    m = metrics if metrics is not None else {}
    org = dict(conn.execute("SELECT * FROM organization WHERE id=?", (org_id,)).fetchone())
    backend = get_backend(s)
    t0 = time.time()
    known = antiicp.match_known_lead(conn, org["name"], org["domain"])
    if known:
        conn.execute("UPDATE organization SET known_status=?, known_detail=? WHERE id=?", (known["outcome"], jdump(known), org_id))
    excl, reason = antiicp.precheck(known)
    if excl:
        return _save(conn, org_id, run_id, "excluded", reason, backend, {"known": known}, [], {}, m)

    pages, err = (source.get_pages(org["domain"], s.max_pages_per_domain) if org["domain"] else ([], "no_domain"))
    if err and "dns_failure" in err:
        err = "dns_failure"          # dominio inexistente => 'sem site' (inferencia por ausencia), nao 'bloqueado'
    m["pages"] = m.get("pages", 0) + len(pages)
    unreachable = not pages
    if unreachable and err not in ("dns_failure", "no_domain") and not (err or "").startswith("network"):
        # bloqueado por robots / unsafe / 403: NAO tratar como "sem site"
        status = "blocked" if err else "error"
        return _save(conn, org_id, run_id, status, err, backend, {"known": known}, [], {}, m)

    conn.execute("DELETE FROM page WHERE org_id=?", (org_id,))
    for p in pages:
        conn.execute("INSERT OR REPLACE INTO page(org_id,url,status_code,fetched_at,text,features,injection_flags) VALUES(?,?,?,?,?,?,?)",
                     (org_id, p["url"], p["status_code"], now(), p["text"], jdump(p["features"]), p["injection_flags"]))
    text_all = "\n".join(p["text"] for p in pages)
    inj = sum(p["injection_flags"] for p in pages)

    a = antiicp.cfg()["anti_icp"]
    if pages and len(text_all) < a["min_text_chars"]:
        return _save(conn, org_id, run_id, "inconclusive", "presenca publica insuficiente (pouco texto)", backend, {"known": known}, [], {}, m)
    if pages and antiicp.is_competitor(text_all):
        return _save(conn, org_id, run_id, "excluded", "possivel concorrente (software house/agencia)", backend, {"known": known}, [], {}, m)

    # --- sinais: regras + (opcional) LLM, tudo verificado contra o texto coletado ---
    hits = detect_text_signals(pages)
    page_texts = {p["url"]: p["text"] for p in pages}
    llm_added = llm_rejected = 0
    for p in pages:
        for ch in chunk_text(p["text"], p["url"]):
            for sig in backend.extract(ch).signals:
                tax = taxonomy().get(sig.code)
                if not tax or tax["source"] != "text" or not verify_quote(sig.evidence_quote, page_texts, ch["url"]):
                    llm_rejected += 1       # codigo invalido ou citacao inexistente => descartado (anti-alucinacao)
                    continue
                if injection_count(sig.evidence_quote):
                    llm_rejected += 1
                    continue
                h = hits.setdefault(sig.code, SignalHit(code=sig.code, kind=tax["kind"], strength=tax["strength"], confidence=sig.confidence))
                if all(e.source_text != sig.evidence_quote for e in h.evidence) and len(h.evidence) < 2:
                    h.evidence.append(Evidence(claim=f"(LLM) {tax['description']}", type="fact", signal_code=sig.code, source_url=ch["url"],
                                               source_text=sig.evidence_quote, confidence=sig.confidence))
                    llm_added += 1
    m["llm_added"] = m.get("llm_added", 0) + llm_added
    m["llm_rejected"] = m.get("llm_rejected", 0) + llm_rejected
    hits.update(detect_technical_signals(pages, unreachable, f"https://{org['domain']}/" if org["domain"] else None))
    # verificacao final de TODA evidencia de texto
    rejected = 0
    for h in hits.values():
        keep = []
        for e in h.evidence:
            e.verified = e.source_kind == "technical_check" or verify_quote(e.source_text, page_texts, e.source_url)
            if e.verified: keep.append(e)
            else: rejected += 1
        h.evidence = keep
    m["evidence_rejected"] = m.get("evidence_rejected", 0) + rejected
    hits = {c: h for c, h in hits.items() if h.evidence}

    facts = extract_numeric_facts(text_all)
    segment = detect_segment(text_all, org.get("segment"))
    conn.execute("UPDATE organization SET segment=? WHERE id=?", (segment, org_id))
    result = compute_scores(hits, facts, text_all, len(pages), inj, segment, known, org)
    result["reactivation_candidate"] = antiicp.reactivation_flag(known)
    result["known"] = known
    result["injection_flags"] = inj
    conn.execute("INSERT INTO company_profile(org_id,run_id,facts,extractor_version,created_at) VALUES(?,?,?,?,?)", (org_id, run_id, jdump(facts), EXTRACTOR_VERSION, now()))

    status, why = "ranked", None
    if result["need_signals_verified"] < scoring_cfg()["evidence"]["min_distinct_signals_ranked"]:
        status, why = "inconclusive", "nenhum sinal de necessidade verificado"
    prof = load_profile()
    svc_defs = {x["id"]: x for x in prof["asimov"]["services"]}
    cases = [c for c in prof["asimov"]["case_studies"]]
    sims = []
    if embedder and text_all:
        sc = embedder.similarities(text_all[:6000], [f"{c['client']} {c['problem']}" for c in cases])
        sims = sorted(((f"{c['client']}{'' if c['verified'] else ' (nao verificado)'}", round(x, 2)) for c, x in zip(cases, sc)), key=lambda t: -t[1])[:2]
    expl = build_explanation(result, hits, svc_defs, sims)
    m["time_s"] = m.get("time_s", 0) + round(time.time() - t0, 2)
    return _save(conn, org_id, run_id, status, why, backend, result, list(hits.values()), expl, m)


def _save(conn, org_id, run_id, status, reason, backend, result, hits, expl, m) -> dict:
    cur = conn.execute("INSERT INTO analysis(org_id,run_id,status,reason,llm_backend,model,prompt_hash,weights_hash,result,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (org_id, run_id, status, reason, backend.name, backend.model, backend.prompt_hash, config_hash(), jdump({**result, "explanation": expl}), now()))
    aid = cur.lastrowid
    for h in hits:
        for e in h.evidence:
            conn.execute("INSERT INTO evidence(analysis_id,org_id,signal_code,claim,type,source_kind,source_url,source_text,confidence,verified) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (aid, org_id, e.signal_code, e.claim, e.type, e.source_kind, e.source_url, e.source_text, e.confidence, int(e.verified)))
    if "final" in result:
        for svc, v in result["service_scores"].items():
            conn.execute("INSERT INTO score(analysis_id,service_id,value,components) VALUES(?,?,?,?)", (aid, svc, v, jdump({"fit_raw": result["service_fit_raw"][svc]})))
        conn.execute("INSERT INTO score(analysis_id,service_id,value,components) VALUES(?,?,?,?)", (aid, "FINAL", result["final"], jdump(result["components"])))
        conn.execute("INSERT INTO score(analysis_id,service_id,value,components) VALUES(?,?,?,?)", (aid, "B1", result["baseline_b1"], "{}"))
        sv = expl["best_service"]
        conn.execute("INSERT INTO opportunity(analysis_id,service_id,hypothesis,explanation,confidence) VALUES(?,?,?,?,?)", (aid, sv, expl["hypothesis"], expl["text"], result["evidence_multiplier"]))
    conn.execute("UPDATE organization SET status=? WHERE id=?", (status, org_id))
    conn.commit()
    m[status] = m.get(status, 0) + 1
    return {"analysis_id": aid, "status": status, "reason": reason, "org_id": org_id}


def run_pipeline(conn, candidates: list[Candidate], source: PageSource, s: Settings, run_cfg: dict | None = None, progress: Callable | None = None) -> int:
    run_id = start_run(conn, run_cfg or {})
    metrics = {"found": len(candidates), "new": 0, "duplicates": 0}
    embedder = Embedder(s.embedding_backend, s.st_model)
    for c in candidates:
        oid, new = upsert_org(conn, c)
        metrics["new" if new else "duplicates"] += 1
        res = analyze_org(conn, oid, run_id, source, s, embedder, metrics)
        if progress: progress(c.name, res)
    conn.execute("UPDATE search_run SET finished_at=?, metrics=? WHERE id=?", (now(), jdump(metrics), run_id))
    conn.commit()
    return run_id


def ranking(conn, run_id: int | None = None, service: str | None = None, include_known_reactivation: bool = True) -> list[dict]:
    q = """SELECT o.id org_id, o.name, o.domain, o.segment, a.id analysis_id, a.run_id, a.result, a.created_at
           FROM analysis a JOIN organization o ON o.id=a.org_id
           WHERE a.status='ranked' AND a.id=(SELECT MAX(id) FROM analysis WHERE org_id=o.id AND status='ranked')"""
    rows = []
    for r in conn.execute(q):
        res = json.loads(r["result"])
        if run_id and r["run_id"] != run_id:
            continue
        score = res["service_scores"][service] if service else res["final"]
        rows.append({"org_id": r["org_id"], "analysis_id": r["analysis_id"], "name": r["name"], "domain": r["domain"], "segment": r["segment"],
                     "score": score, "final": res["final"], "b1": res["baseline_b1"], "best_service": res["best_service"],
                     "service_scores": res["service_scores"], "evidence_multiplier": res["evidence_multiplier"],
                     "reactivation": res.get("reactivation_candidate", False), "explanation": res["explanation"]})
    rows.sort(key=lambda x: -x["score"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows
