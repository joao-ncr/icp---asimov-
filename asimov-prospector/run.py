#!/usr/bin/env python3
"""CLI do Asimov Prospector.  python run.py --help"""
from __future__ import annotations
import argparse, csv, json, subprocess, sys
from pathlib import Path
from app.core.profile import load_profile, seed_db
from app.core.settings import ROOT, get_settings
from app.core.utils import jdump, norm_domain
from app.database.db import connect, init_db, now
from app.discovery import leads as leadsmod, queries as qmod, sources
from app.discovery.dedup import upsert_org
from app.models.schemas import Candidate
from app.pipeline import FixtureSource, WebPageSource, analyze_org, ranking, run_pipeline, start_run
from app.scoring.score import SERVICES


def db():
    c = connect(); init_db(c); seed_db(c); return c


def print_ranking(rows, top):
    for r in rows[:top]:
        ss = "  ".join(f"{k[:4]}={v:.0f}" for k, v in sorted(r["service_scores"].items(), key=lambda t: -t[1]))
        flag = "  [reativacao]" if r["reactivation"] else ""
        print(f"#{r['rank']:<2} {r['name'][:34]:<34} score={r['final']:>5.1f}  B1={r['b1']:>5.1f}  melhor={r['best_service']:<10} ({ss}){flag}")
        print(f"      {r['explanation']['text'][:260]}")


def cmd_setup(a):
    """Prepara uma instalação local para uso diário, sem Docker."""
    c = db()
    ref = ROOT / "data" / "leads_reference.xlsx"
    if ref.exists():
        print("leads de referencia:", leadsmod.import_leads(c, ref))
    template = ROOT / "data" / "seeds_template.csv"
    target = ROOT / "data" / "seeds.csv"
    if not target.exists() and template.exists():
        target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        print("template de seeds criado em", target)
    print("banco pronto em", get_settings().db_path)
    print("proximo passo: python run.py ui")


