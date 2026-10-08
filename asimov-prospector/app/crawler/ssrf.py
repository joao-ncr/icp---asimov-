"""Protecao contra SSRF: valida esquema, porta e TODOS os IPs resolvidos."""
from __future__ import annotations
import ipaddress, socket
from urllib.parse import urlparse

ALLOWED_PORTS = {80, 443, None}
BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


class UnsafeURL(Exception):
    pass


def ip_is_public(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    # is_global cobre privados, loopback, link-local, CGNAT (100.64/10), documentacao, reservados
    return bool(a.is_global) and not (a.is_multicast or a.is_unspecified or getattr(a, "is_site_local", False))


def resolve(host: str) -> list[str]:
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(host, None)})
    except socket.gaierror as e:
        raise UnsafeURL(f"dns_failure:{host}") from e


def validate_url(url: str, allow_private: bool = False) -> str:
    """Retorna a URL normalizada ou levanta UnsafeURL."""
    p = urlparse(url.strip())
    if p.scheme not in ("http", "https"):
        raise UnsafeURL(f"scheme_not_allowed:{p.scheme}")
    if p.username or p.password:
        raise UnsafeURL("credentials_in_url")
    host = (p.hostname or "").lower()
    if not host:
        raise UnsafeURL("no_host")
    if allow_private:
        return url
    if p.port not in ALLOWED_PORTS:
        raise UnsafeURL(f"port_not_allowed:{p.port}")
    if host in BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeURL(f"blocked_host:{host}")
    try:
        ips = [str(ipaddress.ip_address(host))]  # host ja e IP literal (inclui decimal/hex normalizados pelo urlparse)
    except ValueError:
        ips = resolve(host)
    if not ips:
        raise UnsafeURL("no_ips")
    bad = [ip for ip in ips if not ip_is_public(ip)]
    if bad:
        raise UnsafeURL(f"non_public_ip:{bad[0]}")
    return url
