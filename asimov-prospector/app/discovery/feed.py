"""Busca a lista mensal de CNPJ do ICP, publicada pelo GitHub Actions (app/discovery/receita_feed.py) como release do
repositorio privado. So leitura: GETs na API do GitHub com token somente leitura (CNPJ_FEED_TOKEN). Host fixo e tamanho
limitado - nenhuma URL vem do usuario, entao nao ha superficie de SSRF."""
from __future__ import annotations
from dataclasses import dataclass
import httpx
from app.core.settings import Settings

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
TIMEOUT_S = 30
BYTES_PER_MB = 1_000_000
DEFAULT_MAX_MB = 50
NOT_PUBLISHED = "A lista de CNPJ ainda não foi publicada. No GitHub, rode o workflow 'Lista de CNPJ (Receita)' (aba Actions)."


class FeedError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeedFile:
    label: str          # vai para a trilha de auditoria (discovery_generation.filename)
    content: bytes


def is_configured(settings: Settings, feed_cfg: dict | None) -> bool:
    return bool(settings.cnpj_feed_token and feed_cfg and feed_cfg.get("repo"))


def find_asset(release: dict, asset_name: str) -> dict:
    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            return asset
    raise FeedError(NOT_PUBLISHED)


def fetch_latest(settings: Settings, feed_cfg: dict | None, transport: httpx.BaseTransport | None = None) -> FeedFile:
    if not is_configured(settings, feed_cfg):
        raise FeedError("Busca automática não configurada: defina CNPJ_FEED_TOKEN no .env (ver README).")
    max_bytes = int(feed_cfg.get("max_mb", DEFAULT_MAX_MB) * BYTES_PER_MB)
    headers = {"Authorization": f"Bearer {settings.cnpj_feed_token}", "X-GitHub-Api-Version": GITHUB_API_VERSION,
               "User-Agent": settings.user_agent}
    try:
        # O download do asset redireciona para outro host; o httpx descarta o Authorization nesse redirecionamento.
        with httpx.Client(base_url=GITHUB_API, headers=headers, timeout=TIMEOUT_S, follow_redirects=True,
                          transport=transport) as client:
            release = _get_json(client, f"/repos/{feed_cfg['repo']}/releases/tags/{feed_cfg['release_tag']}")
            asset = find_asset(release, feed_cfg["asset"])
            if asset.get("size", 0) > max_bytes:
                raise FeedError(f"A lista publicada passa de {feed_cfg.get('max_mb', DEFAULT_MAX_MB)} MB; revise os ICPs.")
            content = _download(client, asset["url"], max_bytes)
    except httpx.HTTPError as exc:
        raise FeedError(f"Sem conexão com o GitHub para buscar a lista de CNPJ ({exc.__class__.__name__}).") from exc
    return FeedFile(label=f"{asset['name']} (publicada em {asset.get('updated_at', '?')})", content=content)


def _get_json(client: httpx.Client, path: str) -> dict:
    response = client.get(path, headers={"Accept": "application/vnd.github+json"})
    _raise_for_status(response)
    return response.json()


def _download(client: httpx.Client, url: str, max_bytes: int) -> bytes:
    chunks, size = [], 0
    with client.stream("GET", url, headers={"Accept": "application/octet-stream"}) as response:
        _raise_for_status(response)
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise FeedError("A lista publicada é maior que o limite configurado (feed.max_mb).")
            chunks.append(chunk)
    return b"".join(chunks)


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        raise FeedError("Token do GitHub inválido ou sem acesso ao repositório (CNPJ_FEED_TOKEN).")
    if response.status_code == httpx.codes.NOT_FOUND:
        raise FeedError(NOT_PUBLISHED)
    if response.is_error:
        raise FeedError(f"O GitHub respondeu {response.status_code} ao buscar a lista de CNPJ.")
