"""Cliente Ploomes: somente leitura garantido por codigo, chave nunca exposta, campos pessoais recusados, resiliencia."""
import re
from pathlib import Path
import httpx
import pytest
from app.integrations.ploomes import client as client_mod
from app.integrations.ploomes.client import (API_HOST, ForbiddenField, ODataQuery, PloomesAuthError, PloomesClient,
                                             PloomesContractError, PloomesUnavailable, WriteForbidden)
from app.integrations.ploomes.mapping import company_query, deal_query, forbidden_fields

SECRET = "CHAVE-SECRETA-DE-TESTE-0123456789"
PACKAGE = Path(client_mod.__file__).parent


class Recorder:
    """Transporte falso: registra cada requisicao que de fato chegaria a rede."""

    def __init__(self, responder):
        self.requests: list[httpx.Request] = []
        self.responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request)


def _ok(rows=None, **extra):
    return lambda request: httpx.Response(200, json={"value": rows if rows is not None else [], **extra})


def _client(responder, **kw) -> tuple[PloomesClient, Recorder]:
    rec = Recorder(responder)
    return PloomesClient(SECRET, forbidden_fields(), transport=httpx.MockTransport(rec), sleep=lambda s: None, **kw), rec


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_write_methods_are_refused_before_reaching_the_network(method):
    client, rec = _client(_ok())
    with pytest.raises(WriteForbidden):
        client._http.request(method, "Contacts", json={"Name": "x"})
    assert rec.requests == []                       # nada saiu para a rede


def test_other_hosts_are_refused():
    client, rec = _client(_ok())
    with pytest.raises(WriteForbidden):
        client._http.get("https://example.com/Contacts")
    assert rec.requests == []


def test_client_exposes_no_write_operation():
    public = {name for name in dir(PloomesClient) if not name.startswith("_")}
    assert public == {"fetch_all", "count", "close"}


def test_integration_source_has_no_write_call():
    """Barreira estatica: nenhum arquivo da integracao chama verbos de escrita ou operacoes em lote."""
    forbidden = re.compile(r"\.(post|put|patch|delete)\(|\$batch|method\s*=\s*['\"](POST|PUT|PATCH|DELETE)", re.I)
    offenders = [p.name for p in PACKAGE.glob("*.py") if forbidden.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_queries_used_by_the_sync_only_send_get():
    client, rec = _client(_ok([{"Id": 1}], **{"@odata.count": 1}))
    client.fetch_all(company_query({"registration_alert": "contact_X"}))
    client.fetch_all(deal_query({"best_offer": "deal_A", "priority": "deal_B", "segment": "deal_C"}))
    client.count("Deals")
    assert {r.method for r in rec.requests} == {"GET"} and {r.url.host for r in rec.requests} == {API_HOST}


def test_key_goes_only_in_the_header_and_never_in_repr_or_errors():
    client, rec = _client(lambda r: httpx.Response(401, json={"error": "unauthorized"}))
    with pytest.raises(PloomesAuthError) as err:
        client.fetch_all(ODataQuery("Contacts", ("Id",)))
    assert rec.requests[0].headers["User-Key"] == SECRET
    assert SECRET not in str(rec.requests[0].url)
    assert SECRET not in str(err.value) and SECRET not in repr(client)


def test_missing_key_is_an_explicit_error():
    with pytest.raises(PloomesAuthError):
        PloomesClient("", forbidden_fields())


@pytest.mark.parametrize("query", [
    ODataQuery("Contacts", ("Id", "Phones")),
    ODataQuery("Contacts", ("Id", "Email")),
    ODataQuery("Deals", ("Id",), expand="Contact($select=Id,Birthday)"),
    ODataQuery("Contacts", ("Id",), expand="OtherProperties($select=FieldKey,StringValue)"),     # sem filtro: traria tudo
])
def test_personal_data_queries_are_refused_before_the_network(query):
    client, rec = _client(_ok())
    with pytest.raises(ForbiddenField):
        client.fetch_all(query)
    assert rec.requests == []


def test_paginates_with_own_skip_until_a_short_page():
    pages = {0: [{"Id": i} for i in range(3)], 3: [{"Id": i} for i in range(3, 6)], 6: [{"Id": 6}]}
    client, rec = _client(lambda r: httpx.Response(200, json={"value": pages[int(r.url.params["$skip"])],
                                                                 "@odata.nextLink": "https://evil.example/next"}), page_size=3)
    rows = client.fetch_all(ODataQuery("Contacts", ("Id",)))
    assert [r["Id"] for r in rows] == list(range(7))
    assert len(rec.requests) == 3 and all(r.url.host == API_HOST for r in rec.requests)    # nextLink ignorado


def test_page_limit_is_enforced():
    client, _ = _client(_ok([{"Id": 1}, {"Id": 2}]), page_size=2, max_pages=3)
    with pytest.raises(PloomesContractError):
        client.fetch_all(ODataQuery("Contacts", ("Id",)))


def test_retries_rate_limit_and_server_errors_with_backoff():
    answers = iter([httpx.Response(429), httpx.Response(503), httpx.Response(200, json={"value": [{"Id": 9}]})])
    waits: list[float] = []
    rec = Recorder(lambda r: next(answers))
    client = PloomesClient(SECRET, forbidden_fields(), transport=httpx.MockTransport(rec), sleep=waits.append)
    assert client.fetch_all(ODataQuery("Contacts", ("Id",))) == [{"Id": 9}]
    assert waits == [1, 2]


def test_gives_up_after_bounded_retries():
    client, rec = _client(lambda r: httpx.Response(503), max_retries=2)
    with pytest.raises(PloomesUnavailable):
        client.fetch_all(ODataQuery("Contacts", ("Id",)))
    assert len(rec.requests) == 3


def test_network_failure_becomes_unavailable_not_a_crash():
    def broken(request):
        raise httpx.ConnectError("sem rede", request=request)
    client, _ = _client(broken, max_retries=1)
    with pytest.raises(PloomesUnavailable):
        client.fetch_all(ODataQuery("Contacts", ("Id",)))


@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>erro</html>"), httpx.Response(200, json={"data": []}),
                                      httpx.Response(400, json={"error": "bad"})])
def test_unexpected_responses_are_contract_errors(response):
    client, _ = _client(lambda r: response)
    with pytest.raises(PloomesContractError):
        client.fetch_all(ODataQuery("Contacts", ("Id",)))


def test_auth_errors_are_not_retried():
    client, rec = _client(lambda r: httpx.Response(403))
    with pytest.raises(PloomesAuthError):
        client.count("Deals")
    assert len(rec.requests) == 1
