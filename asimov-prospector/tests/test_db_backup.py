"""Copia de seguranca do banco no deploy (app/database/backup.py), contra um GitHub falso (MockTransport), sem rede.
Cobre: copia/restauracao consistentes, restaurar so com o disco vazio, nunca sobrescrever a copia boa apos falha,
rotacao das copias, debounce dos envios e o aviso de gravacao do banco."""
import gzip
import sqlite3
from pathlib import Path
import httpx
import pytest
from app.core.settings import Settings
from app.database import backup, db

CFG = backup.BackupConfig(repo="asimov/prospector", release_tag="db-backup", asset_prefix="asimov-db-", keep=2,
                          debounce_s=3600, max_bytes=10_000_000)
UPLOAD_URL = "https://uploads.github.com/repos/asimov/prospector/releases/1/assets{?name,label}"


def _settings(tmp_path: Path, token: str = "token-de-teste") -> Settings:
    s = Settings()
    s.db_backup_token = token
    s.db_path = tmp_path / "asimov.db"
    return s


def _make_db(path: Path, value: str) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS t(v TEXT)")
    conn.execute("INSERT INTO t VALUES(?)", (value,))
    conn.commit()
    conn.close()


def _values(path: Path) -> list[str]:
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT v FROM t")]
    finally:
        conn.close()


def _asset(asset_id: int, name: str) -> dict:
    return {"id": asset_id, "name": name, "size": 100, "url": f"https://api.github.com/repos/asimov/prospector/releases/assets/{asset_id}"}


class FakeGitHub:
    """Release em memoria: responde como a API do GitHub para as chamadas que o modulo usa."""

    def __init__(self, assets: dict[int, tuple[str, bytes]] | None = None, release_exists: bool = True, fail_status: int | None = None):
        self.assets = dict(assets or {})
        self.release_exists = release_exists
        self.fail_status = fail_status
        self.requests: list[httpx.Request] = []

    def _release(self) -> dict:
        return {"id": 1, "upload_url": UPLOAD_URL, "assets": [_asset(i, n) for i, (n, _) in self.assets.items()]}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_status:
            return httpx.Response(self.fail_status)
        path = request.url.path
        if request.method == "GET" and path.endswith("/releases/tags/db-backup"):
            return httpx.Response(200, json=self._release()) if self.release_exists else httpx.Response(404)
        if request.method == "POST" and path.endswith("/releases"):
            self.release_exists = True
            return httpx.Response(201, json=self._release())
        if request.method == "POST" and request.url.host == "uploads.github.com":
            self.assets[max(self.assets, default=0) + 1] = (request.url.params["name"], request.content)
            return httpx.Response(201, json={})
        asset_id = int(path.rsplit("/", 1)[1])
        if request.method == "DELETE":
            del self.assets[asset_id]
            return httpx.Response(204)
        return httpx.Response(200, content=self.assets[asset_id][1])

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def test_snapshot_and_restore_roundtrip(tmp_path):
    source = tmp_path / "origem.db"
    _make_db(source, "avaliacao boa")
    target = tmp_path / "restaurado.db"
    backup.restore(backup.snapshot(source), target)
    assert _values(target) == ["avaliacao boa"]


def test_restore_refuses_content_that_is_not_sqlite(tmp_path):
    with pytest.raises(backup.BackupError, match="SQLite"):
        backup.restore(gzip.compress(b"nao sou um banco"), tmp_path / "x.db")
    with pytest.raises(backup.BackupError, match="corrompida"):
        backup.restore(b"nem gzip", tmp_path / "x.db")


def test_restores_newest_copy_when_disk_is_empty(tmp_path):
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    _make_db(old, "antiga")
    _make_db(new, "recente")
    github = FakeGitHub({1: ("asimov-db-20261101T000000Z.sqlite.gz", backup.snapshot(old)),
                         2: ("asimov-db-20261105T000000Z.sqlite.gz", backup.snapshot(new)),
                         3: ("cnpj_icp.csv", b"outro arquivo da release")})
    s = _settings(tmp_path)
    assert backup.restore_if_missing(s, CFG, github.transport) is backup.RestoreOutcome.RESTORED
    assert _values(s.db_path) == ["recente"]
    assert all(r.method == "GET" for r in github.requests)
    assert github.requests[0].headers["Authorization"] == "Bearer token-de-teste"


def test_local_database_in_sync_with_release_is_kept(tmp_path):
    s = _settings(tmp_path)
    _make_db(s.db_path, "local")
    backup.version_file(s.db_path).write_text("asimov-db-20261105T000000Z.sqlite.gz", encoding="utf-8")
    github = FakeGitHub({1: ("asimov-db-20261105T000000Z.sqlite.gz", b"nao deve ser baixada")})
    assert backup.restore_if_missing(s, CFG, github.transport) is backup.RestoreOutcome.LOCAL_EXISTS
    assert _values(s.db_path) == ["local"]
    assert len(github.requests) == 1                    # so a listagem; nada baixado


