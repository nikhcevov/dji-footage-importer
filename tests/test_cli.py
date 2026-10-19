from __future__ import annotations

from dji_importer import cli


def test_cli_import_then_verify(xdg, make_clip, tmp_path):
    src = tmp_path / "src"
    make_clip(src, name="DJI_20260925170001_0001_D.MP4", duration=0.4)
    make_clip(src, name="DJI_20260925170002_0002_D.MP4", duration=0.7)

    assert cli.main(["import", "--source", str(src)]) == 0
    assert cli.main(["verify"]) == 0
    # A second import has nothing new and still succeeds.
    assert cli.main(["import", "--source", str(src)]) == 0


def test_cli_import_missing_source(xdg, tmp_path):
    assert cli.main(["import", "--source", str(tmp_path / "nope")]) == 2


def test_cli_without_command_prints_help(xdg):
    assert cli.main([]) == 2
