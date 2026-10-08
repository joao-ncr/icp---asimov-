"""Normalizacao, split em sentencas, chunking, extracao de fatos numericos e verificador de evidencia."""
from __future__ import annotations
import re
from app.core.utils import norm_text

SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")


def sentences(text: str, min_len: int = 15, max_len: int = 300) -> list[str]:
    out = []
    for s in SENT_SPLIT.split(text):
        s = s.strip()
        if len(s) >= min_len:
            out.append(s[:max_len])      # truncar preserva a propriedade de substring
    return out


def chunk_text(text: str, url: str, max_chars: int = 1500) -> list[dict]:
    chunks, cur = [], ""
    for para in text.split("\n"):
        if len(cur) + len(para) + 1 > max_chars and cur:
            chunks.append({"url": url, "text": cur})
            cur = ""
        cur += para + "\n"
    if cur.strip():
        chunks.append({"url": url, "text": cur})
    return chunks


def extract_numeric_facts(text: str) -> dict:
    t = norm_text(text)
    facts: dict = {}
    emp = [int(m.replace(".", "")) for m in re.findall(r"(\d[\d\.]*) (?:colaboradores|funcionarios|profissionais|empregados)", t)
           if m.replace(".", "").isdigit()]
    if emp:
        facts["employees_mentioned"] = max(emp)
    units = [int(n) for n, _ in re.findall(r"\b(\d{1,3}) (unidades|filiais|lojas|escritorios|franquias|polos|clinicas|agencias)\b", t)]
    if units:
        facts["units_mentioned"] = max(units)
    m = re.search(r"fundad[ao] em ((?:19|20)\d{2})|desde ((?:19|20)\d{2})", t)
    if m:
        facts["founded"] = int(m.group(1) or m.group(2))
    return facts


def verify_quote(quote: str, page_texts: dict[str, str], url: str) -> bool:
    """Evidencia so e valida se o trecho citado existe literalmente (normalizado) no texto da URL citada."""
    src = page_texts.get(url)
    if not src or not quote.strip():
        return False
    return re.sub(r"\s+", " ", quote).strip().lower() in re.sub(r"\s+", " ", src).lower()
