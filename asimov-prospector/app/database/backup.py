"""Copia de seguranca do banco SQLite numa release do repositorio privado do GitHub.

Por que: no Streamlit Community Cloud o disco e apagado a cada reinicio. O deploy roda um unico conteiner (um unico
processo escrevendo), entao basta: restaurar a copia mais recente ao subir, se o banco local nao existir, e enviar uma
copia nova pouco depois de cada gravacao (debounce). Uso local sem DB_BACKUP_TOKEN: nada acontece.

Seguranca: host fixo (api.github.com / uploads.github.com), nenhuma URL vem do usuario; token fora de logs. Se a
restauracao falhar, os envios ficam desligados no processo, para um banco vazio nunca sobrescrever a copia boa."""
from __future__ import annotations
import atexit
import gzip
import logging
import os
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable
import httpx
from app.core.settings import Settings
from app.core.utils import load_yaml
from app.database.db import add_write_listener, now

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
TIMEOUT_S = 60
BYTES_PER_MB = 1_000_000
ASSET_SUFFIX = ".sqlite.gz"
SQLITE_HEADER = b"SQLite format 3\x00"
RESTORE_PENDING_SUFFIX = ".restore-pending"
SQLITE_SIDE_FILES = ("-wal", "-shm")
VERSION_SUFFIX = ".backup-version"


class BackupError(RuntimeError):
    pass


class RestoreOutcome(str, Enum):
    DISABLED = "disabled"           # sem token/config: uso local
    LOCAL_EXISTS = "local_exists"   # o banco ja esta no disco (processo reiniciado sem perder o disco)
    RESTORED = "restored"
    NO_BACKUP = "no_backup"         # primeira vez: ainda nao ha copia publicada
    FAILED = "failed"               # envios desligados neste processo


@dataclass(frozen=True)
class BackupConfig:
    repo: str
    release_tag: str
    asset_prefix: str
    keep: int
    debounce_s: float
    max_bytes: int


def load_config(config_dir: Path) -> BackupConfig:
    raw = load_yaml(config_dir / "backup.yaml")
    return BackupConfig(repo=raw["repo"], release_tag=raw["release_tag"], asset_prefix=raw["asset_prefix"], keep=int(raw["keep"]),
                        debounce_s=float(raw["debounce_s"]), max_bytes=int(raw["max_mb"] * BYTES_PER_MB))


def is_enabled(settings: Settings, cfg: BackupConfig) -> bool:
    return bool(settings.db_backup_token and cfg.repo)


# --- arquivo local (puro, sem rede) -------------------------------------------------------------------------------
def snapshot(db_path: Path) -> bytes:
    """Copia consistente (API de backup do SQLite, respeita o WAL) comprimida com gzip."""
    with tempfile.TemporaryDirectory() as tmp:
        copy_path = Path(tmp) / "snapshot.db"
        source, target = sqlite3.connect(str(db_path)), sqlite3.connect(str(copy_path))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return gzip.compress(copy_path.read_bytes())


def restore(content: bytes, db_path: Path) -> None:
    """Grava a copia no lugar do banco de forma atomica (arquivo temporario + rename). Recusa o que nao for SQLite."""
    try:
        raw = gzip.decompress(content)
    except (OSError, EOFError) as exc:
        raise BackupError("A cópia de segurança está corrompida (gzip inválido).") from exc
    if not raw.startswith(SQLITE_HEADER):
        raise BackupError("A cópia de segurança não é um banco SQLite.")
    tmp_path = db_path.with_suffix(".restoring")
    tmp_path.write_bytes(raw)
    for leftover in SQLITE_SIDE_FILES:          # WAL de um banco anterior seria aplicado por cima da copia restaurada
        db_path.with_name(db_path.name + leftover).unlink(missing_ok=True)
    os.replace(tmp_path, db_path)


def asset_name(cfg: BackupConfig, moment: datetime) -> str:
    return f"{cfg.asset_prefix}{moment.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}{ASSET_SUFFIX}"


