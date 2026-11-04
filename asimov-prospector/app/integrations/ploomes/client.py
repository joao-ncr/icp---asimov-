"""Cliente da API do Ploomes ESTRITAMENTE SOMENTE LEITURA.

Duas barreiras independentes impedem qualquer escrita no CRM:
1. a classe so expoe leitura (`fetch_all`, `count`); nao ha metodo de escrita;
2. um gancho no transporte HTTP recusa, ANTES de abrir a rede, qualquer requisicao que nao seja GET ou que nao va
   para o host oficial da API.
A chave (header User-Key) nunca aparece em repr, mensagens de erro ou logs."""
from __future__ import annotations
import re
import time
from dataclasses import dataclass
from typing import Callable, Iterator
import httpx

API_HOST = "api2.ploomes.com"
BASE_URL = f"https://{API_HOST}/"
READ_METHOD = "GET"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
AUTH_STATUS = {401, 403}
MAX_BACKOFF_S = 8.0
ODATA_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class PloomesError(Exception):
    """Base dos erros da integracao. Mensagens nunca contem a chave."""


class WriteForbidden(PloomesError):
    """Tentativa de requisicao que nao e leitura (ou para outro host). A integracao e somente leitura."""


class ForbiddenField(PloomesError):
    """Consulta pede um campo proibido (dado pessoal) ou campos personalizados sem filtro."""


class PloomesAuthError(PloomesError):
    """Chave ausente, invalida ou sem permissao."""


class PloomesUnavailable(PloomesError):
    """API fora do ar ou limitando requisicoes, mesmo apos as novas tentativas."""


class PloomesContractError(PloomesError):
    """Resposta fora do formato esperado ou consulta recusada pela API."""


@dataclass(frozen=True)
class ODataQuery:
    entity: str
    select: tuple[str, ...]
    filter: str | None = None
    expand: str | None = None
    order_by: str = "Id"

    def params(self) -> dict[str, str]:
        params = {"$select": ",".join(self.select), "$orderby": self.order_by}
        if self.filter:
            params["$filter"] = self.filter
        if self.expand:
            params["$expand"] = self.expand
        return params


def _read_only_guard(request: httpx.Request) -> None:
    if request.method != READ_METHOD:
        raise WriteForbidden(f"Integração somente leitura: método {request.method} recusado.")
    if request.url.host != API_HOST:
        raise WriteForbidden(f"Integração restrita a {API_HOST}: host {request.url.host} recusado.")


def validate_query(query: ODataQuery, forbidden_fields: frozenset[str]) -> None:
    """Recusa a consulta antes da rede se pedir dado pessoal ou campos personalizados sem filtro explicito."""
    requested = set(query.select) | set(ODATA_IDENTIFIER.findall(query.expand or ""))
    blocked = sorted(requested & forbidden_fields)
    if blocked:
        raise ForbiddenField(f"Campos proibidos na consulta a {query.entity}: {', '.join(blocked)}")
    if "OtherProperties" in (query.expand or "") and "$filter=" not in query.expand:
        raise ForbiddenField("OtherProperties só pode ser lido com $filter por FieldKey (evita trazer dados pessoais).")


class PloomesClient:
    def __init__(self, user_key: str, forbidden_fields: frozenset[str], *, page_size: int = 300, max_pages: int = 100,
                 timeout_s: float = 30, max_retries: int = 3, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        if not user_key:
            raise PloomesAuthError("Chave do Ploomes não configurada (PLOOMES_USER_KEY).")
        self._forbidden = forbidden_fields
        self._page_size, self._max_pages, self._max_retries, self._sleep = page_size, max_pages, max_retries, sleep
        self._http = httpx.Client(base_url=BASE_URL, headers={"User-Key": user_key, "Accept": "application/json"},
                                  timeout=timeout_s, follow_redirects=False, transport=transport,
                                  event_hooks={"request": [_read_only_guard]})

    def __repr__(self) -> str:
        return f"PloomesClient(host={API_HOST!r})"

    def __enter__(self) -> "PloomesClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def fetch_all(self, query: ODataQuery) -> list[dict]:
        return [row for page in self._pages(query) for row in page]

    def count(self, entity: str, filter: str | None = None) -> int:
        params = {"$top": "1", "$count": "true", "$select": "Id"}
        if filter:
            params["$filter"] = filter
        body = self._get(entity, params)
        total = body.get("@odata.count")
        if not isinstance(total, int):
            raise PloomesContractError(f"Resposta de {entity} sem contagem.")
        return total

    def _pages(self, query: ODataQuery) -> Iterator[list[dict]]:
        validate_query(query, self._forbidden)
        for page in range(self._max_pages):
            # Paginacao propria por $skip: nunca seguimos links devolvidos pela API.
            rows = self._get(query.entity, {**query.params(), "$top": str(self._page_size), "$skip": str(page * self._page_size)})["value"]
            yield rows
            if len(rows) < self._page_size:
                return
        raise PloomesContractError(f"{query.entity}: mais de {self._max_pages} páginas; limite de segurança atingido.")

    def _get(self, entity: str, params: dict[str, str]) -> dict:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.get(entity, params=params)
            except httpx.TransportError as exc:
                failure = f"falha de rede ({type(exc).__name__})"
            else:
                if response.status_code not in RETRYABLE_STATUS:
                    return _parse(entity, response)
                failure = f"HTTP {response.status_code}"
            if attempt < self._max_retries:
                self._sleep(min(2 ** attempt, MAX_BACKOFF_S))
        raise PloomesUnavailable(f"Ploomes indisponível em {entity}: {failure}.")


def _parse(entity: str, response: httpx.Response) -> dict:
    if response.status_code in AUTH_STATUS:
        raise PloomesAuthError(f"Ploomes recusou a chave em {entity} (HTTP {response.status_code}).")
    if response.status_code != 200:
        raise PloomesContractError(f"Ploomes respondeu HTTP {response.status_code} em {entity}.")
    try:
        body = response.json()
    except ValueError as exc:
        raise PloomesContractError(f"Resposta de {entity} não é JSON.") from exc
    if not isinstance(body, dict) or not isinstance(body.get("value"), list):
        raise PloomesContractError(f"Resposta de {entity} sem a lista 'value'.")
    return body