def cmd_init(a):
    c = db()
    xlsx = Path(a.leads) if a.leads else ROOT / "data" / "leads.xlsx"
    if xlsx.exists():
        print("leads importados:", leadsmod.import_leads(c, xlsx))
    else:
        seed = ROOT / "data" / "leads_seed.csv"
        if seed.exists():
            c.execute("DELETE FROM known_lead")
            for r in csv.DictReader(open(seed, encoding="utf-8")):
                from app.core.utils import norm_name
                c.execute("INSERT INTO known_lead(name,name_norm,outcome,value,funnel,loss_reason,loss_category,segment,is_person,created_month) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (r["name"], norm_name(r["name"]), r["outcome"], float(r["value"] or 0), r["funnel"], r["loss_reason"] or None, r["loss_category"] or None, r["segment"], int(r["is_person"]), r["created_month"]))
            c.commit(); print("leads importados do seed CSV")
    print("banco pronto em", get_settings().db_path)


def cmd_import_leads(a):
    c = db(); print("leads importados:", leadsmod.import_leads(c, Path(a.path)))


def cmd_queries(a):
    s = get_settings(); icps = load_profile()["icps"]
    qs = qmod.generate_queries(icps, s, use_llm=a.llm, per_icp=a.per_icp)
    for q in qs: print(f"[{q['icp_id']}] {q['query']}\n      -> {q['rationale']}")
    if a.save:
        Path(a.save).write_text(json.dumps(qs, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_analyze_url(a):
    s = get_settings(); c = db()
    from app.crawler.fetcher import Fetcher
    f = Fetcher(s)
    dom = norm_domain(a.url)
    rid = start_run(c, {"mode": "phase0", "url": a.url})
    oid, _ = upsert_org(c, Candidate(name=a.name or dom, domain=dom, source="phase0"))
    m = {}
    res = analyze_org(c, oid, rid, WebPageSource(f, s), s, None, m)
    print("status:", res["status"], res["reason"] or "")
    from app.intelligence.embeddings import Embedder
    rows = [r for r in ranking(c) if r["org_id"] == oid]
    if rows: print_ranking(rows, 1)
    print("crawler:", f.stats, "metricas:", m)


def collect_candidates(a, s) -> list[Candidate]:
    cands = []
    if a.seeds: cands += sources.from_seed_csv(Path(a.seeds))
    if a.cnpj_csv:
        cands += sources.from_cnpj_csv(Path(a.cnpj_csv), a.cnae or [], a.uf, a.municipio, a.limit)
    if a.searx_queries and s.searxng_url:
        for q in qmod.generate_queries(load_profile()["icps"], s, per_icp=4):
            cands += sources.discover_by_query(s, q)
    for c in cands:
        if not c.domain and s.searxng_url:
            c.domain = sources.resolve_domain(s, c.name, c.municipio)
    return cands


def cmd_run(a):
    s = get_settings(); c = db()
    cands = collect_candidates(a, s)
    if not cands: sys.exit("Nenhum candidato. Use --seeds data/seeds.csv (colunas: name,domain,municipio,uf,segment) e/ou --cnpj-csv.")
    from app.crawler.fetcher import Fetcher
    f = Fetcher(s)
    rid = run_pipeline(c, cands, WebPageSource(f, s), s, {"seeds": a.seeds, "cnpj": a.cnpj_csv}, lambda n, r: print(f"  {n[:40]:<40} -> {r['status']} {r['reason'] or ''}"))
    print("crawler:", f.stats); print(c.execute("SELECT metrics FROM search_run WHERE id=?", (rid,)).fetchone()[0])
    print_ranking(ranking(c, rid), a.top)


def cmd_demo(a):
    s = get_settings()
    s.db_path = ROOT / "data" / "demo.db"
    if s.db_path.exists(): s.db_path.unlink()
    c = connect(s.db_path); init_db(c); seed_db(c)
    import os; os.environ["DB_PATH"] = str(s.db_path)
    seed = ROOT / "data" / "leads_seed.csv"
    from app.core.utils import norm_name
    for r in csv.DictReader(open(seed, encoding="utf-8")):
        c.execute("INSERT INTO known_lead(name,name_norm,outcome,value,funnel,loss_reason,loss_category,segment,is_person,created_month) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (r["name"], norm_name(r["name"]), r["outcome"], float(r["value"] or 0), r["funnel"], r["loss_reason"] or None, r["loss_category"] or None, r["segment"], int(r["is_person"]), r["created_month"]))
    c.commit()
    print("== 1. Queries por problema (amostra, ICP_B) =="); [print("  ", q["query"]) for q in qmod.generate_queries(load_profile()["icps"], s, per_icp=3) if q["icp_id"] == "ICP_B"]
    print("\n== 2. Pipeline sobre sites ficticios (fixtures offline) ==")
    cands = sources.from_seed_csv(ROOT / "data" / "seeds_demo.csv")
    rid = run_pipeline(c, cands, FixtureSource(ROOT / "tests" / "fixtures" / "sites"), s, {"mode": "demo"}, lambda n, r: print(f"  {n[:40]:<40} -> {r['status']} {r['reason'] or ''}"))
    print("\n== 3. Ranking =="); rows = ranking(c, rid); print_ranking(rows, 10)
    print("\n== 4. Avaliacao (rotulos de DEMONSTRACAO) ==")
    from eval.run_eval import evaluate, load_labels
    print(json.dumps(evaluate(rows, load_labels(ROOT / "eval" / "demo_labels.csv")), indent=1, ensure_ascii=False))
    print("\nBanco da demo:", s.db_path)


def cmd_rank(a):
    c = db(); rows = ranking(c, service=a.service); print_ranking(rows, a.top)
    if a.export:
        with open(a.export, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["rank", "name", "domain", "score", "best_service"] + SERVICES + ["explanation"])
            for r in rows: w.writerow([r["rank"], r["name"], r["domain"], r["final"], r["best_service"]] + [r["service_scores"][x] for x in SERVICES] + [r["explanation"]["text"]])



def cmd_report(a):
    """Exporta um relatório comercial com evidencias e hipótese, sem dados de contato/outreach."""
    c = db(); rows = ranking(c, service=a.service)[:a.top]
    cols = ["rank", "name", "domain", "municipio", "uf", "segment", "score", "best_service", "confidence", "hypothesis", "signals", "evidence_urls", "reactivation"]
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows:
            org = c.execute("SELECT municipio,uf FROM organization WHERE id=?", (r["org_id"],)).fetchone()
            ev = list(c.execute("SELECT signal_code,source_url FROM evidence WHERE analysis_id=? AND verified=1 ORDER BY confidence DESC", (r["analysis_id"],)))
            signals = "; ".join(r["explanation"].get("facts", [])[:3])
            urls = "; ".join(dict.fromkeys(x["source_url"] for x in ev if x["source_url"]))
            conf = confidence_label(r["evidence_multiplier"], r["explanation"])
            w.writerow({"rank":r["rank"],"name":r["name"],"domain":r["domain"],"municipio":org["municipio"] if org else "","uf":org["uf"] if org else "","segment":r["segment"],"score":r["final"],"best_service":r["best_service"],"confidence":conf,"hypothesis":r["explanation"].get("hypothesis",""),"signals":signals,"evidence_urls":urls,"reactivation":r["reactivation"]})
    print(f"relatorio salvo em {a.out}: {len(rows)} empresas")


def confidence_label(mult, explanation):
    facts = len(explanation.get("facts", []))
    if mult >= 0.78 and facts >= 2: return "alta"
    if mult >= 0.62 and facts >= 1: return "media"
    return "baixa"

def cmd_feedback(a):
    c = db()
    an = c.execute("SELECT MAX(id) FROM analysis WHERE org_id=?", (a.org,)).fetchone()[0]
    c.execute("INSERT INTO human_feedback(org_id,analysis_id,quality,status,reason,author,created_at) VALUES(?,?,?,?,?,?,?)", (a.org, an, a.quality, a.status, a.reason, a.author, now()))
    c.commit(); print("feedback registrado")


def cmd_export_labels(a):
    """Gera planilha CEGA (sem score) para rotulagem humana. Mistura B1 e B2 (pooling) e embaralha."""
    import random
    c = db(); rows = ranking(c)
    top = {r["org_id"]: r for r in sorted(rows, key=lambda r: -r["final"])[:a.k]}
    top.update({r["org_id"]: r for r in sorted(rows, key=lambda r: -r["b1"])[:a.k]})
    items = list(top.values()); random.Random(3).shuffle(items)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["domain", "name", "label", "rater", "notes"])
        for r in items: w.writerow([r["domain"], r["name"], "", "", ""])
    print(f"{len(items)} empresas em {a.out}. Preencha 'label' (excelente|bom|mediano|ruim|sem_fit) e 'rater'.")


def cmd_eval(a):
    from eval.run_eval import evaluate, load_labels
    c = db(); print(json.dumps(evaluate(ranking(c), load_labels(Path(a.labels))), indent=1, ensure_ascii=False))


def cmd_backtest(a):
    """Fase 0 / sanidade: analisa leads com dominio preenchido em data/leads_enriched.csv e compara ganhos vs perdidos."""
    s = get_settings(); c = db()
    rows = [r for r in csv.DictReader(open(a.file, encoding="utf-8-sig")) if (r.get("domain") or "").strip()]
    if not rows: sys.exit("Preencha a coluna 'domain' em data/leads_enriched.csv (ao menos alguns ganhos e perdidos).")
    from app.crawler.fetcher import Fetcher
    f = Fetcher(s); rid = start_run(c, {"mode": "backtest"}); out = []
    for r in rows:
        oid, _ = upsert_org(c, Candidate(name=r["name"], domain=r["domain"], source="backtest"))
        res = analyze_org(c, oid, rid, WebPageSource(f, s), s)
        sc = c.execute("SELECT value FROM score WHERE analysis_id=? AND service_id='FINAL'", (res["analysis_id"],)).fetchone()
        out.append((r["name"], r["outcome"], sc[0] if sc else None, res["status"]))
    for o in out: print(o)
    won = [x[2] for x in out if x[1] == "won" and x[2] is not None]; lost = [x[2] for x in out if x[1] == "lost" and x[2] is not None]
    if won and lost: print(f"media score ganhos={sum(won)/len(won):.1f} perdidos={sum(lost)/len(lost):.1f}  (n={len(won)}/{len(lost)})")


def cmd_purge(a):
    c = db()
    cur = c.execute("DELETE FROM page WHERE fetched_at < datetime('now', ?)", (f"-{a.days} days",)); c.commit()
    import time
    n = 0
    for p in get_settings().cache_dir.glob("*.json"):
        if time.time() - p.stat().st_mtime > a.days * 86400: p.unlink(); n += 1
    print(f"paginas removidas: {cur.rowcount}; arquivos de cache removidos: {n}")


def cmd_ui(a):
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ROOT / "app" / "ui" / "streamlit_app.py")])


