from pathlib import Path

from typer.testing import CliRunner

from autodialectics.cli.main import app
from autodialectics.settings import Settings


runner = CliRunner()


def test_settings_load_from_cwd_config(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "autodialectics.yaml").write_text(
        "cliproxy_base_url: http://cwd.example\nmax_evidence_items: 11\n",
        encoding="utf-8",
    )

    settings = Settings.load()

    assert settings.cliproxy_base_url == "http://cwd.example"
    assert settings.max_evidence_items == 11



def test_settings_load_from_xdg_config(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AUTODIALECTICS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    config_dir = tmp_path / "xdg" / "autodialectics"
    config_dir.mkdir(parents=True)
    (config_dir / "autodialectics.yaml").write_text(
        "db_path: xdg.db\nartifacts_dir: xdg-artifacts\n",
        encoding="utf-8",
    )

    settings = Settings.load()

    assert settings.db_path == "xdg.db"
    assert settings.artifacts_dir == "xdg-artifacts"



def test_cli_accepts_global_config_option(tmp_path) -> None:
    config_path = tmp_path / "custom.yaml"
    db_path = tmp_path / "custom.db"
    artifacts_dir = tmp_path / "custom-artifacts"
    config_path.write_text(
        "\n".join(
            [
                f"db_path: {db_path}",
                f"artifacts_dir: {artifacts_dir}",
                "cliproxy_base_url: offline",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["--config", str(config_path), "init"])

    assert result.exit_code == 0, result.stdout
    assert str(db_path) in result.stdout
    assert str(artifacts_dir) in result.stdout
