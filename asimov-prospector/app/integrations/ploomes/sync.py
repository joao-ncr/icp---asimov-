"""Sincronizacao Ploomes -> banco local do Prospector.

O CRM so e LIDO (client.py garante GET). Toda a leitura de rede acontece primeiro; depois as escritas vao para o
SQLite local, sem segurar lock durante a rede. Empresas sem site sao importadas com o site vazio (nunca descartadas).
Negocios de funis fora de config/ploomes.yaml sao ignorados e contados. Feedback humano, analises e calibracao nao
sao tocados; o historico comercial (lead_history) so recebe campos que o CRM informa (merge, nunca apaga)."""
from __future__ import annotations
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from app.core.settings import Settings
from app.core.utils import jdump, norm_name
from app.database.db import now
from app.database.run_lock import exclusive_run
from app.discovery.dedup import OrgIndex, upsert_org
from app.discovery.historical import suggested_service
from app.integrations.ploomes.client import ODataQuery, PloomesClient, PloomesContractError, PloomesError
from app.integrations.ploomes.mapping import (allowed_pipelines, company_from_api, company_query, deal_from_api, deal_query,
                                              forbidden_fields, resolve_field_keys, rules)
from app.integrations.ploomes.repository import last_successful_sync
from app.models.schemas import PloomesCompany, PloomesDeal

RUN_LABEL = "sincronizacao_ploomes"
STATUS_LABELS = {"open": "Em aberto", "won": "Ganha", "lost": "Perdida"}
HISTORY_COLUMNS = ("source_id", "segment_label", "registration_alert", "cnpj_suspect", "best_offer", "suggested_service",
                   "priority", "commercial_status", "loss_reason")


class SyncTooSoon(PloomesError):
    def __init__(self, seconds_left: int):
        self.seconds_left = seconds_left
        super().__init__(f"A última sincronização foi há pouco. Tente de novo em {seconds_left} s.")


