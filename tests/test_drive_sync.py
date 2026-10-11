from automacao_fatec.drive_sync import DriveFolders, escape_query_value


def test_escape_query_value():
    assert escape_query_value("O'Reilly") == "O\\'Reilly"
    assert escape_query_value("a\\b") == "a\\\\b"
    assert escape_query_value("a\\'b") == "a\\\\\\'b"


class FakeFiles:
    def __init__(self, pages):
        self.pages = list(pages)
        self.list_calls = 0

    def list(self, **kwargs):
        self.list_calls += 1
        page = self.pages.pop(0)
        return type("Req", (), {"execute": lambda _self: page})()


class FakeService:
    def __init__(self, pages):
        self._files = FakeFiles(pages)

    def files(self):
        return self._files


def test_children_pagina_e_usa_cache():
    service = FakeService(
        [
            {"files": [{"id": "1", "name": "a.pdf"}], "nextPageToken": "t"},
            {"files": [{"id": "2", "name": "b.pdf"}]},
        ]
    )
    folders = DriveFolders(service)
    assert folders.children("root") == {"a.pdf": "1", "b.pdf": "2"}
    folders.children("root")
    assert service.files().list_calls == 2
