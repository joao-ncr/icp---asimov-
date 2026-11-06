"""Sincronizacao Ploomes -> banco local contra um Ploomes falso (MockTransport), sem rede.

O servidor falso devolve de proposito dados pessoais e campos nao pedidos (como se ignorasse $select): nada disso
pode chegar ao banco. Tambem cobre: so GET, empresas sem site preservadas, funis ignorados, idempotencia/incremental,
preservacao de feedback/historico, falha sem escrita parcial e o caminho ate a analise."""
import re
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from app.core.settings import ROOT, get_settings
from app.core.utils import norm_name
from app.discovery.dedup import upsert_org
from app.integrations.ploomes import repository as repo
from app.integrations.ploomes.client import API_HOST, PloomesClient, PloomesContractError, PloomesUnavailable
from app.integrations.ploomes.mapping import custom_value, forbidden_fields, loss_category
from app.integrations.ploomes.sync import SyncTooSoon, run_sync, seconds_until_allowed, sync_is_due
from app.models.schemas import Candidate
from app.pipeline import FixtureSource, run_pipeline

PIPELINES = [{"Id": 37801, "Name": "Funil Ativa"}, {"Id": 52351, "Name": "Funil Passivo"},
             {"Id": 52763, "Name": "Funil Tráfego Pago"}, {"Id": 52822, "Name": "Listas de prospecção"}]
FIELDS = [{"Name": "Alerta de Cadastro", "Key": "c_alert", "EntityId": 1}, {"Name": "Decisor a Abordar", "Key": "c_decisor", "EntityId": 1},
          {"Name": "Melhor Oferta", "Key": "d_offer", "EntityId": 2}, {"Name": "Prioridade revisada", "Key": "d_prio", "EntityId": 2},
          {"Name": "Segmento", "Key": "d_seg", "EntityId": 2}, {"Name": "Telefone", "Key": "d_tel", "EntityId": 2}]
PERSONAL = {"Phones": [{"PhoneNumber": "(35) 99876-5432"}], "Email": "dono.pessoal@gmail.com", "CPF": "123.456.789-00"}
LEAKED_PROPS = [{"FieldKey": "c_decisor", "StringValue": "Fulano de Tal (decisor)"}, {"FieldKey": "d_tel", "StringValue": "(35) 3622-1111"}]


def _company(cid, name, site, alert=None, cnpj=None, city="ITAJUBÁ", lob="Indústria", updated="2026-10-01T10:00:00-03:00"):
    props = LEAKED_PROPS + ([{"FieldKey": "c_alert", "StringValue": alert}] if alert else [])
    return {"Id": cid, "Name": name, "Website": site, "CNPJ": cnpj, "TypeId": 1, "LastUpdateDate": updated,
            "City": {"Name": city}, "State": {"Short": "MG"}, "LineOfBusiness": {"Name": lob}, "OtherProperties": props, **PERSONAL}


def _deal(did, contact, status, pipeline=37801, reason=None, offer=None, updated="2026-10-02T10:00:00-03:00", person=False):
    props = LEAKED_PROPS + ([{"FieldKey": "d_offer", "StringValue": offer}] if offer else []) + [{"FieldKey": "d_prio", "ObjectValueName": "Alta"}]
    contact_obj = {"Id": 900, "TypeId": 2, "CompanyId": None} if person else {"Id": contact, "TypeId": 1, "CompanyId": None}
    return {"Id": did, "ContactId": contact_obj["Id"], "PipelineId": pipeline, "StageId": 1, "StatusId": status, "Amount": 5000.0,
            "CreateDate": "2026-09-15T10:00:00-03:00", "LastUpdateDate": updated, "Contact": contact_obj,
            "Stage": {"Name": "Negociação"}, "LossReason": {"Name": reason} if reason else None, "OtherProperties": props}


COMPANIES = [
    _company(101, "Alfa Manutencao Industrial", "https://www.manutencao-sul.example/"),
    _company(102, "Beta Sem Site", None),
    _company(103, "Gama Só Instagram", "https://instagram.com/gama"),
    _company(104, "Delta Cliente", "https://delta-cliente.example", alert="ATENCAO: CNPJ pode ser de outra empresa", cnpj="12.345.678/0001-90"),
]
DEALS = [
    _deal(201, 104, 2),
    _deal(202, 101, 3, reason="Não é prioridade", offer="Sites"),
    _deal(203, 103, 3, reason="ESTÁ FORA DO ICP"),
    _deal(204, None, 3, reason="Não respondeu", person=True),
    _deal(205, 101, 1, pipeline=52822),
    _deal(206, 102, 3, reason=None),
]
ALL_DEALS_COUNT = len(DEALS) + 1          # +1 negocio de funil fora da lista (o servidor ja o filtra)


