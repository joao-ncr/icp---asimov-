"""Interface com acesso controlado e fonte Ploomes: login, papeis, sincronizacao pela tela, analise em lote, autoria
das avaliacoes e escape de HTML. Sem rede: o Ploomes e os sites sao falsos."""
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from app.core.auth import LoginThrottle, hash_password
from app.core.settings import ROOT, get_settings
from app.database.db import ensure_ready, session
from app.discovery import sources
from app.integrations.ploomes.sync import run_sync
from app.pipeline import FixtureSource, run_pipeline
from app.ui import auth as ui_auth
from app.ui import theme
from tests.test_ploomes_sync import FakePloomes, _client

APP = str(ROOT / "app" / "ui" / "streamlit_app.py")
FIXTURE_SITES = ROOT / "tests" / "fixtures" / "sites"
ANA, ANA_PWD = "ana", "senha-da-ana-123"          # administradora
BETO, BETO_PWD = "beto", "senha-do-beto-456"      # membro do time


@pytest.fixture
def ui_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(ui_auth, "_THROTTLE", LoginThrottle())
    monkeypatch.setattr("app.ui.data.WebPageSource", lambda fetcher, s: FixtureSource(FIXTURE_SITES))
    monkeypatch.setattr("app.ui.data.client_from_settings", lambda s: _client(FakePloomes()))
    ensure_ready.cache_clear(); st.cache_data.clear()
    ensure_ready()
    yield
    ensure_ready.cache_clear(); st.cache_data.clear()


