"""Orquestrador: candidato -> (anti-ICP previo) -> crawl -> texto -> sinais -> score -> ranking.
Etapas gravam no SQLite; metricas ficam em search_run.metrics."""
from __future__ import annotations
import json, time
from dataclasses import dataclass, field
from typing import Callable, Protocol
from app.core.profile import load_profile
from app.core.settings import Settings
from app.core.utils import is_platform_domain, jdump, norm_domain
from app.crawler.extract import extract_page, injection_count, rank_links
from app.crawler.fetcher import Fetcher
from app.database.db import now
from app.database.run_lock import exclusive_run
from app.discovery.dedup import OrgIndex, upsert_org
from app.discovery.historical import history_for_org, summarize_history
from app.feedback.store import refresh_calibration
from app.extraction.text import chunk_text, extract_numeric_facts, verify_quote
from app.intelligence.embeddings import Embedder
from app.intelligence.llm import get_backend
from app.intelligence.signals import detect_technical_signals, detect_text_signals, taxonomy
from app.models.schemas import Candidate, Evidence, SignalHit
from app.ranking import ranking  # noqa: F401  (reexportado: run.py e testes importam daqui)
from app.scoring import antiicp
from app.scoring.calibration import Calibration
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
            try:
                r = self.f.fetch(u)
            except Exception:
                # Falha em pagina secundaria nao invalida as paginas ja coletadas.
                continue
            if r.ok:
                pages.append({"url": r.final_url, "status_code": r.status, **extract_page(r.body, r.final_url)})
        return pages, None


class StoredPageSource:
    """Paginas ja gravadas no banco: reaplica o scoring (ex.: apos nova calibracao) sem refazer o crawl."""
    def __init__(self, conn):
        self.conn = conn

    def get_pages(self, domain: str, max_pages: int):
        rows = self.conn.execute("""SELECT p.url, p.status_code, p.text, p.features, p.injection_flags FROM page p
                                    JOIN organization o ON o.id=p.org_id WHERE o.domain=? ORDER BY p.id LIMIT ?""", (domain, max_pages)).fetchall()
        # Sem paginas guardadas = a empresa foi ranqueada por dominio inexistente (inferencia por ausencia).
        return [{**dict(r), "features": json.loads(r["features"] or "{}")} for r in rows], (None if rows else "dns_failure")


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
    run_id = conn.execute("INSERT INTO search_run(started_at,config,metrics) VALUES(?,?,?)", (now(), jdump(config), "{}")).lastrowid
    conn.commit()
    return run_id


def analyze_org(conn, org_id: int, run_id: int, source: PageSource, s: Settings, embedder: Embedder | None = None, metrics: dict | None = None,
                known_index: antiicp.KnownLeadIndex | None = None, calibration: Calibration | None = None) -> dict:
    m = metrics if metrics is not None else {}
    org = dict(conn.execute("SELECT * FROM organization WHERE id=?", (org_id,)).fetchone())
    backend = get_backend(s)
    t0 = time.time()
    known = antiicp.match_known_lead(conn, org["name"], org["domain"], known_index)
    if known:
        conn.execute("UPDATE organization SET known_status=?, known_detail=? WHERE id=?", (known["outcome"], jdump(known), org_id))
        conn.commit()           # nao segurar lock de escrita durante o crawl (rede lenta bloquearia outras sessoes)
    history = history_for_org(conn, org_id)
    context = {"known": known, "history": summarize_history(history)}
    excl, reason = antiicp.precheck(known)
    if excl:
        return _save(conn, org_id, run_id, "excluded", reason, backend, context, [], {}, m)
    if not org.get("domain") or is_platform_domain(org["domain"]):
        return _save(conn, org_id, run_id, "inconclusive", "no_domain: site próprio não informado (sem site ou só rede social)", backend, context, [], {}, m)

    pages, err = source.get_pages(org["domain"], s.max_pages_per_domain)
    if err and "dns_failure" in err:
        err = "dns_failure"          # dominio inexistente => 'sem site' (inferencia por ausencia), nao 'bloqueado'
    m["pages"] = m.get("pages", 0) + len(pages)
    unreachable = not pages
    if unreachable and err not in ("dns_failure", "no_domain"):
        # Falhas de transporte/SSL sao erros daquela empresa; bloqueios de acesso
        # continuam como blocked. Nenhum deles e tratado como "sem site".
        if (err or "").startswith(("network:", "ssl:")):
            status = "error"
        else:
            status = "blocked"
        return _save(conn, org_id, run_id, status, err, backend, context, [], {}, m)

    conn.execute("DELETE FROM page WHERE org_id=?", (org_id,))
    for p in pages:
        conn.execute("INSERT OR REPLACE INTO page(org_id,url,status_code,fetched_at,text,features,injection_flags) VALUES(?,?,?,?,?,?,?)",
                     (org_id, p["url"], p["status_code"], now(), p["text"], jdump(p["features"]), p["injection_flags"]))
    text_all = "\n".join(p["text"] for p in pages)
    inj = sum(p["injection_flags"] for p in pages)

    a = antiicp.cfg()["anti_icp"]
    if pages and len(text_all) < a["min_text_chars"]:
        return _save(conn, org_id, run_id, "inconclusive", "presenca publica insuficiente (pouco texto)", backend, context, [], {}, m)
    if pages and antiicp.is_competitor(text_all):
        return _save(conn, org_id, run_id, "excluded", "possivel concorrente (software house/agencia)", backend, context, [], {}, m)

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
    result = compute_scores(hits, facts, text_all, len(pages), inj, segment, known, org, calibration)
    result["reactivation_candidate"] = antiicp.reactivation_flag(known)
    result["known"] = known
    result["history"] = summarize_history(history, result["best_service"])
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
    agrees = (result["history"] or {}).get("agrees_with_model")
    if agrees is not None:
        key = "history_agree" if agrees else "history_disagree"
        m[key] = m.get(key, 0) + 1
    m["time_s"] = m.get("time_s", 0) + round(time.time() - t0, 2)
    return _save(conn, org_id, run_id, status, why, backend, result, list(hits.values()), expl, m)