@dataclass
class SyncReport:
    full_sync: bool = True
    companies: int = 0
    with_site: int = 0
    without_site: int = 0
    new_orgs: int = 0
    deals_won: int = 0
    deals_lost: int = 0
    deals_open: int = 0
    deals_ignored_pipeline: int = 0
    deals_without_company: int = 0
    replaced_spreadsheet_leads: int = 0


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _odata_ts(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seconds_until_allowed(last_finished_at: str | None, moment: datetime, interval_s: int) -> int:
    finished = _parse_ts(last_finished_at)
    if finished is None:
        return 0
    return max(0, int(interval_s - (moment - finished).total_seconds()))


def incremental_since(last: dict | None, overlap_hours: int) -> str | None:
    """None = sincronizacao completa (primeira vez). Senao, o cursor anterior menos a janela de sobreposicao."""
    cursor = _parse_ts((last or {}).get("cursor"))
    return _odata_ts(cursor - timedelta(hours=overlap_hours)) if cursor else None


def newest_update(rows: list[dict], previous: str | None) -> str | None:
    stamps = [ts for ts in (_parse_ts(r.get("LastUpdateDate")) for r in rows) if ts] + [ts for ts in [_parse_ts(previous)] if ts]
    return _odata_ts(max(stamps)) if stamps else None


def client_from_settings(settings: Settings) -> PloomesClient:
    api = rules()["api"]
    return PloomesClient(settings.ploomes_user_key, forbidden_fields(), page_size=api["page_size"], max_pages=api["max_pages"],
                         timeout_s=api["timeout_s"], max_retries=api["max_retries"])


def run_sync(conn: sqlite3.Connection, client: PloomesClient, triggered_by: str) -> SyncReport:
    """Ponto de entrada: respeita o intervalo minimo, a rodada unica e registra a trilha de auditoria."""
    api = rules()["api"]
    with exclusive_run(conn, RUN_LABEL):
        last = last_successful_sync(conn)
        wait = seconds_until_allowed((last or {}).get("finished_at"), datetime.now(timezone.utc), api["min_sync_interval_s"])
        if wait:
            raise SyncTooSoon(wait)
        since = incremental_since(last, api["incremental_overlap_hours"])
        sync_id = conn.execute("INSERT INTO ploomes_sync(started_at,status,full_sync,triggered_by) VALUES(?,?,?,?)",
                               (now(), "running", int(since is None), triggered_by)).lastrowid
        conn.commit()
        try:
            report, cursor = _sync(conn, client, since, (last or {}).get("cursor"))
        except (PloomesError, sqlite3.Error) as exc:
            conn.rollback()
            conn.execute("UPDATE ploomes_sync SET finished_at=?, status='error', error=? WHERE id=?", (now(), str(exc)[:300], sync_id))
            conn.commit()
            raise
        conn.execute("UPDATE ploomes_sync SET finished_at=?, status='ok', cursor=?, report=? WHERE id=?",
                     (now(), cursor, jdump(asdict(report)), sync_id))
        conn.commit()
    return report


def _check_pipelines(api_pipelines: list[dict]) -> None:
    names = {p["Id"]: (p.get("Name") or "").strip() for p in api_pipelines}
    wrong = [f"{pid} ({name})" for pid, name in allowed_pipelines().items() if names.get(pid) != name]
    if wrong:
        raise PloomesContractError(f"Funis configurados não conferem com o Ploomes: {', '.join(wrong)}")


def _sync(conn, client: PloomesClient, since: str | None, previous_cursor: str | None) -> tuple[SyncReport, str | None]:
    # 1) leitura (rede): nada e gravado antes de toda a leitura terminar
    contact_keys, deal_keys = resolve_field_keys(client.fetch_all(ODataQuery("Fields", ("Name", "Key", "EntityId"), "EntityId eq 1 or EntityId eq 2")))
    _check_pipelines(client.fetch_all(ODataQuery("Deals@Pipelines", ("Id", "Name"))))
    company_rows = client.fetch_all(company_query(contact_keys, since))
    deal_rows = client.fetch_all(deal_query(deal_keys, since))
    all_deals = client.count("Deals", f"LastUpdateDate ge {since}" if since else None)
    # 2) escrita local
    report = SyncReport(full_sync=since is None, deals_ignored_pipeline=max(0, all_deals - len(deal_rows)))
    _store_companies(conn, [company_from_api(r, contact_keys) for r in company_rows], report)
    _store_deals(conn, deal_rows, deal_keys, report)
    if report.full_sync:
        # O CRM passa a ser a fonte dos leads conhecidos: sai o que veio das planilhas (reimportavel; nao e feedback).
        report.replaced_spreadsheet_leads = conn.execute("DELETE FROM known_lead WHERE ploomes_deal_id IS NULL").rowcount
    conn.commit()
    return report, newest_update(company_rows + deal_rows, previous_cursor)


def _store_companies(conn, companies: list[PloomesCompany], report: SyncReport) -> None:
    index = OrgIndex.from_db(conn)
    for company in companies:
        org_id, is_new = upsert_org(conn, company.candidate, index)
        _fill_missing_org_fields(conn, org_id, company)
        conn.execute("""INSERT INTO ploomes_company(contact_id,org_id,last_update,synced_at) VALUES(?,?,?,?)
                        ON CONFLICT(contact_id) DO UPDATE SET org_id=excluded.org_id, last_update=excluded.last_update,
                        synced_at=excluded.synced_at""", (company.contact_id, org_id, company.last_update, now()))
        _merge_history(conn, org_id, {"source_id": company.contact_id, "segment_label": company.segment_label,
                                      "registration_alert": company.registration_alert,
                                      "cnpj_suspect": 1 if company.cnpj_suspect else None})
        report.companies += 1
        report.with_site += bool(company.candidate.domain)
        report.without_site += not company.candidate.domain
        report.new_orgs += is_new


def _fill_missing_org_fields(conn, org_id: int, company: PloomesCompany) -> None:
    """Completa so o que esta vazio; CNPJ apenas se nenhuma outra organizacao o usa (coluna UNIQUE)."""
    c = company.candidate
    conn.execute("""UPDATE organization SET municipio=COALESCE(municipio,?), uf=COALESCE(uf,?), segment=COALESCE(segment,?),
                    cnpj=COALESCE(cnpj, CASE WHEN EXISTS (SELECT 1 FROM organization x WHERE x.cnpj=? AND x.id<>?) THEN NULL ELSE ? END)
                    WHERE id=?""", (c.municipio, c.uf, c.segment, c.cnpj, org_id, c.cnpj, org_id))


def _merge_history(conn, org_id: int, values: dict) -> None:
    """Upsert em lead_history que so sobrescreve com valores informados (None mantem o que ja existia)."""
    present = {k: v for k, v in values.items() if v is not None}
    unknown = set(present) - set(HISTORY_COLUMNS)
    if unknown:
        raise ValueError(f"Colunas de histórico desconhecidas: {sorted(unknown)}")
    if not any(k != "source_id" for k in present):
        return
    cols = ["org_id", *present, "imported_at"]
    updates = ", ".join(f"{k}=excluded.{k}" for k in [*present, "imported_at"])
    conn.execute(f"INSERT INTO lead_history({','.join(cols)}) VALUES({','.join('?' * len(cols))}) ON CONFLICT(org_id) DO UPDATE SET {updates}",
                 (org_id, *present.values(), now()))


def _store_deals(conn, deal_rows: list[dict], deal_keys: dict[str, str], report: SyncReport) -> None:
    org_of = {r["contact_id"]: r["org_id"] for r in conn.execute("SELECT contact_id, org_id FROM ploomes_company")}
    for row in deal_rows:
        deal = deal_from_api(row, deal_keys)
        org_id = org_of.get(deal.company_contact_id) if deal else None
        if org_id is None:
            report.deals_without_company += 1
            continue
        setattr(report, f"deals_{deal.outcome}", getattr(report, f"deals_{deal.outcome}") + 1)
        _store_known_lead(conn, org_id, deal)
        _merge_history(conn, org_id, {"best_offer": deal.best_offer, "suggested_service": suggested_service(deal.best_offer),
                                      "priority": deal.priority, "segment_label": deal.segment_label, "loss_reason": deal.loss_reason,
                                      "commercial_status": " · ".join(x for x in (STATUS_LABELS[deal.outcome], deal.stage) if x)})


def _store_known_lead(conn, org_id: int, deal: PloomesDeal) -> None:
    """Ganhos/perdidos alimentam o anti-ICP (known_lead). Negocio reaberto sai da lista."""
    if deal.outcome == "open":
        conn.execute("DELETE FROM known_lead WHERE ploomes_deal_id=?", (deal.deal_id,))
        return
    org = conn.execute("SELECT name, domain, segment FROM organization WHERE id=?", (org_id,)).fetchone()
    conn.execute("""INSERT INTO known_lead(ploomes_deal_id,name,name_norm,domain,outcome,value,funnel,loss_reason,loss_category,segment,
                    is_person,created_month) VALUES(?,?,?,?,?,?,?,?,?,?,0,?)
                    ON CONFLICT(ploomes_deal_id) WHERE ploomes_deal_id IS NOT NULL DO UPDATE SET name=excluded.name,
                    name_norm=excluded.name_norm, domain=excluded.domain, outcome=excluded.outcome, value=excluded.value,
                    funnel=excluded.funnel, loss_reason=excluded.loss_reason, loss_category=excluded.loss_category,
                    segment=excluded.segment, created_month=excluded.created_month""",
                 (deal.deal_id, org["name"], norm_name(org["name"]), org["domain"], deal.outcome, deal.amount, deal.funnel,
                  deal.loss_reason, deal.loss_category, org["segment"] or "desconhecido", deal.created_month))