class FakePloomes:
    def __init__(self, fail_on: str | None = None, pipelines=PIPELINES):
        self.requests: list[httpx.Request] = []
        self.fail_on, self.pipelines = fail_on, pipelines

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, params = request.url.path.strip("/"), request.url.params
        if path == self.fail_on:
            return httpx.Response(500)
        if params.get("$count") == "true":
            return httpx.Response(200, json={"value": [{"Id": 1}], "@odata.count": ALL_DEALS_COUNT})
        if int(params.get("$skip", "0")) > 0:
            return httpx.Response(200, json={"value": []})
        incremental = "LastUpdateDate ge" in params.get("$filter", "")
        rows = {"Fields": FIELDS, "Deals@Pipelines": self.pipelines, "Contacts": [] if incremental else COMPANIES,
                "Deals": [] if incremental else DEALS}[path]
        return httpx.Response(200, json={"value": rows})


def _client(fake: FakePloomes) -> PloomesClient:
    return PloomesClient("chave-de-teste", forbidden_fields(), transport=httpx.MockTransport(fake), sleep=lambda s: None)


def _sync(conn, fake=None):
    fake = fake or FakePloomes()
    return run_sync(conn, _client(fake), "teste"), fake


def _allow_next_sync(conn):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    conn.execute("UPDATE ploomes_sync SET finished_at=?", (past,))
    conn.commit()


def _org(conn, name):
    return conn.execute("SELECT * FROM organization WHERE name=?", (name,)).fetchone()


def test_sync_reads_only_with_get_on_the_official_host(conn):
    _, fake = _sync(conn)
    assert fake.requests and {r.method for r in fake.requests} == {"GET"}
    assert {r.url.host for r in fake.requests} == {API_HOST}


def test_companies_without_site_are_kept_with_empty_site(conn):
    report, _ = _sync(conn)
    assert (report.companies, report.with_site, report.without_site) == (4, 2, 2)
    assert _org(conn, "Beta Sem Site")["domain"] is None
    assert _org(conn, "Gama Só Instagram")["domain"] is None          # rede social nao identifica empresa
    assert _org(conn, "Alfa Manutencao Industrial")["domain"] == "manutencao-sul.example"
    assert _org(conn, "Alfa Manutencao Industrial")["municipio"] == "Itajubá"
    assert conn.execute("SELECT COUNT(*) FROM ploomes_company").fetchone()[0] == 4


def test_deals_feed_known_leads_with_loss_categories(conn):
    report, _ = _sync(conn)
    leads = {r["ploomes_deal_id"]: dict(r) for r in conn.execute("SELECT * FROM known_lead")}
    assert leads[201]["outcome"] == "won" and leads[201]["domain"] == "delta-cliente.example"
    assert leads[202]["loss_category"] == "not_priority"
    assert leads[203]["loss_category"] == "outside_icp"                # acento e caixa nao importam
    assert leads[206]["loss_category"] == "other"                      # sem motivo nao exclui
    assert 205 not in leads                                            # negocio em aberto nao e lead conhecido
    assert (report.deals_won, report.deals_lost, report.deals_open) == (1, 3, 1)
    assert report.deals_without_company == 1 and report.deals_ignored_pipeline == 1


def test_no_personal_data_reaches_the_database(conn):
    _sync(conn)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    dump = " ".join(str(v) for t in tables for row in conn.execute(f"SELECT * FROM {t}") for v in row if v is not None)
    assert "@" not in dump.replace("@odata", "")
    assert not re.search(r"\(\d{2}\)\s?\d{4,5}-\d{4}", dump)
    assert "Fulano" not in dump and "123.456.789" not in dump
    assert _org(conn, "Delta Cliente")["cnpj"] is None                # alerta de cadastro: CNPJ nao vira identidade


def test_crm_context_is_merged_without_erasing_history_or_feedback(conn):
    org_id, _ = upsert_org(conn, Candidate(name="Alfa Manutencao Industrial", domain="manutencao-sul.example"))
    conn.execute("INSERT INTO lead_history(org_id,capital_social,best_offer,legacy_score) VALUES(?,?,?,?)", (org_id, 1000.0, "Mobile", 71.0))
    conn.execute("INSERT INTO human_feedback(org_id,analysis_id,quality,created_at) VALUES(?,1,'boa','x')", (org_id,))
    conn.execute("INSERT INTO known_lead(name,name_norm,outcome,is_person) VALUES('Planilha Antiga',?, 'lost', 0)", (norm_name("Planilha Antiga"),))
    conn.commit()
    report, _ = _sync(conn)
    h = conn.execute("SELECT * FROM lead_history WHERE org_id=?", (org_id,)).fetchone()
    assert (h["capital_social"], h["legacy_score"]) == (1000.0, 71.0)          # o que o CRM nao informa e mantido
    assert h["best_offer"] == "Sites" and h["suggested_service"] == "site" and h["priority"] == "Alta"
    assert conn.execute("SELECT COUNT(*) FROM human_feedback").fetchone()[0] == 1
    assert report.replaced_spreadsheet_leads == 1                              # CRM substitui os leads da planilha


