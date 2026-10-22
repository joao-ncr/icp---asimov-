from __future__ import annotations
import hashlib, json, re, unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
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


@lru_cache
def _platform_hosts() -> tuple[str, ...]:
    from app.core.settings import get_settings   # import tardio: settings nao deve ser carregado so por importar utils
    return tuple(load_yaml(get_settings().config_dir / "platforms.yaml")["hosts"])


def is_platform_domain(domain: str | None) -> bool:
    """True para redes sociais/diretorios: o host e compartilhado por varias empresas."""
    return bool(domain) and any(domain == h or domain.endswith("." + h) for h in _platform_hosts())


def identity_domain(url_or_domain: str | None) -> str | None:
    """Dominio proprio da empresa (usado em dedup e crawl); None se vazio ou se for plataforma compartilhada."""
    d = norm_domain(url_or_domain)
    return None if is_platform_domain(d) else d


def similarity(a: str, b: str, floor: float = 0.0) -> float:
    """SequenceMatcher.ratio() com poda: se um limite superior barato ja fica abaixo de `floor`, devolve 0.0.
    Resultado identico a ratio() sempre que ele seria >= floor."""
    m = SequenceMatcher(None, a, b)
    if m.real_quick_ratio() < floor or m.quick_ratio() < floor:
        return 0.0
    return m.ratio()


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def jdump(o) -> str:
    return json.dumps(o, ensure_ascii=False, default=str)


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
