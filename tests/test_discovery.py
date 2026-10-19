from __future__ import annotations

from dji_importer import discovery


def test_manual_scan_ignores_non_mp4(tmp_path):
    (tmp_path / "DJI_0001.MP4").write_bytes(b"x")
    (tmp_path / "DJI_0001.LRF").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "DJI_0002.mp4").write_bytes(b"x")

    files = discovery.iter_manual_files(tmp_path)
    assert {p.name for p in files} == {"DJI_0001.MP4", "DJI_0002.mp4"}


def test_find_sources_detects_dji_mount(tmp_path, monkeypatch):
    mount = tmp_path / "Pocket4"
    dcim = mount / "DCIM" / "DJI_001"
    dcim.mkdir(parents=True)
    (dcim / "DJI_0001.MP4").write_bytes(b"x")

    monkeypatch.setattr(discovery, "_MOUNT_ROOTS", (tmp_path,))
    sources = discovery.find_sources()
    assert len(sources) == 1
    assert sources[0].mount_point == mount
    assert sources[0].display_name == "Pocket4"


def test_plain_mp4_drive_is_not_a_dji_source(tmp_path, monkeypatch):
    mount = tmp_path / "USBSTICK"
    dcim = mount / "DCIM"
    dcim.mkdir(parents=True)
    (dcim / "holiday.mp4").write_bytes(b"x")

    monkeypatch.setattr(discovery, "_MOUNT_ROOTS", (tmp_path,))
    assert discovery.find_sources() == []