def test_second_sync_is_throttled_then_incremental_and_idempotent(conn):
    _sync(conn)
    with pytest.raises(SyncTooSoon):
        _sync(conn)
    counts = lambda: conn.execute("SELECT (SELECT COUNT(*) FROM organization),(SELECT COUNT(*) FROM known_lead),(SELECT COUNT(*) FROM lead_history)").fetchone()
    before = tuple(counts())
    _allow_next_sync(conn)
    report, fake = _sync(conn)
    assert not report.full_sync
    assert any("LastUpdateDate ge" in r.url.params.get("$filter", "") for r in fake.requests)
    assert tuple(counts()) == before


def test_full_resync_does_not_duplicate(conn):
    _sync(conn)
    before = conn.execute("SELECT (SELECT COUNT(*) FROM organization),(SELECT COUNT(*) FROM known_lead)").fetchone()
    conn.execute("DELETE FROM ploomes_sync")          # simula sincronizacao completa de novo
    conn.commit()
    _sync(conn)
    assert tuple(conn.execute("SELECT (SELECT COUNT(*) FROM organization),(SELECT COUNT(*) FROM known_lead)").fetchone()) == tuple(before)


def test_api_failure_writes_nothing_and_is_audited(conn):
    with pytest.raises(PloomesUnavailable):
        _sync(conn, FakePloomes(fail_on="Deals"))
    assert conn.execute("SELECT COUNT(*) FROM ploomes_company").fetchone()[0] == 0
    row = conn.execute("SELECT status, error, triggered_by FROM ploomes_sync").fetchone()
    assert row["status"] == "error" and "Deals" in row["error"] and row["triggered_by"] == "teste"
    assert conn.execute("SELECT COUNT(*) FROM run_lock").fetchone()[0] == 0            # trava liberada


def test_pipeline_drift_is_an_explicit_error(conn):
    renamed = [dict(p, Name="Outro nome") if p["Id"] == 37801 else p for p in PIPELINES]
    with pytest.raises(PloomesContractError):
        _sync(conn, FakePloomes(pipelines=renamed))


def test_pending_candidates_put_companies_with_site_first(conn):
    _sync(conn)
    names = [c.name for c in repo.pending_candidates(conn, 10)]
    assert set(names[:2]) == {"Alfa Manutencao Industrial", "Delta Cliente"}
    assert set(names[2:]) == {"Beta Sem Site", "Gama Só Instagram"}
    assert repo.summary(conn)["pending_without_site"] == 2


def test_analysis_of_crm_companies_never_drops_companies_without_site(conn):
    _sync(conn)
    run_pipeline(conn, repo.pending_candidates(conn, 10), FixtureSource(ROOT / "tests" / "fixtures" / "sites"), get_settings())
    status = {r["name"]: (r["status"], r["reason"]) for r in conn.execute(
        "SELECT o.name, a.status, a.reason FROM analysis a JOIN organization o ON o.id=a.org_id")}
    assert status["Beta Sem Site"][0] == "inconclusive" and status["Beta Sem Site"][1].startswith("no_domain")
    assert status["Delta Cliente"] == ("excluded", "ja e cliente")              # anti-ICP alimentado pelo CRM
    assert status["Gama Só Instagram"] == ("excluded", "lead anterior perdido: outside_icp")
    assert status["Alfa Manutencao Industrial"][0] == "ranked"
    assert repo.summary(conn)["pending_without_site"] == 0 and repo.pending_candidates(conn, 10) == []


@pytest.mark.parametrize("reason, category", [("Não é prioridade", "not_priority"), ("nao e prioridade", "not_priority"),
                                              ("Timing / Prioridade", "not_priority"), ("Lead desqualificado", "disqualified"),
                                              ("Contratou concorrente", "other"), (None, "other")])
def test_loss_reasons_map_by_name(reason, category):
    assert loss_category(reason) == category


def test_custom_value_reads_only_the_requested_field():
    row = {"OtherProperties": LEAKED_PROPS + [{"FieldKey": "c_alert", "BigStringValue": " alerta "}]}
    assert custom_value(row, "c_alert") == "alerta"
    assert custom_value(row, "inexistente") is None


def test_sync_interval_math():
    moment = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    assert seconds_until_allowed(None, moment, 300) == 0
    assert seconds_until_allowed("2026-11-04T11:58:00+00:00", moment, 300) == 180
    assert seconds_until_allowed("2026-11-04T11:00:00+00:00", moment, 300) == 0


def test_auto_sync_runs_when_never_synced_or_stale():
    moment = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    assert sync_is_due(None, moment, 12)
    assert sync_is_due({"finished_at": "2026-11-05T23:00:00+00:00"}, moment, 12)
    assert not sync_is_due({"finished_at": "2026-11-06T09:00:00+00:00"}, moment, 12)
