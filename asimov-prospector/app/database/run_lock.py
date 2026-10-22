"""Trava de rodada unica: so uma analise (crawler + banco) por vez, entre abas e processos.

A linha unica de `run_lock` e adquirida com BEGIN IMMEDIATE (atomico no SQLite). O dono renova o `heartbeat_at`
a cada empresa; se o processo morrer, a trava expira sozinha depois de STALE_AFTER_S."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Iterator
from uuid import uuid4
from app.database.db import now

STALE_AFTER_S = 600


class RunInProgress(RuntimeError):
    def __init__(self, label: str | None, started_at: str | None):
        self.label, self.started_at = label, started_at
        super().__init__(f"Já existe uma análise em andamento ({label or 'sem descrição'}, iniciada em {started_at}).")


def _is_fresh(heartbeat_at: str | None) -> bool:
    if not heartbeat_at:
        return False
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat_at)).total_seconds()
    return age < STALE_AFTER_S


def current_holder(conn) -> dict | None:
    """Rodada ativa (com heartbeat recente) ou None."""
    row = conn.execute("SELECT label, started_at, heartbeat_at FROM run_lock WHERE id=1").fetchone()
    return dict(row) if row and _is_fresh(row["heartbeat_at"]) else None


def _acquire(conn, owner: str, label: str) -> None:
    conn.commit()                                   # BEGIN IMMEDIATE nao pode ser aninhado em transacao aberta
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT * FROM run_lock WHERE id=1").fetchone()
        if row and row["owner"] != owner and _is_fresh(row["heartbeat_at"]):
            raise RunInProgress(row["label"], row["started_at"])
        stamp = now()
        conn.execute("""INSERT INTO run_lock(id, owner, label, started_at, heartbeat_at) VALUES(1,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET owner=excluded.owner, label=excluded.label,
                        started_at=excluded.started_at, heartbeat_at=excluded.heartbeat_at""", (owner, label, stamp, stamp))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _release(conn, owner: str) -> None:
    conn.rollback()
    conn.execute("DELETE FROM run_lock WHERE id=1 AND owner=?", (owner,))
    conn.commit()


@contextmanager
def exclusive_run(conn, label: str) -> Iterator[Callable[[], None]]:
    """Garante rodada unica. Entrega `beat()` para renovar o heartbeat (chame apos cada empresa, ja commitada)."""
    owner = uuid4().hex

    def beat() -> None:
        conn.execute("UPDATE run_lock SET heartbeat_at=? WHERE id=1 AND owner=?", (now(), owner))
        conn.commit()

    _acquire(conn, owner, label)
    try:
        yield beat
    finally:
        _release(conn, owner)


def force_release(conn) -> None:
    """Uso manual, quando se tem certeza de que nenhuma analise esta rodando (ex.: janela fechada no meio)."""
    conn.execute("DELETE FROM run_lock WHERE id=1")
    conn.commit()
