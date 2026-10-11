"""Espelhamento das bibliotecas de documentos de cada equipe do Teams no Google Drive."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from googleapiclient.http import MediaFileUpload

from .teams import GRAPH_BASE, GraphClient, GraphError

log = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"


def escape_query_value(value: str) -> str:
    """Escapa um valor para uso entre aspas simples em consultas `q` da Drive API."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


@dataclass
class SyncStats:
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass
class DriveFolders:
    """Acesso ao Drive com cache da listagem de cada pasta (uma consulta por pasta)."""

    service: object
    _cache: dict[str, dict[str, str]] = field(default_factory=dict)

    def children(self, folder_id: str) -> dict[str, str]:
        """Mapeia nome -> id dos itens não removidos de `folder_id`."""
        if folder_id not in self._cache:
            items: dict[str, str] = {}
            page_token = None
            while True:
                resp = (
                    self.service.files()
                    .list(
                        q=f"'{escape_query_value(folder_id)}' in parents and trashed=false",
                        fields="nextPageToken, files(id, name)",
                        pageSize=1000,
                        pageToken=page_token,
                    )
                    .execute()
                )
                for f in resp.get("files", []):
                    items.setdefault(f["name"], f["id"])
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
            self._cache[folder_id] = items
        return self._cache[folder_id]

    def ensure_folder(self, name: str, parent_id: str) -> str:
        existing = self.children(parent_id).get(name)
        if existing:
            return existing
        meta = {"name": name, "parents": [parent_id], "mimeType": FOLDER_MIME}
        folder_id = self.service.files().create(body=meta, fields="id").execute()["id"]
        self._cache[parent_id][name] = folder_id
        return folder_id

    def upload(self, local_path: Path, name: str, parent_id: str) -> None:
        meta = {"name": name, "parents": [parent_id]}
        media = MediaFileUpload(str(local_path), resumable=True)
        file_id = (
            self.service.files().create(body=meta, media_body=media, fields="id").execute()["id"]
        )
        self._cache[parent_id][name] = file_id


class TeamsToDriveMirror:
    def __init__(self, graph: GraphClient, drive_service, root_folder_id: str) -> None:
        self._graph = graph
        self._drive = DriveFolders(drive_service)
        self._root = root_folder_id
        self.stats = SyncStats()

    def sync_course(self, course: str, group_id: str) -> None:
        log.info("Disciplina: %s", course)
        course_folder = self._drive.ensure_folder(course, self._root)
        for library in self._graph.paginate(f"{GRAPH_BASE}/groups/{group_id}/drives"):
            drive_id = library["id"]
            log.info("  Biblioteca: %s", library.get("name", drive_id))
            url = f"{GRAPH_BASE}/drives/{drive_id}/root/children"
            self._sync_folder(url, drive_id, course_folder, library.get("name", ""))

    def _sync_folder(self, url: str, drive_id: str, drive_folder_id: str, path: str) -> None:
        try:
            items = list(self._graph.paginate(url))
        except GraphError as exc:
            log.error("Falha ao listar %s: %s", path, exc)
            self.stats.failed += 1
            return

        for item in items:
            name = item["name"]
            if "folder" in item:
                child_url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item['id']}/children"
                child_folder = self._drive.ensure_folder(name, drive_folder_id)
                self._sync_folder(child_url, drive_id, child_folder, f"{path}/{name}")
            elif "file" in item:
                self._sync_file(item, drive_folder_id, f"{path}/{name}")

    def _sync_file(self, item: dict, parent_id: str, path: str) -> None:
        name = item["name"]
        if name in self._drive.children(parent_id):
            log.debug("Já existe, ignorando: %s", path)
            self.stats.skipped += 1
            return

        download_url = item.get("@microsoft.graph.downloadUrl")
        if not download_url:
            log.warning("Sem URL de download: %s", path)
            self.stats.failed += 1
            return

        try:
            with tempfile.TemporaryDirectory() as tmp:
                local = Path(tmp) / "payload"
                with local.open("wb") as fh:
                    self._graph.download(download_url, fh)
                self._drive.upload(local, name, parent_id)
        except GraphError as exc:
            log.error("Falha ao baixar %s: %s", path, exc)
            self.stats.failed += 1
            return

        log.info("  Enviado: %s", path)
        self.stats.uploaded += 1