def backup_assets(release: dict, cfg: BackupConfig) -> list[dict]:
    """Copias da release, da mais recente para a mais antiga (o nome carrega o horario)."""
    ours = [a for a in release.get("assets", []) if a.get("name", "").startswith(cfg.asset_prefix) and a["name"].endswith(ASSET_SUFFIX)]
    return sorted(ours, key=lambda a: a["name"], reverse=True)


# --- GitHub (rede) ------------------------------------------------------------------------------------------------
class ReleaseStore:
    """Release do GitHub como armazenamento: listar, baixar, enviar e apagar copias."""

    def __init__(self, settings: Settings, cfg: BackupConfig, transport: httpx.BaseTransport | None = None):
        self._cfg = cfg
        headers = {"Authorization": f"Bearer {settings.db_backup_token}", "X-GitHub-Api-Version": GITHUB_API_VERSION,
                   "User-Agent": settings.user_agent, "Accept": "application/vnd.github+json"}
        # O download do asset redireciona para outro host; o httpx descarta o Authorization nesse redirecionamento.
        self._client = httpx.Client(base_url=GITHUB_API, headers=headers, timeout=TIMEOUT_S, follow_redirects=True, transport=transport)

    def __enter__(self) -> ReleaseStore:
        return self

    def __exit__(self, *exc) -> None:
        self._client.close()

    def find_release(self) -> dict | None:
        response = self._client.get(f"/repos/{self._cfg.repo}/releases/tags/{self._cfg.release_tag}")
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        _raise_for_status(response)
        return response.json()

    def ensure_release(self) -> dict:
        release = self.find_release()
        if release is not None:
            return release
        body = {"tag_name": self._cfg.release_tag, "name": "Cópia de segurança do banco (Prospector)", "prerelease": True,
                "make_latest": "false", "body": "Gerada automaticamente pelo app publicado. Não editar nem apagar à mão."}
        response = self._client.post(f"/repos/{self._cfg.repo}/releases", json=body)
        _raise_for_status(response)
        return response.json()

    def download(self, asset: dict) -> bytes:
        if asset.get("size", 0) > self._cfg.max_bytes:
            raise BackupError("A cópia de segurança passa do limite configurado (backup.yaml: max_mb).")
        chunks, size = [], 0
        with self._client.stream("GET", asset["url"], headers={"Accept": "application/octet-stream"}) as response:
            _raise_for_status(response)
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self._cfg.max_bytes:
                    raise BackupError("A cópia de segurança passa do limite configurado (backup.yaml: max_mb).")
                chunks.append(chunk)
        return b"".join(chunks)

    def upload(self, release: dict, name: str, content: bytes) -> None:
        upload_url = release["upload_url"].split("{", 1)[0]       # vem como ".../assets{?name,label}"
        response = self._client.post(upload_url, params={"name": name}, content=content,
                                     headers={"Content-Type": "application/gzip"})
        _raise_for_status(response)

    def delete(self, asset: dict) -> None:
        _raise_for_status(self._client.delete(f"/repos/{self._cfg.repo}/releases/assets/{asset['id']}"))


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        raise BackupError("Token do GitHub inválido ou sem permissão de escrita no repositório (DB_BACKUP_TOKEN).")
    if response.is_error:
        raise BackupError(f"O GitHub respondeu {response.status_code} na cópia de segurança do banco.")


# --- casos de uso -------------------------------------------------------------------------------------------------
def pending_marker(db_path: Path) -> Path:
    """Existe enquanto uma restauracao falhou: o banco local (vazio ou parcial) nao e confiavel e nao pode virar copia."""
    return db_path.with_name(db_path.name + RESTORE_PENDING_SUFFIX)


def version_file(db_path: Path) -> Path:
    """Nome da copia que o banco local representa (a ultima restaurada ou enviada por este disco)."""
    return db_path.with_name(db_path.name + VERSION_SUFFIX)