def main():
    p = argparse.ArgumentParser(description="Asimov Prospector - discovery + intelligence + matching (decisao humana)")
    sp = p.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("setup"); x.set_defaults(f=cmd_setup)
    x = sp.add_parser("init"); x.add_argument("--leads"); x.set_defaults(f=cmd_init)
    x = sp.add_parser("import-leads"); x.add_argument("path"); x.set_defaults(f=cmd_import_leads)
    x = sp.add_parser("queries"); x.add_argument("--llm", action="store_true"); x.add_argument("--per-icp", type=int, default=6); x.add_argument("--save"); x.set_defaults(f=cmd_queries)
    x = sp.add_parser("analyze-url"); x.add_argument("url"); x.add_argument("--name"); x.set_defaults(f=cmd_analyze_url)
    x = sp.add_parser("run"); x.add_argument("--seeds"); x.add_argument("--cnpj-csv"); x.add_argument("--cnae", nargs="*"); x.add_argument("--uf"); x.add_argument("--municipio", nargs="*")
    x.add_argument("--limit", type=int, default=200); x.add_argument("--searx-queries", action="store_true"); x.add_argument("--top", type=int, default=20); x.set_defaults(f=cmd_run)
    x = sp.add_parser("demo"); x.set_defaults(f=cmd_demo)
    x = sp.add_parser("rank"); x.add_argument("--service", choices=SERVICES); x.add_argument("--top", type=int, default=20); x.add_argument("--export"); x.set_defaults(f=cmd_rank)
    x = sp.add_parser("report"); x.add_argument("--service", choices=SERVICES); x.add_argument("--top", type=int, default=20); x.add_argument("--out", default="data/prospects_report.csv"); x.set_defaults(f=cmd_report)
    x = sp.add_parser("feedback"); x.add_argument("--org", type=int, required=True)
    x.add_argument("--quality", choices=["excelente", "bom", "mediano", "ruim", "sem_fit"], required=True)
    x.add_argument("--status", default="novo", choices=["novo", "ja_conhecemos", "ja_e_cliente", "descartar", "contatar"]); x.add_argument("--reason", default=""); x.add_argument("--author", default=""); x.set_defaults(f=cmd_feedback)
    x = sp.add_parser("export-labels"); x.add_argument("--k", type=int, default=20); x.add_argument("--out", default="eval/labels_blind.csv"); x.set_defaults(f=cmd_export_labels)
    x = sp.add_parser("eval"); x.add_argument("--labels", required=True); x.set_defaults(f=cmd_eval)
    x = sp.add_parser("backtest-leads"); x.add_argument("--file", default="data/leads_enriched.csv"); x.set_defaults(f=cmd_backtest)
    x = sp.add_parser("purge"); x.add_argument("--days", type=int, default=get_settings().retention_days); x.set_defaults(f=cmd_purge)
    x = sp.add_parser("ui"); x.set_defaults(f=cmd_ui)
    a = p.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
