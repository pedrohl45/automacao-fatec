import pytest

from automacao_fatec.config import ConfigError, load_config


def test_carrega_config_valida(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('drive_folder_id = "x"\n[courses]\n"A" = "g1"\n', encoding="utf-8")
    cfg = load_config(f)
    assert cfg.courses == {"A": "g1"}
    assert cfg.calendar.event_duration_hours == 2


def test_exige_disciplinas(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('drive_folder_id = "x"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(f)


def test_arquivo_ausente(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nao-existe.toml")
