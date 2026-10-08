import httpx, pytest
from app.core.settings import Settings
from app.crawler import ssrf
from app.crawler.fetcher import Fetcher
from app.crawler.ssrf import UnsafeURL, validate_url


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "ftp://x.com/",
                                 "http://localhost/", "http://[::1]/", "http://2130706433/", "http://10.0.0.5/", "http://192.168.0.1:80/",
                                 "https://example.com:8443/", "http://user:pw@example.com/", "http://0.0.0.0/"])
def test_blocks_unsafe(url):
    with pytest.raises(UnsafeURL):
        validate_url(url)


def test_allows_public_ip_literal():
    assert validate_url("https://8.8.8.8/")


def _fetcher(tmp_path, handler, monkeypatch):
    s = Settings(cache_dir=tmp_path, domain_delay_s=0, max_retries=0)
    monkeypatch.setattr(ssrf, "resolve", lambda host: ["10.1.1.1"] if host.startswith("evil") else ["93.184.216.34"])
    f = Fetcher(s)
    f.client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return f


def test_redirect_to_private_ip_is_blocked(tmp_path, monkeypatch):
    def h(req):
        if req.url.path == "/robots.txt": return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})
    r = _fetcher(tmp_path, h, monkeypatch).fetch("https://good.test/")
    assert r.error and r.error.startswith("unsafe")


def test_dns_resolving_to_private_blocked(tmp_path, monkeypatch):
    r = _fetcher(tmp_path, lambda req: httpx.Response(200, text="x"), monkeypatch).fetch("https://evil.test/")
    assert r.error and "non_public_ip" in r.error


def test_robots_disallow_respected(tmp_path, monkeypatch):
    def h(req):
        if req.url.path == "/robots.txt": return httpx.Response(200, text="User-agent: *\nDisallow: /privado")
        return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})
    f = _fetcher(tmp_path, h, monkeypatch)
    assert f.fetch("https://good.test/privado/x").error == "blocked_by_robots"
    assert f.fetch("https://good.test/publico").ok


def test_response_too_large_and_content_type(tmp_path, monkeypatch):
    def h(req):
        if req.url.path == "/robots.txt": return httpx.Response(404)
        if req.url.path == "/big": return httpx.Response(200, content=b"a" * 3_000_000, headers={"content-type": "text/html"})
        return httpx.Response(200, content=b"\x00\x01", headers={"content-type": "application/octet-stream"})
    f = _fetcher(tmp_path, h, monkeypatch)
    assert f.fetch("https://good.test/big").error == "response_too_large"
    assert f.fetch("https://good.test/bin").error.startswith("content_type_not_allowed")


def test_cache_hit(tmp_path, monkeypatch):
    calls = []
    def h(req):
        calls.append(req.url.path)
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text="<p>oi</p>", headers={"content-type": "text/html"})
    f = _fetcher(tmp_path, h, monkeypatch)
    f.fetch("https://good.test/a"); f.fetch("https://good.test/a")
    assert calls.count("/a") == 1 and f.stats["cache_hits"] == 1