@pytest.fixture
def password_mode(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.setenv("APP_USERS", f"{ANA}={hash_password(ANA_PWD)};{BETO}={hash_password(BETO_PWD)}")
    monkeypatch.setenv("APP_ADMINS", ANA)
    monkeypatch.setenv("PLOOMES_USER_KEY", "chave-falsa-de-teste")


def _synced():
    with session() as conn:
        run_sync(conn, _client(FakePloomes()), "teste")


def _ranked_demo():
    with session() as conn:
        run_pipeline(conn, sources.from_seed_csv(ROOT / "data" / "seeds_demo.csv"), FixtureSource(FIXTURE_SITES), get_settings())


def _login(username: str, password: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90).run()
    next(t for t in at.text_input if t.label == "Usuário").set_value(username)
    next(t for t in at.text_input if t.label == "Senha").set_value(password)
    next(b for b in at.button if b.label == "Entrar").click()
    return at.run()


def _open(at: AppTest, page: str) -> AppTest:
    at.session_state["page"] = page
    return at.run()


def _texts(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [x.value for x in at.success]
    parts += [x.value for x in at.info] + [x.value for x in at.warning] + [x.value for x in at.error]
    return "\n".join(str(p) for p in parts)


def test_without_configured_users_nothing_is_shown(ui_db, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "password")
    _ranked_demo()
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert "Acesso não configurado" in _texts(at)
    assert not at.radio and "Alfa Manutencao" not in _texts(at)


def test_wrong_password_shows_generic_error_and_no_data(ui_db, password_mode):
    _ranked_demo()
    at = _login(ANA, "senha-errada-123")
    assert not at.exception
    assert any("Usuário ou senha inválidos" in e.value for e in at.error)
    assert not at.radio and not at.dataframe


def test_repeated_failures_lock_the_account(ui_db, password_mode):
    for _ in range(5):
        _login(BETO, "senha-errada-123")
    at = _login(BETO, BETO_PWD)                      # ate a senha certa e recusada durante o bloqueio
    assert any("Muitas tentativas" in e.value for e in at.error)
    assert not at.radio


def test_member_logs_in_and_does_not_see_admin_controls(ui_db, password_mode):
    _synced()
    at = _open(_login(BETO, BETO_PWD), "Nova análise")
    assert not at.exception
    assert not any("Sincronizar" in b.label for b in at.button)
    assert "feita por um administrador" in _texts(at)
    assert any(b.label == "🚀 Analisar próximas empresas" for b in at.button)


def test_admin_syncs_from_ploomes_through_the_screen(ui_db, password_mode):
    at = _open(_login(ANA, ANA_PWD), "Nova análise")
    assert "ainda não foi sincronizado" in _texts(at)
    next(b for b in at.button if "Sincronizar com o Ploomes" in b.label).click()
    at.run()
    assert not at.exception
    assert any("Sincronização completa concluída: 4 empresa(s)" in s.value for s in at.success)
    assert {m.label: m.value for m in at.metric}["Empresas no Ploomes"] == "4"
    assert "por ana" in _texts(at)                    # trilha de auditoria visivel


def test_next_pending_batch_is_analyzed_and_reaches_the_ranking(ui_db, password_mode):
    _synced()
    at = _open(_login(BETO, BETO_PWD), "Nova análise")
    next(b for b in at.button if b.label == "🚀 Analisar próximas empresas").click()
    at.run()
    assert not at.exception
    assert any("Rodada concluída: 4 leads processados" in s.value for s in at.success)
    at = _open(at, "Ranking")
    assert "Alfa Manutencao Industrial" in at.dataframe[0].value["Empresa"].tolist()


def test_evaluation_author_is_the_logged_user(ui_db, password_mode):
    _ranked_demo()
    at = _open(_login(BETO, BETO_PWD), "Avaliar")
    assert "Avaliando como" in _texts(at) and not any(t.label == "Seu nome (opcional)" for t in at.text_input)
    next(r for r in at.radio if "boa oportunidade" in r.label).set_value("boa")
    next(b for b in at.button if "Salvar" in b.label).click()
    at.run()
    with session() as conn:
        assert conn.execute("SELECT author FROM human_feedback").fetchone()["author"] == BETO


def test_logout_returns_to_login(ui_db, password_mode):
    at = _login(ANA, ANA_PWD)
    next(b for b in at.button if b.label == "Sair").click()
    at.run()
    assert any(t.label == "Senha" for t in at.text_input) and not at.radio


def test_local_mode_without_ploomes_key_explains_how_to_configure(ui_db):
    at = _open(AppTest.from_file(APP, default_timeout=60).run(), "Nova análise")
    assert not at.exception
    assert "ainda não está configurada" in _texts(at)


def test_local_mode_refuses_network_connections(ui_db, monkeypatch):
    _ranked_demo()
    monkeypatch.setattr(ui_auth, "_connection_ip", lambda: "192.168.0.10")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert "só é permitido na própria máquina" in _texts(at)
    assert not at.radio and not at.dataframe


@pytest.mark.parametrize("ip, local", [(None, True), ("127.0.0.1", True), ("::1", True), ("192.168.0.10", False),
                                       ("8.8.8.8", False), ("lixo", False)])
def test_local_mode_only_accepts_loopback(ip, local):
    assert ui_auth.is_local_address(ip) is local


DISCOVERY_CSV = (b"cnpj,razao_social,nome_fantasia,cnae,uf,municipio,porte,situacao\n"
                 b"11.222.333/0001-44,Industria Alfa LTDA,Industria Alfa,2512-8,MG,Itajuba,PEQUENA,ATIVA\n")


def test_member_does_not_see_the_discovery_generate_button(ui_db, password_mode):
    at = _open(_login(BETO, BETO_PWD), "Nova análise")
    assert not at.exception
    assert not any("Gerar candidatos" in b.label for b in at.button)
    assert "geração de novos leads é feita por um administrador" in _texts(at)


def test_admin_generates_discovery_candidates_through_the_screen(ui_db, password_mode):
    at = _open(_login(ANA, ANA_PWD), "Nova análise")
    next(f for f in at.file_uploader if "extrato de CNPJ" in f.label).set_value(("extrato.csv", DISCOVERY_CSV, "text/csv"))
    at.run()
    next(b for b in at.button if "Gerar candidatos" in b.label).click()
    at.run()
    assert not at.exception
    assert any("candidato(s) novo(s) para aprovar" in s.value for s in at.success)
    assert "Industria Alfa" in at.dataframe[-1].value["Empresa"].tolist()
    with session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM organization").fetchone()[0] == 0   # sem aprovacao, nao e organizacao


def test_theme_escapes_text_from_the_crm(monkeypatch):
    rendered: list[str] = []
    monkeypatch.setattr(theme.st, "markdown", lambda body, **kw: rendered.append(body))
    evil = '<img src=x onerror="alert(1)">Empresa'
    theme.company_card(evil, '"><script>x()</script>')
    theme.hero(evil, evil)
    theme.notice(evil)
    theme.step(1, evil, evil)
    html = "".join(rendered)
    assert "<img" not in html and "<script" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;Empresa" in html