def _weights_hash(result: dict) -> str:
    """Versao dos pesos + da calibracao aprendida, para reproduzir qualquer pontuacao depois."""
    version = result.get("calibration_version")
    return f"{config_hash()}+cal{version}" if version else config_hash()


def _save(conn, org_id, run_id, status, reason, backend, result, hits, expl, m) -> dict:
    cur = conn.execute("INSERT INTO analysis(org_id,run_id,status,reason,llm_backend,model,prompt_hash,weights_hash,result,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (org_id, run_id, status, reason, backend.name, backend.model, backend.prompt_hash, _weights_hash(result), jdump({**result, "explanation": expl}), now()))
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


@dataclass
class RunContext:
    """Estado compartilhado de uma rodada: evita recarregar indices e permite pular leads semelhantes."""
    run_id: int
    source: PageSource
    settings: Settings
    embedder: Embedder
    org_index: OrgIndex
    known_index: antiicp.KnownLeadIndex
    calibration: Calibration
    metrics: dict
    seen_orgs: set[int] = field(default_factory=set)


def run_pipeline(conn, candidates: list[Candidate], source: PageSource, s: Settings, run_cfg: dict | None = None, progress: Callable | None = None) -> int:
    """Executa uma rodada. Levanta RunInProgress se outra rodada (nesta ou em outra aba/processo) ja estiver ativa."""
    run_cfg = run_cfg or {}
    with exclusive_run(conn, run_cfg.get("mode", "analise")) as beat:
        run_id = start_run(conn, run_cfg)
        calibration = refresh_calibration(conn)
        metrics = {"found": len(candidates), "new": 0, "duplicates": 0, "skipped_similar": 0, "calibration_version": calibration.version if calibration.active else 0}
        ctx = RunContext(run_id, source, s, Embedder(s.embedding_backend, s.st_model), OrgIndex.from_db(conn),
                         antiicp.KnownLeadIndex.from_db(conn), calibration, metrics)
        try:
            for c in candidates:
                res = _analyze_candidate(conn, c, ctx)
                beat()
                if progress: progress(c.name, res)
        finally:
            # Mesmo se a rodada for interrompida, o run fecha com as metricas parciais (nao fica "{}" para sempre).
            conn.rollback()
            conn.execute("UPDATE search_run SET finished_at=?, metrics=? WHERE id=?", (now(), jdump(metrics), run_id))
            conn.commit()
    return run_id


def _analyze_candidate(conn, c: Candidate, ctx: RunContext) -> dict:
    """Uma empresa nunca aborta a rodada: o erro vira analise 'error' no proprio run e a proxima segue.
    Leads que a deduplicacao trata como a mesma empresa (nome semelhante) sao analisados uma unica vez por rodada."""
    oid = None
    try:
        oid, new = upsert_org(conn, c, ctx.org_index)
        ctx.metrics["new" if new else "duplicates"] += 1
        if oid in ctx.seen_orgs:
            ctx.metrics["skipped_similar"] += 1
            return {"analysis_id": None, "status": "duplicate", "org_id": oid,
                    "reason": "nome ou site semelhante a outro lead desta rodada; apenas um é analisado"}
        ctx.seen_orgs.add(oid)
        return analyze_org(conn, oid, ctx.run_id, ctx.source, ctx.settings, ctx.embedder, ctx.metrics, ctx.known_index, ctx.calibration)
    except Exception as exc:
        conn.rollback()         # descarta transacao parcial antes de gravar o erro (e libera o lock)
        reason = f"pipeline_error:{type(exc).__name__}:{str(exc)[:240]}"
        ctx.metrics["pipeline_errors"] = ctx.metrics.get("pipeline_errors", 0) + 1
        if oid is None:
            return {"analysis_id": None, "status": "error", "reason": reason, "org_id": None}
        try:
            return _save(conn, oid, ctx.run_id, "error", reason, get_backend(ctx.settings), {"known": None}, [], {}, ctx.metrics)
        except Exception:
            conn.rollback()
            return {"analysis_id": None, "status": "error", "reason": reason, "org_id": oid}


def reapply_learning(conn, s: Settings, progress: Callable | None = None) -> int:
    """Reanalisa, SEM rede, as empresas ja ranqueadas usando as paginas guardadas e a calibracao vigente."""
    orgs = conn.execute("""SELECT o.name, o.domain, o.cnpj, o.municipio, o.uf, o.segment FROM organization o
                           WHERE EXISTS (SELECT 1 FROM analysis a WHERE a.org_id=o.id AND a.status='ranked') ORDER BY o.id""").fetchall()
    candidates = [Candidate(name=o["name"], domain=o["domain"], cnpj=o["cnpj"], municipio=o["municipio"], uf=o["uf"],
                            segment=o["segment"], source="reapply") for o in orgs]
    return run_pipeline(conn, candidates, StoredPageSource(conn), s, {"mode": "reapply_learning", "count": len(candidates)}, progress)
