from datetime import UTC, datetime

from automacao_fatec.calendar_sync import (
    ASSIGNMENT_ID_KEY,
    build_event,
    legacy_summary,
    needs_update,
    parse_due,
)
from automacao_fatec.config import CalendarSettings

SETTINGS = CalendarSettings(event_duration_hours=2, color_id="11", reminders_minutes=(1440, 120))
ASSIGNMENT = {
    "id": "abc-123",
    "displayName": "Lista 1",
    "dueDateTime": "2026-09-23T23:59:00Z",
    "status": "assigned",
}


def test_parse_due_aceita_com_e_sem_fracao():
    esperado = datetime(2026, 9, 23, 23, 59, tzinfo=UTC)
    assert parse_due("2026-09-23T23:59:00Z") == esperado
    assert parse_due("2026-09-23T23:59:00.0000000Z") == esperado


def test_parse_due_sem_fuso_assume_utc():
    assert parse_due("2026-09-23T23:59:00").tzinfo == UTC


def test_build_event_termina_no_prazo_e_dura_duas_horas():
    event = build_event(ASSIGNMENT, "Algoritmos", SETTINGS)
    assert event["start"]["dateTime"] == "2026-09-23T21:59:00Z"
    assert event["end"]["dateTime"] == "2026-09-23T23:59:00Z"
    assert event["summary"] == "[FATEC] Algoritmos: Lista 1"
    assert event["extendedProperties"]["private"][ASSIGNMENT_ID_KEY] == "abc-123"
    assert [r["minutes"] for r in event["reminders"]["overrides"]] == [1440, 120]


def test_build_event_sem_disciplina_usa_titulo_legado():
    event = build_event(ASSIGNMENT, None, SETTINGS)
    assert event["summary"] == legacy_summary("Lista 1")


def test_needs_update_falso_para_evento_igual():
    desired = build_event(ASSIGNMENT, "Algoritmos", SETTINGS)
    assert not needs_update(dict(desired), desired)


def test_needs_update_ignora_formato_equivalente_de_horario():
    desired = build_event(ASSIGNMENT, "Algoritmos", SETTINGS)
    existing = dict(desired)
    existing["start"] = {"dateTime": "2026-09-23T18:59:00-03:00"}
    existing["end"] = {"dateTime": "2026-09-23T20:59:00-03:00"}
    assert not needs_update(existing, desired)


def test_needs_update_detecta_mudanca_de_prazo():
    desired = build_event(ASSIGNMENT, "Algoritmos", SETTINGS)
    novo = build_event(
        {**ASSIGNMENT, "dueDateTime": "2026-09-30T23:59:00Z"}, "Algoritmos", SETTINGS
    )
    assert needs_update(desired, novo)
