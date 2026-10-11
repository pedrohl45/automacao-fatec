"""Interface de linha de comando."""

from __future__ import annotations

import argparse
import logging
import sys

from .calendar_sync import AssignmentCalendarSync
from .config import ConfigError, load_config
from .drive_sync import TeamsToDriveMirror
from .google_auth import build_services, load_credentials
from .teams import GraphClient, GraphError, capture_graph_token

log = logging.getLogger("automacao_fatec")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="automacao-fatec",
        description="Sincroniza materiais e tarefas do Microsoft Teams com Google Drive e Agenda.",
    )
    parser.add_argument("-c", "--config", default="config.toml", help="caminho do arquivo TOML")
    parser.add_argument("--skip-files", action="store_true", help="não sincroniza arquivos")
    parser.add_argument("--skip-calendar", action="store_true", help="não sincroniza tarefas")
    parser.add_argument("-v", "--verbose", action="store_true", help="log detalhado")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in (
        "urllib3",
        "requests_oauthlib",
        "oauthlib",
        "googleapiclient",
        "google_auth_httplib2",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2

    creds = load_credentials(config.credentials_file, config.token_file)
    calendar_service, drive_service = build_services(creds)

    token = capture_graph_token(
        config.session_dir, config.token_wait_seconds, config.token_settle_seconds
    )
    if not token:
        log.error(
            "Token não capturado. Se o login travou, remova '%s' e tente novamente.",
            config.session_dir,
        )
        return 1
    graph = GraphClient(token)

    exit_code = 0
    try:
        if not args.skip_calendar:
            stats = AssignmentCalendarSync(graph, calendar_service, config.calendar).run()
            log.info(
                "Agenda: %d criados, %d atualizados, %d sem mudança",
                stats.created,
                stats.updated,
                stats.unchanged,
            )
        if not args.skip_files:
            mirror = TeamsToDriveMirror(graph, drive_service, config.drive_folder_id)
            for course, group_id in config.courses.items():
                mirror.sync_course(course, group_id)
            s = mirror.stats
            log.info(
                "Drive: %d enviados, %d já existiam, %d falhas", s.uploaded, s.skipped, s.failed
            )
            if s.failed:
                exit_code = 1
    except GraphError as exc:
        log.error("Falha na Graph API: %s", exc)
        return 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
