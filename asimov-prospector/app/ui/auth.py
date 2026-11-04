"""Portao de acesso da interface: nada de dados e renderizado antes do login (ver app/core/auth.py)."""
from __future__ import annotations
import ipaddress
import os
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from app.core.auth import (AUTH_MODE_LOCAL, AUTH_MODE_PASSWORD, LOCAL_USER, LoginThrottle, User, authenticate, parse_admins,
                           parse_users)
from app.core.settings import get_settings
from app.ui import theme

SESSION_KEY = "auth_user"
SECONDS_PER_MINUTE = 60
# Compartilhado por todas as sessoes do processo: abrir outra aba nao zera o limite de tentativas.
_THROTTLE = LoginThrottle()


def load_secrets_into_env() -> None:
    """Deploy (Streamlit Community Cloud): chaves de primeiro nivel de st.secrets viram variaveis de ambiente.
    Nunca sobrescreve uma variavel ja definida; sem arquivo de secrets (uso local com .env), nao faz nada."""
    try:
        values = {k: v for k, v in st.secrets.items() if isinstance(v, (str, int, float))}
    except (FileNotFoundError, StreamlitSecretNotFoundError):
        return
    for key, value in values.items():
        os.environ.setdefault(key, str(value))


def _connection_ip() -> str | None:
    return st.context.ip_address


def is_local_address(ip: str | None) -> bool:
    if ip is None:              # o Streamlit devolve None para acessos via localhost
        return True
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def require_user() -> User:
    """Devolve o usuario autenticado ou interrompe a renderizacao (st.stop) mostrando o login ou o motivo do bloqueio."""
    s = get_settings()
    if s.auth_mode == AUTH_MODE_LOCAL:
        if not is_local_address(_connection_ip()):
            st.error("Modo local: o acesso sem login só é permitido na própria máquina.")
            st.stop()
        return LOCAL_USER
    if s.auth_mode != AUTH_MODE_PASSWORD:
        st.error("Configuração de acesso inválida (AUTH_MODE deve ser 'password' ou 'local').")
        st.stop()
    user = st.session_state.get(SESSION_KEY)
    if user:
        return user
    users = parse_users(s.app_users)
    theme.brand()
    if not users:
        theme.hero("Acesso não configurado", "Nenhum usuário cadastrado. Um administrador precisa definir APP_USERS nos segredos do deploy.")
        st.stop()
    _login_form(users, parse_admins(s.app_admins))
    st.stop()


def _login_form(users: dict[str, str], admins: frozenset[str]) -> None:
    theme.hero("Entrar", "Acesso restrito ao time da Asimov Jr. Use o usuário e a senha fornecidos pelo administrador.")
    with st.form("login"):
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
    if not submitted:
        return
    locked = _THROTTLE.seconds_locked(username)
    if locked:
        st.error(f"Muitas tentativas sem sucesso. Tente novamente em {locked // SECONDS_PER_MINUTE + 1} min.")
        return
    user = authenticate(username, password, users, admins)
    _THROTTLE.register(username, user is not None)
    if user is None:
        st.error("Usuário ou senha inválidos.")
        return
    st.session_state[SESSION_KEY] = user
    st.rerun()


def logout_button(user: User) -> None:
    if user is LOCAL_USER:
        st.caption("Modo local (sem login).")
        return
    st.caption(f"Conectado como **{user.username}**" + (" · administrador" if user.is_admin else ""))
    if st.button("Sair", width="stretch"):
        st.session_state.pop(SESSION_KEY, None)
        st.rerun()
