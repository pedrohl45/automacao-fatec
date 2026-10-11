"""Acesso ao Microsoft Teams: captura do token e cliente mínimo da Microsoft Graph API."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import BinaryIO

import requests
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class GraphError(RuntimeError):
    """Falha em uma requisição à Graph API."""


def extract_graph_token(url: str, headers: Mapping[str, str]) -> str | None:
    """Devolve o header Authorization se a requisição for um acesso Bearer à Graph API."""
    auth = headers.get("authorization")
    if auth and auth.lower().startswith("bearer ") and "graph.microsoft.com" in url:
        return auth
    return None


def capture_graph_token(
    session_dir: Path, wait_seconds: int = 180, settle_seconds: int = 20
) -> str | None:
    """Abre o Teams Web e intercepta o token Bearer usado nas chamadas à Graph API.

    O perfil do navegador é persistido em `session_dir` para evitar logins repetidos.
    O usuário precisa navegar até a aba "Arquivos" de uma equipe para que o próprio
    Teams dispare uma chamada à Graph API. O Teams usa tokens com permissões distintas
    conforme a tela; por isso a captura só termina após `settle_seconds` sem novos tokens,
    mantendo o mais recente. Ver a seção de limitações no README.
    """
    token: str | None = None
    last_seen = 0
    tick = 0

    def on_request(request) -> None:
        nonlocal token, last_seen
        found = extract_graph_token(request.url, request.headers)
        if found:
            token = found
            last_seen = tick

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(session_dir), headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.on("request", on_request)
            try:
                page.goto("https://teams.microsoft.com", timeout=60_000)
            except PlaywrightError as exc:
                log.warning("Navegação inicial incompleta: %s", exc)

            log.info("Aguardando token; abra a aba 'Arquivos' de uma equipe no Teams")
            try:
                while tick < wait_seconds:
                    if token and tick - last_seen >= settle_seconds:
                        break
                    page.wait_for_timeout(1000)
                    tick += 1
            except PlaywrightError:
                log.warning("Navegador fechado antes do fim da captura")
        finally:
            try:
                context.close()
            except PlaywrightError:
                pass

    if token:
        log.info("Token da Graph API capturado")
    return token


class GraphClient:
    """Cliente HTTP com timeout, paginação e tentativas para 429/5xx."""

    def __init__(self, token: str, timeout: float = 30.0, max_retries: int = 4) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"Authorization": token, "Accept": "application/json"})

    def _get(self, url: str, **kwargs) -> requests.Response:
        for attempt in range(self._max_retries + 1):
            resp = self._session.get(url, timeout=self._timeout, **kwargs)
            if resp.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                delay = _retry_delay(resp, attempt)
                log.warning("HTTP %s em %s; nova tentativa em %.1fs", resp.status_code, url, delay)
                time.sleep(delay)
                continue
            if not resp.ok:
                log.debug("Corpo da resposta de erro: %s", resp.text[:500])
                raise GraphError(f"HTTP {resp.status_code} em {url}")
            return resp
        raise GraphError(f"Tentativas esgotadas em {url}")

    def get_json(self, url: str) -> dict:
        return self._get(url).json()

    def paginate(self, url: str) -> Iterator[dict]:
        """Itera sobre `value`, seguindo `@odata.nextLink` até o fim."""
        next_url: str | None = url
        while next_url:
            data = self._get(next_url).json()
            yield from data.get("value", [])
            next_url = data.get("@odata.nextLink")

    def download(self, url: str, dest: BinaryIO) -> None:
        """Baixa `url` em blocos, sem enviar o token (a URL de download já é pré-autenticada)."""
        with requests.get(url, stream=True, timeout=self._timeout) as resp:
            if not resp.ok:
                raise GraphError(f"HTTP {resp.status_code} no download")
            for chunk in resp.iter_content(chunk_size=1 << 20):
                dest.write(chunk)


def _retry_delay(resp: requests.Response, attempt: int) -> float:
    try:
        return float(resp.headers["Retry-After"])
    except (KeyError, ValueError):
        return float(2**attempt)
