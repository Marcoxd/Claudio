"""Enlace firmado al dashboard."""
from __future__ import annotations

from app.config import settings


def dashboard_url(path: str = "/") -> str:
    base = settings.base_url.rstrip("/")
    sep = "&" if "?" in path else "?"
    return f"{base}{path}{sep}t={settings.dashboard_token}"
