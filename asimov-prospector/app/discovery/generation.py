"""Geracao de leads novos a partir de dados abertos de CNPJ (Receita), filtrados por ICP (config/icp.yaml).

O CSV e enviado pelo admin na tela (sem rede externa). Os candidatos NUNCA viram organizacao sozinhos: ficam
pendentes em discovery_candidate ate um humano aprovar (ver app/discovery/review.py). Sem cron real: o Streamlit
Community Cloud nao tem processo de fundo, entao "agendamento" e so uma trava de intervalo minimo entre geracoes -
mesmo espirito da sincronizacao do Ploomes (app/integrations/ploomes/sync.py), sem acoplar os dois modulos."""
from __future__ import annotations
import csv
import io
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from app.core.settings import get_settings
from app.core.utils import jdump, load_yaml, norm_name
from app.database.db import now
from app.database.run_lock import exclusive_run
from app.discovery.dedup import OrgIndex
from app.discovery.sources import candidates_from_cnpj_rows

RUN_LABEL = "geracao_leads"


class GenerationError(RuntimeError):
    pass


class GenerationTooSoon(GenerationError):
    def __init__(self, seconds_left: int):
        self.seconds_left = seconds_left
        super().__init__(f"A última geração foi há pouco. Tente de novo em {seconds_left} s.")


@dataclass
class GenerationReport:
    rows_total: int = 0
    matched: int = 0
    duplicates: int = 0
    skipped_without_cnpj: int = 0
    new_candidates: int = 0


@lru_cache
def rules() -> dict:
    return load_yaml(get_settings().config_dir / "icp.yaml")


def seconds_until_allowed(last_finished_at: str | None, moment: datetime, interval_s: int) -> int:
    if not last_finished_at:
        return 0
    try:
        finished = datetime.fromisoformat(last_finished_at)
    except ValueError:
        return 0
    finished = finished if finished.tzinfo else finished.replace(tzinfo=timezone.utc)
    return max(0, int(interval_s - (moment - finished).total_seconds()))


def last_successful_generation(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM discovery_generation WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def last_generation(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM discovery_generation ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def _read_rows(csv_file) -> list[dict]:
    text = csv_file if isinstance(csv_file, io.TextIOBase) else io.TextIOWrapper(csv_file, encoding="utf-8-sig")
    return list(csv.DictReader(text))


def _known_cnpjs(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT cnpj FROM discovery_candidate WHERE cnpj IS NOT NULL")}


def run_generation(conn: sqlite3.Connection, csv_file, filename: str, triggered_by: str) -> GenerationReport:
    """Ponto de entrada: respeita o intervalo minimo e a rodada unica, e registra a trilha de auditoria."""
    cfg = rules()
    with exclusive_run(conn, RUN_LABEL):
        last = last_successful_generation(conn)
        wait = seconds_until_allowed((last or {}).get("finished_at"), datetime.now(timezone.utc),
                                     cfg["min_generation_interval_hours"] * 3600)
        if wait:
            raise GenerationTooSoon(wait)
        generation_id = conn.execute("INSERT INTO discovery_generation(started_at,status,triggered_by,filename) VALUES(?,?,?,?)",
                                     (now(), "running", triggered_by, filename)).lastrowid
        conn.commit()
        try:
            report = _generate(conn, csv_file, cfg, generation_id)
        except Exception as exc:
            conn.rollback()
            conn.execute("UPDATE discovery_generation SET finished_at=?, status='error', error=? WHERE id=?",
                         (now(), str(exc)[:300], generation_id))
            conn.commit()
            raise
        conn.execute("UPDATE discovery_generation SET finished_at=?, status='ok', report=? WHERE id=?",
                     (now(), jdump(asdict(report)), generation_id))
        conn.commit()
    return report


def _rationale(icp: dict) -> str:
    parts = [f"ICP: {icp['name']}", f"CNAE {', '.join(icp['cnae_prefixes'])}"]
    if icp.get("uf"):
        parts.append(f"UF {icp['uf']}")
    return " · ".join(parts)


def _generate(conn: sqlite3.Connection, csv_file, cfg: dict, generation_id: int) -> GenerationReport:
    rows = _read_rows(csv_file)
    limit = cfg.get("max_candidates_per_run", 500)
    org_index = OrgIndex.from_db(conn)
    seen_cnpjs = _known_cnpjs(conn)
    report = GenerationReport(rows_total=len(rows))
    for icp in cfg["icps"]:
        matched = candidates_from_cnpj_rows(rows, icp["cnae_prefixes"], icp.get("uf"), icp.get("municipios"), limit)
        report.matched += len(matched)
        rationale = _rationale(icp)
        for candidate in matched:
            if not candidate.cnpj:
                report.skipped_without_cnpj += 1
                continue
            candidate.segment = icp.get("segment") or candidate.segment
            if candidate.cnpj in seen_cnpjs or org_index.find(candidate):
                report.duplicates += 1
                seen_cnpjs.add(candidate.cnpj)
                continue
            inserted = conn.execute(
                """INSERT OR IGNORE INTO discovery_candidate(generation_id,name,name_norm,cnpj,cnae,uf,municipio,porte,
                   segment,icp_id,rationale,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,'pending',?)""",
                (generation_id, candidate.name, norm_name(candidate.name), candidate.cnpj, candidate.cnae, candidate.uf,
                 candidate.municipio, candidate.porte, candidate.segment, icp["id"], rationale, now()))
            report.new_candidates += bool(inserted.rowcount)
            report.duplicates += not inserted.rowcount
            seen_cnpjs.add(candidate.cnpj)
    conn.commit()
    return report
