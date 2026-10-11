"""Conversão dos prazos de tarefas do Teams em eventos do Google Agenda.

Cada evento carrega o ID da tarefa em `extendedProperties.private`, o que torna a
sincronização idempotente: rodar o programa várias vezes atualiza os eventos
existentes em vez de duplicá-los.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .config import CalendarSettings
from .teams import GRAPH_BASE, GraphClient, GraphError

log = logging.getLogger(__name__)

ASSIGNMENT_ID_KEY = "teamsAssignmentId"
SUMMARY_PREFIX = "[FATEC]"


@dataclass
class CalendarStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0


def parse_due(value: str) -> datetime:
    """Converte o `dueDateTime` da Graph API (ISO 8601, sufixo Z) em datetime UTC."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def legacy_summary(assignment_name: str) -> str:
    """Título usado nas primeiras versões, mantido para migrar eventos já criados."""
    return f"{SUMMARY_PREFIX} Entrega: {assignment_name}"


def build_event(assignment: dict, course_name: str | None, settings: CalendarSettings) -> dict:
    """Monta o corpo do evento: um bloco que termina no prazo da tarefa."""
    name = assignment.get("displayName") or "Tarefa sem nome"
    end = parse_due(assignment["dueDateTime"])
    start = end - timedelta(hours=settings.event_duration_hours)
    summary = f"{SUMMARY_PREFIX} {course_name}: {name}" if course_name else legacy_summary(name)
    return {
        "summary": summary,
        "description": (
            "Tarefa do Microsoft Teams.\n"
            f"Status no Teams: {assignment.get('status', 'desconhecido')}"
        ),
        "colorId": settings.color_id,
        "start": {"dateTime": _iso(start), "timeZone": "UTC"},
        "end": {"dateTime": _iso(end), "timeZone": "UTC"},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": m} for m in settings.reminders_minutes],
        },
        "extendedProperties": {"private": {ASSIGNMENT_ID_KEY: assignment["id"]}},
    }


def needs_update(existing: dict, desired: dict) -> bool:
    """Indica se o evento existente difere do desejado em título, horário ou cor."""

    def moment(event: dict, key: str) -> datetime | None:
        raw = event.get(key, {}).get("dateTime")
        return parse_due(raw) if raw else None

    return (
        existing.get("summary") != desired["summary"]
        or existing.get("colorId") != desired["colorId"]
        or moment(existing, "start") != moment(desired, "start")
        or moment(existing, "end") != moment(desired, "end")
    )


class AssignmentCalendarSync:
    def __init__(self, graph: GraphClient, calendar_service, settings: CalendarSettings) -> None:
        self._graph = graph
        self._events = calendar_service.events()
        self._settings = settings
        self.stats = CalendarStats()

    def run(self) -> CalendarStats:
        course_names = self._load_course_names()
        assignments = list(self._graph.paginate(f"{GRAPH_BASE}/education/me/assignments"))
        log.info("%d tarefas encontradas", len(assignments))

        for assignment in assignments:
            if not assignment.get("dueDateTime"):
                continue
            course = course_names.get(assignment.get("classId", ""))
            self._upsert(build_event(assignment, course, self._settings), assignment)
        return self.stats

    def _load_course_names(self) -> dict[str, str]:
        try:
            classes = self._graph.paginate(f"{GRAPH_BASE}/education/me/classes")
            return {c["id"]: c.get("displayName", "") for c in classes}
        except GraphError as exc:
            log.warning("Não foi possível obter os nomes das turmas: %s", exc)
            return {}

    def _find_existing(self, assignment: dict) -> dict | None:
        by_id = self._events.list(
            calendarId="primary",
            privateExtendedProperty=f"{ASSIGNMENT_ID_KEY}={assignment['id']}",
            singleEvents=True,
        ).execute()
        if by_id.get("items"):
            return by_id["items"][0]

        title = legacy_summary(assignment.get("displayName") or "Tarefa sem nome")
        by_title = self._events.list(calendarId="primary", q=title, singleEvents=True).execute()
        for event in by_title.get("items", []):
            private = event.get("extendedProperties", {}).get("private", {})
            if event.get("summary") == title and ASSIGNMENT_ID_KEY not in private:
                return event
        return None

    def _upsert(self, desired: dict, assignment: dict) -> None:
        existing = self._find_existing(assignment)
        if existing is None:
            self._events.insert(calendarId="primary", body=desired).execute()
            self.stats.created += 1
            log.info("Criado: %s", desired["summary"])
        elif needs_update(existing, desired):
            self._events.update(
                calendarId="primary", eventId=existing["id"], body=desired
            ).execute()
            self.stats.updated += 1
            log.info("Atualizado: %s", desired["summary"])
        else:
            self.stats.unchanged += 1
