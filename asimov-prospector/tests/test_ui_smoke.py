"""Fumaca da interface: abre cada tela contra um banco temporario e percorre o fluxo de avaliacao."""
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from app.core.settings import ROOT, get_settings
from app.database.db import ensure_ready, session
from app.discovery import sources
from app.pipeline import FixtureSource, run_pipeline

APP = str(ROOT / "app" / "ui" / "streamlit_app.py")


@pytest.fixture
def populated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    ensure_ready.cache_clear(); st.cache_data.clear()
    ensure_ready()
    with session() as conn:
        run_pipeline(conn, sources.from_seed_csv(ROOT / "data" / "seeds_demo.csv"), FixtureSource(ROOT / "tests" / "fixtures" / "sites"), get_settings())
    yield tmp_path / "ui.db"
    ensure_ready.cache_clear(); st.cache_data.clear()


def _app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=60).run()


def test_opens_on_ranking_with_learning_progress(populated_db):
    at = _app()
    assert not at.exception
    assert at.session_state["page"] == "Ranking"
    assert any("Avaliações: 0 de" in p.text for p in at.get("progress"))


def test_every_page_renders(populated_db):
    at = _app()
    for page in ("Nova análise", "Avaliar", "Ranking"):
        at.session_state["page"] = page
        at.run()
        assert not at.exception, page


def test_team_evaluation_is_saved_and_moves_to_next_company(populated_db):
    at = _app()
    at.session_state["page"] = "Avaliar"
    at.run()
    first = at.session_state["selected_org_id"]
    form_radio = next(r for r in at.radio if "boa oportunidade" in r.label)
    form_radio.set_value("boa")
    next(b for b in at.button if "Salvar" in b.label).click()
    at.run()
    assert not at.exception
    with session() as conn:
        saved = conn.execute("SELECT org_id, quality FROM human_feedback").fetchall()
    assert [(r["org_id"], r["quality"]) for r in saved] == [(first, "boa")]
    assert at.session_state["selected_org_id"] != first                        # seguiu para a proxima sem avaliacao


def test_saving_without_choosing_a_level_does_nothing(populated_db):
    at = _app()
    at.session_state["page"] = "Avaliar"
    at.run()
    next(b for b in at.button if "Salvar" in b.label).click()
    at.run()
    assert any("Escolha uma das três" in w.value for w in at.warning)
    with session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM human_feedback").fetchone()[0] == 0
