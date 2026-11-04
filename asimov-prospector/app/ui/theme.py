"""Identidade visual (Asimov Jr.) e blocos de HTML reutilizados pelas telas.

Funciona nos modos claro e escuro do Streamlit: cores de texto, fundo e bordas são derivadas do tema ativo
(`inherit` / `currentColor`); só o azul da marca e os acentos de estado têm cor própria. Paleta do site asimovjr.com.br:
azul #007FFF (primária), navy #0A0E23 / #0F142C (fundos e texto escuros)."""
from __future__ import annotations
import base64
from functools import lru_cache
from html import escape
from pathlib import Path
import streamlit as st
from PIL import Image

ASSETS = Path(__file__).parent / "assets"
BRAND_BLUE = "#007FFF"
BRAND_NAME = "Asimov Jr."

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700&display=swap');
:root {
  --asimov-blue: __BLUE__;
  --asimov-line: color-mix(in srgb, currentColor 16%, transparent);
  --asimov-surface: color-mix(in srgb, currentColor 5%, transparent);
}
.brand { display:flex; align-items:center; gap:12px; padding: 4px 0 18px 0; }
.brand img { width: 40px; height: 40px; }
.brand-name { font-family: 'Poppins', sans-serif; font-size: 22px; font-weight: 600; letter-spacing: -0.5px; line-height: 1.1; }
.brand-sub { opacity: .65; font-size: 12px; margin-top: 2px; }
.hero { background: var(--asimov-surface); border: 1px solid var(--asimov-line); border-left: 4px solid var(--asimov-blue);
        border-radius: 14px; padding: 24px 28px; margin-bottom: 20px; }
.hero h1 { margin: 0 0 6px 0; padding: 0; font-family: 'Poppins', sans-serif; font-size: 30px; font-weight: 600; letter-spacing: -0.8px; }
.hero p { margin: 0; opacity: .75; font-size: 15px; }
.card { background: var(--asimov-surface); border: 1px solid var(--asimov-line); border-radius: 14px; padding: 18px 20px; margin-bottom: 14px; }
.card-title { font-size: 18px; font-weight: 700; margin-bottom: 4px; }
.muted { opacity: .65; font-size: 13px; }
.step { background: var(--asimov-surface); border: 1px solid var(--asimov-line); border-radius: 12px; padding: 16px; height: 100%; }
.step-num { display:inline-flex; width:28px; height:28px; align-items:center; justify-content:center; border-radius:50%;
            background: var(--asimov-blue); color:#fff; font-weight:700; margin-bottom:10px; }
.step-title { font-weight: 700; }
.step-text { opacity: .7; font-size: 13px; margin-top: 4px; }
.notice { background: var(--asimov-surface); border: 1px solid var(--asimov-line); border-radius: 10px; padding: 12px 14px; opacity: .85; font-size: 13px; }
div[data-testid="stMetric"] { background: var(--asimov-surface); border: 1px solid var(--asimov-line); padding: 14px 16px; border-radius: 12px; }

/* Indicador de execução: o mini Homem de Ferro substitui o boneco correndo do Streamlit */
[data-testid="stStatusWidgetRunningIcon"] {
  width: 30px; height: 52px; background: url(__MASCOT__) center / contain no-repeat;
  filter: drop-shadow(0 0 1px rgba(255,255,255,.55)); animation: asimov-hover 0.9s ease-in-out infinite alternate;
}
[data-testid="stStatusWidgetRunningManIcon"] { display: none; }
@keyframes asimov-hover { from { transform: translateY(3px) rotate(-3deg); } to { transform: translateY(-4px) rotate(3deg); } }
@media (prefers-reduced-motion: reduce) { [data-testid="stStatusWidgetRunningIcon"] { animation: none; } }
</style>
"""


@lru_cache
def _data_uri(filename: str) -> str:
    return "data:image/png;base64," + base64.b64encode((ASSETS / filename).read_bytes()).decode("ascii")


@lru_cache
def page_icon() -> Image.Image:
    return Image.open(ASSETS / "asimov_mark.png")


def apply() -> None:
    st.markdown(_CSS.replace("__BLUE__", BRAND_BLUE).replace("__MASCOT__", _data_uri("mascot.png")), unsafe_allow_html=True)


def brand() -> None:
    st.markdown(f'<div class="brand"><img src="{_data_uri("asimov_mark.png")}" alt="{BRAND_NAME}">'
                f'<div><div class="brand-name">{BRAND_NAME}</div><div class="brand-sub">Prospector · Operação</div></div></div>', unsafe_allow_html=True)


# Todo texto interpolado no HTML abaixo passa por escape: nome e site vêm do CRM (texto livre digitado por pessoas).
def hero(title: str, text: str) -> None:
    st.markdown(f'<div class="hero"><h1>{escape(title)}</h1><p>{escape(text)}</p></div>', unsafe_allow_html=True)


def step(number: int, title: str, text: str) -> None:
    st.markdown(f'<div class="step"><div class="step-num">{int(number)}</div><div class="step-title">{escape(title)}</div>'
                f'<div class="step-text">{escape(text)}</div></div>', unsafe_allow_html=True)


def company_card(name: str, domain: str | None) -> None:
    st.markdown(f'<div class="card"><div class="card-title">{escape(name)}</div>'
                f'<div class="muted">{escape(domain or "sem site informado")}</div></div>', unsafe_allow_html=True)


def notice(text: str) -> None:
    st.markdown(f'<div class="notice">{escape(text)}</div>', unsafe_allow_html=True)
