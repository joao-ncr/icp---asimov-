"""HTML -> texto limpo + features tecnicas + deteccao de prompt injection."""
from __future__ import annotations
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from app.core.utils import norm_text, norm_domain

INJECTION_PATTERNS = [
    r"ignor(e|em|ar) (todas? )?(as |os )?(instruc|ordens|regras|prompts?)", r"ignore (all |any )?(previous|prior|above) (instructions|prompts?)",
    r"desconsidere (as |todas)", r"classifiqu?e (esta|nossa|essa|a) empresa", r"classify (this|our) (company|business)",
    r"voce (agora )?(e|deve|precisa)\b.{0,40}(assistente|modelo|ia\b)", r"you are (now )?(an?|the) (ai|assistant|model)",
    r"system prompt", r"prompt do sistema", r"(excelente|otimo|melhor) prospect", r"(de|atribua|give) (a )?(nota|score|pontuacao) (maxima|100|10)",
    r"responda (apenas|somente) com", r"<\s*/?\s*(system|instruction)s?\s*>",
]
INJ_RE = [re.compile(p) for p in INJECTION_PATTERNS]
HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0(?![.\d])")
PATH_HINTS = ["sobre", "quem-somos", "empresa", "servico", "produto", "solucoes", "unidades", "lojas", "clientes",
              "contato", "carreira", "trabalhe", "atuacao", "institucional", "portfolio", "area-do-cliente"]


def injection_count(text: str) -> int:
    t = norm_text(text)
    return sum(1 for r in INJ_RE if r.search(t))


def extract_page(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    feats: dict = {}
    head = soup.find("head")
    vp = soup.find("meta", attrs={"name": re.compile("viewport", re.I)})
    feats["has_viewport"] = vp is not None
    feats["https"] = url.startswith("https://")
    feats["title"] = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    feats["meta_description"] = (md.get("content") or "").strip() if md else ""
    gen = soup.find("meta", attrs={"name": re.compile("generator", re.I)})
    feats["generator"] = (gen.get("content") or "")[:60] if gen else ""
    hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
    feats["has_whatsapp"] = any("wa.me" in h or "api.whatsapp.com" in h or "whatsapp" in h.lower() for h in hrefs)
    feats["has_form"] = soup.find("form") is not None
    feats["app_links"] = any("play.google.com" in h or "apps.apple.com" in h for h in hrefs)
    # elementos ocultos: remover do texto e checar se escondem instrucoes
    hidden_inj = 0
    for el in soup.find_all(True):
        if el.attrs is None:
            continue
        st = el.get("style", "") or ""
        if el.has_attr("hidden") or HIDDEN_STYLE.search(st):
            hidden_inj += injection_count(el.get_text(" ", strip=True))
            el.decompose()
    for tag in soup(["script", "style", "noscript", "template", "svg", "iframe", "nav", "form"]):
        tag.decompose()       # footer e mantido de proposito (copyright, unidades, enderecos)
    text = "\n".join(t.strip() for t in soup.get_text("\n").splitlines() if t.strip())
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)[^0-9]{0,40}((?:19|20)\d{2})", html, re.I)]
    feats["copyright_year"] = max(years) if years else None
    feats["hidden_injection"] = hidden_inj
    links = []
    base = norm_domain(url)
    for h in hrefs:
        u = urljoin(url, h.split("#")[0])
        if urlparse(u).scheme in ("http", "https") and norm_domain(u) == base:
            links.append(u)
    return {"text": text, "features": feats, "links": list(dict.fromkeys(links)),
            "injection_flags": injection_count(text) + hidden_inj}


def rank_links(links: list[str], limit: int) -> list[str]:
    def score(u):
        path = norm_text(urlparse(u).path)
        return -sum(1 for h in PATH_HINTS if h in path), len(path)
    return sorted({u.rstrip("/") for u in links if not re.search(r"\.(pdf|jpg|png|zip|docx?|xlsx?)$", u, re.I)}, key=score)[:limit]