def test_copy_uploaded_by_hand_replaces_local_database(tmp_path):
    """Disco preservado entre reinicios, mas alguem publicou outra copia (ex.: banco da maquina local ou volta atras)."""
    s = _settings(tmp_path)
    _make_db(s.db_path, "local")
    backup.version_file(s.db_path).write_text("asimov-db-20261101T000000Z.sqlite.gz", encoding="utf-8")
    other = tmp_path / "other.db"
    _make_db(other, "enviada a mao")
    github = FakeGitHub({1: ("asimov-db-20261106T000000Z.sqlite.gz", backup.snapshot(other))})
    assert backup.restore_if_missing(s, CFG, github.transport) is backup.RestoreOutcome.RESTORED
    assert _values(s.db_path) == ["enviada a mao"]
    assert backup.version_file(s.db_path).read_text(encoding="utf-8") == "asimov-db-20261106T000000Z.sqlite.gz"


def test_local_database_without_any_copy_is_kept(tmp_path):
    s = _settings(tmp_path)
    _make_db(s.db_path, "local")
    assert backup.restore_if_missing(s, CFG, FakeGitHub(release_exists=False).transport) is backup.RestoreOutcome.LOCAL_EXISTS


def test_without_token_nothing_happens(tmp_path):
    github = FakeGitHub()
    assert backup.restore_if_missing(_settings(tmp_path, token=""), CFG, github.transport) is backup.RestoreOutcome.DISABLED
    assert github.requests == []


def test_first_deploy_without_copy_starts_empty(tmp_path):
    s = _settings(tmp_path)
    assert backup.restore_if_missing(s, CFG, FakeGitHub(release_exists=False).transport) is backup.RestoreOutcome.NO_BACKUP
    assert not s.db_path.exists()


def test_failed_restore_is_retried_even_if_an_empty_db_was_created(tmp_path):
    """Falhou -> o app cria um banco vazio. Na proxima subida, esse banco nao pode ser tratado como valido."""
    s = _settings(tmp_path)
    assert backup.restore_if_missing(s, CFG, FakeGitHub(fail_status=500).transport) is backup.RestoreOutcome.FAILED
    _make_db(s.db_path, "vazio criado depois da falha")
    good = tmp_path / "good.db"
    _make_db(good, "copia boa")
    github = FakeGitHub({1: ("asimov-db-20261105T000000Z.sqlite.gz", backup.snapshot(good))})
    assert backup.restore_if_missing(s, CFG, github.transport) is backup.RestoreOutcome.RESTORED
    assert _values(s.db_path) == ["copia boa"]
    assert not backup.pending_marker(s.db_path).exists()


def test_start_disables_uploads_when_restore_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "restore_if_missing", lambda settings, cfg: backup.RestoreOutcome.FAILED)
    assert backup.start(_settings(tmp_path)).scheduler is None


def test_publish_creates_release_uploads_and_keeps_only_latest_copies(tmp_path):
    s = _settings(tmp_path)
    _make_db(s.db_path, "atual")
    github = FakeGitHub({1: ("asimov-db-20261101T000000Z.sqlite.gz", b"a"), 2: ("asimov-db-20261102T000000Z.sqlite.gz", b"b"),
                         3: ("cnpj_icp.csv", b"nao e copia")})
    name = backup.publish_snapshot(s, CFG, github.transport)
    names = sorted(n for n, _ in github.assets.values())
    assert names == ["asimov-db-20261102T000000Z.sqlite.gz", name, "cnpj_icp.csv"]       # keep=2: a nova + a anterior
    restored = tmp_path / "check.db"
    backup.restore(dict(github.assets.values())[name], restored)
    assert _values(restored) == ["atual"]
    assert backup.version_file(s.db_path).read_text(encoding="utf-8") == name


def test_publish_creates_the_release_on_first_use(tmp_path):
    s = _settings(tmp_path)
    _make_db(s.db_path, "x")
    github = FakeGitHub(release_exists=False)
    backup.publish_snapshot(s, CFG, github.transport)
    assert any(r.method == "POST" and r.url.path.endswith("/releases") for r in github.requests)
    assert len(github.assets) == 1


def test_publish_errors_become_backup_error(tmp_path):
    s = _settings(tmp_path)
    _make_db(s.db_path, "x")
    with pytest.raises(backup.BackupError, match="DB_BACKUP_TOKEN"):
        backup.publish_snapshot(s, CFG, FakeGitHub(fail_status=403).transport)


def test_scheduler_coalesces_writes_into_one_upload():
    uploads = []
    scheduler = backup.BackupScheduler(lambda: uploads.append(1) or "ok", debounce_s=3600)
    scheduler.notify()
    scheduler.notify()
    assert scheduler.pending
    scheduler.flush()
    scheduler.flush()                   # nada pendente: nao envia de novo
    assert uploads == [1]
    assert scheduler.last_ok_at and not scheduler.pending


def test_scheduler_keeps_error_for_the_admin():
    def failing() -> str:
        raise backup.BackupError("sem permissao")
    scheduler = backup.BackupScheduler(failing, debounce_s=3600)
    scheduler.notify()
    scheduler.flush()
    assert scheduler.last_error == "sem permissao"


def test_session_notifies_listeners_only_after_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_write_listeners", [])
    calls = []
    db.add_write_listener(lambda: calls.append(1))
    path = tmp_path / "x.db"
    with db.session(path) as conn:
        conn.execute("CREATE TABLE t(v)")
        conn.execute("INSERT INTO t VALUES(1)")
    with db.session(path) as conn:
        conn.execute("SELECT * FROM t").fetchall()
    assert calls == [1]
