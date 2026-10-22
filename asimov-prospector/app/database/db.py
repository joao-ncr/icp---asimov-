from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterator
from app.core.settings import get_settings

SCHEMA = Path(__file__).with_name("schema.sql")
BUSY_TIMEOUT_S = 30     # espera por lock de outro escritor (ex.: outra aba/processo do Streamlit) antes de falhar


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = path or get_settings().db_path
    conn = sqlite3.connect(str(p), timeout=BUSY_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_S * 1000}")
    if str(p) != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def session(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Conexao de vida curta: commit se tudo der certo, rollback em erro, sempre fecha.
    Evita conexoes vazadas (uma por rerun do Streamlit) que seguravam locks no SQLite."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


@lru_cache(maxsize=None)
def ensure_ready(path: str | None = None) -> None:
    """Cria schema e carrega o perfil Asimov uma unica vez por processo (idempotente)."""
    from app.core.profile import seed_db     # import tardio: profile depende de intelligence, que nao depende do banco
    with session(path) as conn:
        init_db(conn)
        seed_db(conn)
