"""Leitura e validação do arquivo de configuração (TOML)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Configuração ausente ou inválida."""


@dataclass(frozen=True)
class CalendarSettings:
    event_duration_hours: int = 2
    color_id: str = "11"
    reminders_minutes: tuple[int, ...] = (1440, 120)


@dataclass(frozen=True)
class Config:
    drive_folder_id: str
    courses: dict[str, str]
    credentials_file: Path
    token_file: Path
    session_dir: Path
    token_wait_seconds: int
    token_settle_seconds: int
    calendar: CalendarSettings


def load_config(path: str | Path) -> Config:
    """Carrega o TOML em `path` e valida os campos obrigatórios."""
    path = Path(path)
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError(
            f"Arquivo de configuração não encontrado: {path}. "
            "Copie config.example.toml para config.toml e preencha."
        ) from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML inválido em {path}: {exc}") from exc

    drive_folder_id = raw.get("drive_folder_id")
    if not drive_folder_id or not isinstance(drive_folder_id, str):
        raise ConfigError("'drive_folder_id' é obrigatório.")

    courses = raw.get("courses")
    if not isinstance(courses, dict) or not courses:
        raise ConfigError("A seção [courses] deve mapear ao menos uma disciplina a um ID de grupo.")

    cal = raw.get("calendar", {})
    defaults = CalendarSettings()
    calendar = CalendarSettings(
        event_duration_hours=int(cal.get("event_duration_hours", defaults.event_duration_hours)),
        color_id=str(cal.get("color_id", defaults.color_id)),
        reminders_minutes=tuple(cal.get("reminders_minutes", defaults.reminders_minutes)),
    )
    if calendar.event_duration_hours <= 0:
        raise ConfigError("'event_duration_hours' deve ser positivo.")

    return Config(
        drive_folder_id=drive_folder_id,
        courses={str(name): str(group_id) for name, group_id in courses.items()},
        credentials_file=Path(raw.get("credentials_file", "credentials.json")),
        token_file=Path(raw.get("token_file", "token.json")),
        session_dir=Path(raw.get("session_dir", "teams_session")),
        token_wait_seconds=int(raw.get("token_wait_seconds", 180)),
        token_settle_seconds=int(raw.get("token_settle_seconds", 20)),
        calendar=calendar,
    )
