"""Fetcher responsavel: robots.txt, timeouts, limite de tamanho, retry+backoff, cache em disco,
redirects revalidados um a um, checagem do IP efetivamente conectado (anti DNS-rebinding)."""
from __future__ import annotations
import json, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import httpx
from app.core.settings import Settings, get_settings
from app.core.utils import sha
from app.crawler.ssrf import UnsafeURL, validate_url, ip_is_public

ALLOWED_CT = ("text/html", "application/xhtml+xml", "text/plain")
MAX_REDIRECTS = 4


class FetchResult:
    def __init__(self, url, final_url=None, status=0, content_type="", body="", error=None, from_cache=False):
        self.url, self.final_url, self.status = url, final_url or url, status
        self.content_type, self.body, self.error, self.from_cache = content_type, body, error, from_cache

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300


class Fetcher:
    def __init__(self, settings: Settings | None = None, allow_private: bool = False, respect_robots: bool = True):
        self.s = settings or get_settings()
        self.allow_private = allow_private     # SOMENTE para testes com servidor local
        self.respect_robots = respect_robots
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self.stats = {"requests": 0, "cache_hits": 0, "errors": 0, "blocked_robots": 0, "unsafe": 0}
        self.client = httpx.Client(timeout=self.s.timeout_s, follow_redirects=False,
                                   headers={"User-Agent": self.s.user_agent, "Accept": "text/html,*/*;q=0.5",
                                            "Accept-Language": "pt-BR,pt;q=0.9"})

    # ---- cache ----
    def _cache_path(self, url: str) -> Path:
        return self.s.cache_dir / f"{sha(url)}.json"

    def _cache_get(self, url: str):
        p = self._cache_path(url)
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        if datetime.fromisoformat(d["at"]) < datetime.now(timezone.utc) - timedelta(days=self.s.cache_ttl_days):
            return None
        return d

    def _cache_put(self, url: str, r: FetchResult):
        self._cache_path(url).write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "final_url": r.final_url,
                                                     "status": r.status, "ct": r.content_type, "body": r.body}), encoding="utf-8")

    # ---- politeness ----
    def _wait(self, host: str):
        gap = time.time() - self._last.get(host, 0)
        if gap < self.s.domain_delay_s:
            time.sleep(self.s.domain_delay_s - gap)
        self._last[host] = time.time()

    def _request(self, url: str, max_bytes: int) -> FetchResult:
        """Uma sequencia de requests com redirects revalidados."""
        cur = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                validate_url(cur, self.allow_private)
            except UnsafeURL as e:
                self.stats["unsafe"] += 1
                return FetchResult(url, cur, error=f"unsafe:{e}")
            self._wait(urlparse(cur).hostname or "")
            self.stats["requests"] += 1
            with self.client.stream("GET", cur) as resp:
                if not self.allow_private:      # anti DNS rebinding: confere o IP realmente usado
                    stream = resp.extensions.get("network_stream")
                    addr = stream.get_extra_info("server_addr") if stream else None
                    if addr and not ip_is_public(addr[0]):
                        self.stats["unsafe"] += 1
                        return FetchResult(url, cur, error=f"unsafe:connected_non_public_ip:{addr[0]}")
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    cur = urljoin(cur, resp.headers["location"])
                    continue
                ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if resp.status_code == 200 and not any(ct.startswith(a) for a in ALLOWED_CT):
                    return FetchResult(url, cur, resp.status_code, ct, error=f"content_type_not_allowed:{ct}")
                buf, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        return FetchResult(url, cur, resp.status_code, ct, error="response_too_large")
                    buf.append(chunk)
                body = b"".join(buf).decode(resp.encoding or "utf-8", errors="replace")
                return FetchResult(url, cur, resp.status_code, ct, body)
        return FetchResult(url, cur, error="too_many_redirects")

    def robots_allows(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self._robots:
            r = self._request(origin + "/robots.txt", 200_000)
            rp = RobotFileParser()
            if r.error:
                self._robots[origin] = None if not r.error.startswith("unsafe") else RobotFileParser()
            elif r.status == 200:
                rp.parse(r.body.splitlines())
                self._robots[origin] = rp
            elif 400 <= r.status < 500:
                self._robots[origin] = None          # sem robots.txt => permitido
            else:
                rp.parse(["User-agent: *", "Disallow: /"])   # 5xx => conservador
                self._robots[origin] = rp
        rp = self._robots[origin]
        return True if rp is None else rp.can_fetch(self.s.user_agent, url)

    def fetch(self, url: str) -> FetchResult:
        cached = self._cache_get(url)
        if cached:
            self.stats["cache_hits"] += 1
            return FetchResult(url, cached["final_url"], cached["status"], cached["ct"], cached["body"], from_cache=True)
        try:
            validate_url(url, self.allow_private)
        except UnsafeURL as e:
            self.stats["unsafe"] += 1
            return FetchResult(url, error=f"unsafe:{e}")
        if not self.robots_allows(url):
            self.stats["blocked_robots"] += 1
            return FetchResult(url, error="blocked_by_robots")
        last = None
        for attempt in range(self.s.max_retries + 1):
            try:
                r = self._request(url, self.s.max_bytes)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = FetchResult(url, error=f"network:{type(e).__name__}")
            else:
                if r.error or r.status < 500 and r.status != 429:
                    last = r
                    break
                last = r
            time.sleep(min(2 ** attempt * 0.5, 4))      # backoff exponencial
        if last.error:
            self.stats["errors"] += 1
        elif last.ok:
            self._cache_put(url, last)
        return last

    def close(self):
        self.client.close()
