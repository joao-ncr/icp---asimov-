"""Autenticacao da interface (logica pura, sem Streamlit): senhas com PBKDF2-SHA256, papeis e limite de tentativas.

Usuarios vem de APP_USERS ("usuario=hash;usuario2=hash", hashes gerados por `python run.py hash-password`) e
administradores de APP_ADMINS. Nenhuma senha em texto puro e guardada. Servico gratuito: nao depende de provedor externo."""
from __future__ import annotations
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

HASH_SCHEME = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000         # recomendacao OWASP (2023) para PBKDF2-HMAC-SHA256
SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 10
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 300
LOCAL_USERNAME = "local"
AUTH_MODE_PASSWORD = "password"
AUTH_MODE_LOCAL = "local"
_DUMMY_HASH = f"{HASH_SCHEME}${PBKDF2_ITERATIONS}${'00' * SALT_BYTES}${'00' * 32}"


class Role(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"


@dataclass(frozen=True)
class User:
    username: str
    role: Role

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


LOCAL_USER = User(LOCAL_USERNAME, Role.ADMIN)


def hash_password(password: str, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"A senha precisa ter ao menos {MIN_PASSWORD_LENGTH} caracteres.")
    salt = salt or secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{HASH_SCHEME}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = encoded.split("$")
        salt, expected, rounds = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex), int(iterations)
    except ValueError:
        return False
    if scheme != HASH_SCHEME or rounds <= 0:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(candidate, expected)


def parse_users(spec: str) -> dict[str, str]:
    users = {}
    for item in spec.replace("\n", ";").split(";"):
        username, sep, encoded = item.strip().partition("=")
        if sep and username.strip() and encoded.strip():
            users[username.strip().lower()] = encoded.strip()
    return users


def parse_admins(spec: str) -> frozenset[str]:
    return frozenset(name.strip().lower() for name in spec.split(",") if name.strip())


def authenticate(username: str, password: str, users: dict[str, str], admins: frozenset[str]) -> User | None:
    name = username.strip().lower()
    encoded = users.get(name)
    # Usuario inexistente tambem paga o custo do hash: o tempo de resposta nao revela quem existe.
    valid = verify_password(password, encoded or _DUMMY_HASH)
    if not (encoded and valid):
        return None
    return User(name, Role.ADMIN if name in admins else Role.MEMBER)


class LoginThrottle:
    """Bloqueia um usuario apos tentativas falhas seguidas, valendo para todas as sessoes do processo."""

    def __init__(self, max_failures: int = MAX_FAILED_ATTEMPTS, lockout_s: int = LOCKOUT_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        self._max, self._lockout, self._clock = max_failures, lockout_s, clock
        self._failures: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def seconds_locked(self, username: str) -> int:
        with self._lock:
            return self._remaining(username.strip().lower())

    def _remaining(self, key: str) -> int:
        count, last_failure = self._failures.get(key, (0, 0.0))
        if count < self._max:
            return 0
        return max(0, int(self._lockout - (self._clock() - last_failure)))

    def register(self, username: str, success: bool) -> None:
        key = username.strip().lower()
        with self._lock:
            if success:
                self._failures.pop(key, None)
                return
            count, _ = self._failures.get(key, (0, 0.0))
            if count >= self._max and not self._remaining(key):
                count = 0                                # bloqueio expirado: recomeca a contagem
            self._failures[key] = (count + 1, self._clock())
