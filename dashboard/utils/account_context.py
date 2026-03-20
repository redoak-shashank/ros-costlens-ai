"""
Account context helpers for dashboard multi-account switching.

Supports selecting an account (e.g., default/saf) from the UI and reading
account-specific app/aws config from Streamlit secrets when provided.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import streamlit as st

ACCOUNT_SESSION_KEY = "dashboard_account"


def _as_dict(value) -> dict:
    """Best-effort conversion of Streamlit secret sections to plain dict."""
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def get_available_accounts() -> list[str]:
    """Return configured account choices for the dashboard selector."""
    try:
        accounts = _as_dict(st.secrets.get("accounts", {}))
        names = [str(name).strip() for name in accounts.keys() if str(name).strip()]
        if names:
            return sorted(names)
    except Exception:
        pass

    env_accounts = os.environ.get("DASHBOARD_ACCOUNTS", "")
    if env_accounts.strip():
        parsed = [x.strip() for x in env_accounts.split(",") if x.strip()]
        if parsed:
            return parsed

    return ["default"]


def get_selected_account() -> str:
    """Return active account key from session state (or fallback)."""
    accounts = get_available_accounts()
    default_account = accounts[0]
    selected = st.session_state.get(
        ACCOUNT_SESSION_KEY,
        os.environ.get("DASHBOARD_ACCOUNT", default_account),
    )
    if selected not in accounts:
        return default_account
    return selected


def get_account_config(section: str) -> dict:
    """
    Return merged config for a section (e.g., app/aws) for selected account.

    Precedence: account-specific section values override top-level section values.
    """
    merged: dict = {}
    try:
        top_level = _as_dict(st.secrets.get(section, {}))
        merged.update(top_level)

        accounts = _as_dict(st.secrets.get("accounts", {}))
        selected_cfg = _as_dict(accounts.get(get_selected_account(), {}))
        section_cfg = _as_dict(selected_cfg.get(section, {}))
        merged.update(section_cfg)
    except Exception:
        pass
    return merged


def get_account_value(section: str, key: str, default: str = "") -> str:
    """Return account-scoped section value with optional default."""
    value = get_account_config(section).get(key, default)
    return default if value is None else value


def get_selected_profile() -> str | None:
    """Return selected account profile from secrets/accounts or environment."""
    try:
        accounts = _as_dict(st.secrets.get("accounts", {}))
        selected_cfg = _as_dict(accounts.get(get_selected_account(), {}))
        profile = selected_cfg.get("aws_profile") or selected_cfg.get("profile")
        if isinstance(profile, str):
            profile = profile.strip()
            if profile:
                return profile
    except Exception:
        pass
    return os.environ.get("AWS_PROFILE")
