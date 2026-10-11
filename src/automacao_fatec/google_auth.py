"""Autenticação OAuth 2.0 (fluxo de aplicativo instalado) para as APIs do Google."""

from __future__ import annotations

import logging
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.file",
]


def load_credentials(credentials_file: Path, token_file: Path) -> Credentials:
    """Reutiliza o token salvo, renova-o se expirou ou abre o fluxo de consentimento."""
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            log.info("Renovando token do Google")
            creds.refresh(Request())
        except RefreshError as exc:
            log.warning("Renovação recusada (%s); novo consentimento necessário", exc)
            creds = _run_consent_flow(credentials_file)
    else:
        creds = _run_consent_flow(credentials_file)

    token_file.write_text(creds.to_json(), encoding="utf-8")
    token_file.chmod(0o600)
    return creds


def _run_consent_flow(credentials_file: Path) -> Credentials:
    log.info("Iniciando fluxo de consentimento do Google")
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    return flow.run_local_server(port=0)


def build_services(creds: Credentials):
    """Retorna os clientes (calendar, drive)."""
    calendar = build("calendar", "v3", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return calendar, drive
