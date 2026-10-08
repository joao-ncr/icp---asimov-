from __future__ import annotations
import hashlib, json, re, unicodedata
from pathlib import Path
from urllib.parse import urlparse
import yaml

LEGAL_SUFFIX = re.compile(r"\b(ltda|me|epp|eireli|sa|s/a|s\.a\.|mei|cia|companhia)\b\.?")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(s).lower()).strip()


def norm_name(s: str) -> str:
    s = norm_text(s)
    s = LEGAL_SUFFIX.sub(" ", s)
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def norm_domain(url_or_domain: str | None) -> str | None:
    if not url_or_domain:
        return None
    u = url_or_domain.strip()
    if "://" not in u:
        u = "http://" + u
    host = (urlparse(u).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return host or None


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def jdump(o) -> str:
    return json.dumps(o, ensure_ascii=False, default=str)


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
