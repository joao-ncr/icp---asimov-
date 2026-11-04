"""Migracoes ADITIVAS e idempotentes para bancos criados por versoes anteriores.

So adicionam colunas/indices: nunca apagam nem reescrevem dados, entao o codigo antigo continua lendo o banco
(rollback = voltar a versao do codigo). Tabelas novas ficam em schema.sql (CREATE TABLE IF NOT EXISTS)."""
from __future__ import annotations
import re
import sqlite3

SQL_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
ADDED_COLUMNS = [("known_lead", "ploomes_deal_id", "INTEGER")]
INDEXES = ["CREATE UNIQUE INDEX IF NOT EXISTS ux_known_lead_ploomes_deal ON known_lead(ploomes_deal_id) WHERE ploomes_deal_id IS NOT NULL"]


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, sql_type: str) -> bool:
    if not (SQL_IDENTIFIER.match(table) and SQL_IDENTIFIER.match(column) and SQL_IDENTIFIER.match(sql_type.lower())):
        raise ValueError(f"Identificador SQL inválido: {table}.{column} {sql_type}")
    if column in _columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    return True


def apply_migrations(conn: sqlite3.Connection) -> None:
    for table, column, sql_type in ADDED_COLUMNS:
        add_column_if_missing(conn, table, column, sql_type)
    for statement in INDEXES:
        conn.execute(statement)
    conn.commit()
