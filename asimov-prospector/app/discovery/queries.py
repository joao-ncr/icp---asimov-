"""Gerador de queries por PROBLEMA: ICP -> segmento x termo de problema x regiao. Opcionalmente expandido por LLM local."""
from __future__ import annotations
import itertools, json
import httpx
from app.core.settings import Settings


def template_queries(icp: dict, regions: list[str], per_icp: int = 12) -> list[dict]:
    out = []
    combos = list(itertools.product(icp["segments"], icp["problem_terms"]))
    # intercala regioes para diversificar sem explodir o numero de queries
    for i, (seg, term) in enumerate(combos):
        region = regions[i % len(regions)]
        out.append({"icp_id": icp["id"], "query": f'"{seg}" "{term}" {region}',
                    "rationale": f"{icp['name']}: segmento '{seg}' com termo de problema '{term}' na regiao '{region}'."})
    step = max(1, len(out) // per_icp)
    return out[::step][:per_icp]


def llm_queries(icp: dict, regions: list[str], s: Settings, n: int = 8) -> list[dict]:
    tpl = (s.prompts_dir / "generate_queries.md").read_text(encoding="utf-8")
    prompt = (tpl.replace("{icp_name}", icp["name"]).replace("{icp_description}", icp["description"])
              .replace("{segments}", ", ".join(icp["segments"])).replace("{problem_terms}", ", ".join(icp["problem_terms"]))
              .replace("{regions}", ", ".join(regions)).replace("{n}", str(n)))
    try:
        r = httpx.post(s.ollama_url + "/api/chat", timeout=120, json={"model": s.ollama_model, "stream": False, "format": "json",
                       "options": {"temperature": 0.2}, "messages": [{"role": "user", "content": prompt}]})
        items = json.loads(r.json()["message"]["content"])["queries"]
        return [{"icp_id": icp["id"], "query": q["query"][:200], "rationale": q.get("rationale", "")[:300]} for q in items[:n]]
    except Exception:
        return []


def generate_queries(icps_cfg: dict, s: Settings, use_llm: bool = False, per_icp: int = 12) -> list[dict]:
    out = []
    for icp in icps_cfg["icps"]:
        qs = template_queries(icp, icps_cfg["regions"], per_icp)
        if use_llm:
            qs += llm_queries(icp, icps_cfg["regions"], s)
        out += qs
    return out