def _local_version(db_path: Path) -> str | None:
    path = version_file(db_path)
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def restore_if_missing(settings: Settings, cfg: BackupConfig, transport: httpx.BaseTransport | None = None) -> RestoreOutcome:
    """Ao subir, antes de qualquer conexao: traz a copia mais recente se o disco veio vazio, se a ultima restauracao
    falhou ou se a release tem uma copia diferente da que o disco representa (enviada a mao ou volta a uma anterior)."""
    if not is_enabled(settings, cfg):
        return RestoreOutcome.DISABLED
    marker = pending_marker(settings.db_path)
    trusted_local = settings.db_path.exists() and not marker.exists()
    try:
        with ReleaseStore(settings, cfg, transport) as store:
            assets = backup_assets(store.find_release() or {}, cfg)
            newest = assets[0]["name"] if assets else None
            if trusted_local and newest in (None, _local_version(settings.db_path)):
                return RestoreOutcome.LOCAL_EXISTS
            if newest:
                restore(store.download(assets[0]), settings.db_path)
                version_file(settings.db_path).write_text(newest, encoding="utf-8")
    except (BackupError, httpx.HTTPError, OSError) as exc:
        logger.error("Restauracao do banco falhou: %s", exc.__class__.__name__)
        marker.touch()
        return RestoreOutcome.FAILED
    marker.unlink(missing_ok=True)
    if newest is None:
        return RestoreOutcome.NO_BACKUP
    logger.info("Banco restaurado da copia %s", newest)
    return RestoreOutcome.RESTORED


def publish_snapshot(settings: Settings, cfg: BackupConfig, transport: httpx.BaseTransport | None = None) -> str:
    """Envia uma copia nova e so depois apaga as excedentes (nunca fica sem copia). Devolve o nome enviado."""
    try:
        content = snapshot(settings.db_path)
        name = asset_name(cfg, datetime.now(timezone.utc))
        with ReleaseStore(settings, cfg, transport) as store:
            release = store.ensure_release()
            store.upload(release, name, content)
            version_file(settings.db_path).write_text(name, encoding="utf-8")
            for old in [a for a in backup_assets(release, cfg) if a["name"] != name][cfg.keep - 1:]:
                store.delete(old)
    except (httpx.HTTPError, sqlite3.Error, OSError) as exc:
        raise BackupError(f"Não foi possível enviar a cópia de segurança ({exc.__class__.__name__}).") from exc
    return name


class BackupScheduler:
    """Junta gravacoes seguidas num unico envio, feito numa thread depois de `debounce_s` sem nova gravacao pendente."""

    def __init__(self, upload: Callable[[], str], debounce_s: float):
        self._upload = upload
        self._debounce_s = debounce_s
        self._timer_lock, self._upload_lock = threading.Lock(), threading.Lock()
        self._timer: threading.Timer | None = None
        self.last_ok_at: str | None = None
        self.last_error: str | None = None

    @property
    def pending(self) -> bool:
        return self._timer is not None

    def notify(self) -> None:
        with self._timer_lock:
            if self._timer is not None:
                return
            self._timer = threading.Timer(self._debounce_s, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        """Envia agora o que estiver pendente (chamado pelo timer ou ao encerrar o processo)."""
        with self._timer_lock:
            timer, self._timer = self._timer, None
        if timer is None:
            return
        timer.cancel()
        with self._upload_lock:
            try:
                self._upload()
            except BackupError as exc:
                self.last_error = str(exc)
                logger.error("Copia de seguranca do banco falhou: %s", exc)
                return
            self.last_ok_at, self.last_error = now(), None


@dataclass(frozen=True)
class Persistence:
    outcome: RestoreOutcome
    scheduler: BackupScheduler | None       # None = envios desligados (uso local ou restauracao falhou)


def start(settings: Settings) -> Persistence:
    """Uma vez por processo, antes de qualquer conexao: restaura se preciso e liga os envios apos cada gravacao."""
    cfg = load_config(settings.config_dir)
    outcome = restore_if_missing(settings, cfg)
    if outcome in (RestoreOutcome.DISABLED, RestoreOutcome.FAILED):
        return Persistence(outcome, None)
    scheduler = BackupScheduler(lambda: publish_snapshot(settings, cfg), cfg.debounce_s)
    add_write_listener(scheduler.notify)
    atexit.register(scheduler.flush)        # encerramento normal (novo deploy): envia o que estiver pendente
    return Persistence(outcome, scheduler)
