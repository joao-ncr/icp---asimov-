"""Seguranca fora da UI: senhas, papeis, limite de tentativas, migracao aditiva do banco e higiene do repositorio."""
import re
import subprocess
from pathlib import Path
import pytest
from app.core.auth import (LoginThrottle, Role, authenticate, hash_password, parse_admins, parse_users, verify_password)
from app.core.settings import ROOT, Settings
from app.database.db import connect, init_db

FAST = 1_000          # iteracoes reduzidas so nos testes (o padrao de producao e PBKDF2_ITERATIONS)


def _users():
    return {"ana": hash_password("senha-da-ana-123", iterations=FAST), "beto": hash_password("senha-do-beto-456", iterations=FAST)}


def test_password_hash_roundtrip_and_salt():
    first, second = hash_password("uma-senha-longa", iterations=FAST), hash_password("uma-senha-longa", iterations=FAST)
    assert first != second                                     # sal aleatorio
    assert verify_password("uma-senha-longa", first) and not verify_password("outra-senha-xx", first)
    assert "uma-senha-longa" not in first


@pytest.mark.parametrize("encoded", ["", "texto", "md5$1$aa$bb", "pbkdf2_sha256$0$aa$bb", "pbkdf2_sha256$x$zz$yy"])
def test_malformed_hashes_never_authenticate(encoded):
    assert verify_password("qualquer-coisa", encoded) is False


def test_short_passwords_are_rejected():
    with pytest.raises(ValueError):
        hash_password("curta")


def test_authenticate_roles_and_failures():
    users, admins = _users(), parse_admins("Ana")
    assert authenticate(" ANA ", "senha-da-ana-123", users, admins).role is Role.ADMIN
    assert authenticate("beto", "senha-do-beto-456", users, admins).role is Role.MEMBER
    assert authenticate("beto", "errada-errada", users, admins) is None
    assert authenticate("ninguem", "senha-da-ana-123", users, admins) is None


def test_users_spec_parsing_ignores_garbage():
    assert parse_users("ana=h1; beto = h2 ;;sem-hash=;=orfao\ncaio=h3") == {"ana": "h1", "beto": "h2", "caio": "h3"}


def test_login_throttle_locks_after_failures_and_expires():
    now = [0.0]
    throttle = LoginThrottle(max_failures=3, lockout_s=60, clock=lambda: now[0])
    for _ in range(3):
        throttle.register("ana", success=False)
    assert throttle.seconds_locked("ANA") == 60
    now[0] = 61
    assert throttle.seconds_locked("ana") == 0
    throttle.register("ana", success=False)                     # bloqueio expirado: recomeca a contagem
    assert throttle.seconds_locked("ana") == 0
    throttle.register("ana", success=True)
    assert throttle.seconds_locked("ana") == 0


def test_secrets_are_not_in_settings_repr(monkeypatch):
    monkeypatch.setenv("PLOOMES_USER_KEY", "segredo-ploomes-xyz")
    monkeypatch.setenv("APP_USERS", "ana=hash-secreto")
    text = repr(Settings())
    assert "segredo-ploomes-xyz" not in text and "hash-secreto" not in text


def test_migration_is_additive_and_repeatable(tmp_path):
    db = tmp_path / "antigo.db"
    old = connect(db)
    old.executescript("""CREATE TABLE known_lead (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, name_norm TEXT, domain TEXT, outcome TEXT,
                         value REAL, funnel TEXT, loss_reason TEXT, loss_category TEXT, segment TEXT, is_person INTEGER DEFAULT 0, created_month TEXT);
                         INSERT INTO known_lead(name, outcome) VALUES ('Lead da planilha', 'won');""")
    old.commit()
    init_db(old)
    init_db(old)
    cols = {r[1] for r in old.execute("PRAGMA table_info(known_lead)")}
    assert "ploomes_deal_id" in cols
    assert old.execute("SELECT name FROM known_lead").fetchall()[0][0] == "Lead da planilha"
    assert {"ploomes_company", "ploomes_sync"} <= {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _tracked_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git indisponível ou fora de um repositório (ex.: pacote de deploy): higiene verificada no repositório")
    return [line for line in out.splitlines() if line]


ALLOWED_DATA = {"data/leads_seed.csv", "data/seeds_demo.csv", "data/seeds_template.csv"}


def test_repository_tracks_no_database_secret_or_real_lead_data():
    files = _tracked_files()
    assert not [f for f in files if re.search(r"\.db(-wal|-shm)?$|(^|/)\.env$|secrets\.toml$", f)]
    assert [f for f in files if f.startswith("data/")] == sorted(f for f in files if f in ALLOWED_DATA)


def test_repository_contains_no_api_key_like_secret():
    key_like = re.compile(r"\b[0-9A-F]{64,}\b")
    leaks = []
    for name in _tracked_files():
        path = ROOT / name
        if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".xlsx", ".ico"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if key_like.search(text) or re.search(r"User-Key\s*[:=]\s*['\"]?[0-9A-Za-z]{16,}", text):
            leaks.append(name)
    assert leaks == []
