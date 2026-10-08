import httpx
from app.core.settings import Settings
from app.crawler.fetcher import Fetcher, FetchResult
from app.crawler import ssrf
from app.pipeline import WebPageSource, run_pipeline, ranking
from app.models.schemas import Candidate
from app.database.db import connect, init_db
from app.core.profile import seed_db


def test_ssl_transport_error_isolated_and_http_fallback(tmp_path, monkeypatch):
    # HTTPS falha por SSL; HTTP funciona. O crawler nao desabilita TLS e faz fallback seguro.
    s = Settings(cache_dir=tmp_path, domain_delay_s=0, max_retries=0)
    calls = []
    def handler(req):
        calls.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.scheme == "https":
            raise httpx.ConnectError("certificate verify failed", request=req)
        return httpx.Response(200, text="<html><title>Empresa</title><body>equipe operacional ordens de servico planilhas</body></html>", headers={"content-type":"text/html"})
    monkeypatch.setattr(ssrf, "resolve", lambda host: ["93.184.216.34"])
    f = Fetcher(s)
    f.client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    source = WebPageSource(f, s)
    pages, err = source.get_pages("empresa.test", 2)
    assert err is None
    assert pages and pages[0]["status_code"] == 200


def test_batch_continues_after_unexpected_candidate_failure(monkeypatch):
    c = connect(":memory:"); init_db(c); seed_db(c)
    s = Settings(cache_dir=__import__('pathlib').Path("/tmp/asimov-test-cache"), domain_delay_s=0, max_retries=0)
    class Source:
        def get_pages(self, domain, max_pages):
            if domain == "quebra.test":
                raise RuntimeError("falha simulada")
            return [{"url": "https://ok.test/", "status_code": 200, "text": "equipe operacional ordens de servico planilhas", "features": {}, "injection_flags": 0, "links": []}], None
    rid = run_pipeline(c, [Candidate(name="Quebra", domain="quebra.test"), Candidate(name="OK", domain="ok.test")], Source(), s)
    rows = c.execute("SELECT o.name,a.status,a.reason FROM analysis a JOIN organization o ON o.id=a.org_id ORDER BY o.name").fetchall()
    assert len(rows) == 2
    assert any(r[0] == "Quebra" and r[1] == "error" for r in rows)
    assert any(r[0] == "OK" for r in rows)
