import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from app.core.profile import seed_db
from app.database.db import connect, init_db


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Isola a suite do .env do desenvolvedor: nenhum teste usa a chave real do Ploomes nem herda o modo de acesso.
    Testes que precisam de outro valor sobrescrevem com monkeypatch."""
    monkeypatch.setenv("PLOOMES_USER_KEY", "")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("APP_USERS", "")
    monkeypatch.setenv("APP_ADMINS", "")
    # AppTest nao tem conexao real: simula o acesso pela propria maquina, como o Streamlit faz (localhost => None).
    monkeypatch.setattr("app.ui.auth._connection_ip", lambda: None)


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    seed_db(c)
    return c
