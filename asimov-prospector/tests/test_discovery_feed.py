"""Busca da lista mensal de CNPJ publicada como release do GitHub (app/discovery/feed.py), contra um GitHub falso
(MockTransport), sem rede. Cobre o caminho feliz, configuracao ausente, erros de acesso e o limite de tamanho."""
import httpx
import pytest
from app.core.settings import Settings
from app.discovery import feed

FEED_CFG = {"repo": "asimov/prospector", "release_tag": "cnpj-feed", "asset": "cnpj_icp.csv", "max_mb": 1}
ASSET_URL = "https://api.github.com/repos/asimov/prospector/releases/assets/7"
CSV = b"cnpj,razao_social,nome_fantasia,cnae,uf,municipio,porte,situacao\n"


def _settings(token: str = "token-de-teste") -> Settings:
    s = Settings()
    s.cnpj_feed_token = token
    return s


def _release(size: int = len(CSV)) -> dict:
    return {"assets": [{"name": "cnpj_icp.csv", "url": ASSET_URL, "size": size, "updated_at": "2026-10-20T10:00:00Z"}]}


def _github(release: dict | None = None, status: int = 200, seen: list | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(status)
        if request.url.path.endswith("/releases/tags/cnpj-feed"):
            return httpx.Response(200, json=release or _release())
        return httpx.Response(200, content=CSV)
    return httpx.MockTransport(handler)


def test_fetches_latest_list_with_read_only_token():
    seen = []
    result = feed.fetch_latest(_settings(), FEED_CFG, transport=_github(seen=seen))
    assert result.content == CSV
    assert "2026-10-20" in result.label
    assert all(r.method == "GET" for r in seen)
    assert seen[0].headers["Authorization"] == "Bearer token-de-teste"
    assert seen[1].headers["Accept"] == "application/octet-stream"


def test_missing_token_is_reported_as_not_configured():
    assert not feed.is_configured(_settings(token=""), FEED_CFG)
    with pytest.raises(feed.FeedError, match="CNPJ_FEED_TOKEN"):
        feed.fetch_latest(_settings(token=""), FEED_CFG, transport=_github())


@pytest.mark.parametrize("status, message", [(401, "Token"), (404, "ainda não foi publicada"), (500, "500")])
def test_github_errors_become_friendly_messages(status, message):
    with pytest.raises(feed.FeedError, match=message):
        feed.fetch_latest(_settings(), FEED_CFG, transport=_github(status=status))


def test_release_without_the_asset_is_not_published_yet():
    with pytest.raises(feed.FeedError, match="ainda não foi publicada"):
        feed.fetch_latest(_settings(), FEED_CFG, transport=_github(release={"assets": []}))


def test_oversized_list_is_refused_before_download():
    seen = []
    with pytest.raises(feed.FeedError, match="MB"):
        feed.fetch_latest(_settings(), FEED_CFG, transport=_github(release=_release(size=2_000_000), seen=seen))
    assert len(seen) == 1
