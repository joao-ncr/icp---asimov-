"""Configuracao central. Le variaveis de .env (parser simples, sem dependencias)."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


@dataclass
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.getenv("DB_PATH", ROOT / "data" / "asimov.db")))
    cache_dir: Path = field(default_factory=lambda: Path(os.getenv("CACHE_DIR", ROOT / "data" / "cache")))
    llm_backend: str = field(default_factory=lambda: os.getenv("LLM_BACKEND", "heuristic"))  # heuristic | ollama
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct"))
    embedding_backend: str = field(default_factory=lambda: os.getenv("EMBEDDING_BACKEND", "tfidf"))  # tfidf | st
    st_model: str = field(default_factory=lambda: os.getenv("ST_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"))
    searxng_url: str = field(default_factory=lambda: os.getenv("SEARXNG_URL", ""))
    user_agent: str = field(default_factory=lambda: os.getenv(
        "CRAWLER_USER_AGENT", "AsimovProspectorBot/0.1 (+contato: comercial@asimovjr.com.br)"))
    max_pages_per_domain: int = int(os.getenv("MAX_PAGES_PER_DOMAIN", "8"))
    max_bytes: int = int(os.getenv("MAX_RESPONSE_BYTES", str(2_000_000)))
    timeout_s: float = float(os.getenv("CRAWL_TIMEOUT_S", "10"))
    domain_delay_s: float = float(os.getenv("DOMAIN_DELAY_S", "1.5"))
    cache_ttl_days: int = int(os.getenv("CACHE_TTL_DAYS", "14"))
    retention_days: int = int(os.getenv("RETENTION_DAYS", "90"))
    max_retries: int = 2
    config_dir: Path = ROOT / "app" / "config"
    profile_dir: Path = ROOT / "profile"
    prompts_dir: Path = ROOT / "prompts"


def get_settings() -> Settings:
    s = Settings()
    s.db_path.parent.mkdir(parents=True, exist_ok=True)
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    return s
