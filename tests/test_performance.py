"""The low-end preset in autoexec.cfg and the mod size report."""

from __future__ import annotations

import pytest

from helpers import make_game
from sapphire import crosshair as ch
from sapphire import performance as perf
from sapphire.library import InstalledMod, StoredFile, StoredVpk


@pytest.fixture
def game(tmp_path):
    g = make_game(tmp_path / "lib")
    ch.autoexec_path(g).parent.mkdir(parents=True, exist_ok=True)
    return g


def test_preset_is_added_and_removed_without_touching_the_rest(game):
    ch.write_autoexec(game, "fps_max 240\n// mine\n")
    assert not perf.preset_applied(game)
    saved = perf.apply_preset(game)
    assert perf.preset_applied(game)
    assert saved.startswith("fps_max 240\n// mine\n")
    for cmd, _ in perf.PRESET:
        assert cmd in saved
    perf.remove_preset(game)
    assert ch.read_autoexec(game) == "fps_max 240\n// mine\n"


def test_preset_goes_last_so_it_wins_over_earlier_lines(game):
    ch.write_autoexec(game, "fps_max_ui 200\n")
    saved = perf.apply_preset(game)
    assert saved.index("fps_max_ui 200") < saved.index("fps_max_ui 30")


def test_applying_twice_keeps_one_copy(game):
    perf.apply_preset(game)
    saved = perf.apply_preset(game)
    assert saved.count(perf.BEGIN) == 1 and saved.count(perf.END) == 1


def test_removal_never_leaves_an_empty_file(game):
    perf.apply_preset(game)
    saved = perf.remove_preset(game)
    assert saved.strip() and not perf.preset_applied(game)    # empty + +exec autoexec can crash the game


def test_missing_autoexec_is_fine(game):
    assert not perf.preset_applied(game)
    assert perf.apply_preset(game).startswith(perf.BEGIN)


def test_half_deleted_block_keeps_the_players_lines(game):
    ch.write_autoexec(game, f"fps_max 240\n{perf.BEGIN}\nbind x y\n")
    saved = perf.apply_preset(game)
    assert "fps_max 240" in saved and "bind x y" in saved and saved.count(perf.BEGIN) == 1


def test_windows_line_endings_still_remove_cleanly(game):
    perf.apply_preset(game)
    p = ch.autoexec_path(game)
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert perf.preset_applied(game)
    assert perf.BEGIN not in perf.remove_preset(game)


def _mod(tmp_path, monkeypatch, uid, name, sizes, enabled=True, off_sizes=()):
    monkeypatch.setattr("sapphire.paths.library_dir", lambda: tmp_path / "library")
    folder = tmp_path / "library" / uid
    folder.mkdir(parents=True, exist_ok=True)

    def vpk(label, size, active):
        path = folder / f"{label}.vpk"
        path.write_bytes(b"x" * size)
        return StoredVpk(label, [StoredFile(path.name)], active=active)

    vpks = [vpk(f"on{i}", s, True) for i, s in enumerate(sizes)]
    vpks += [vpk(f"off{i}", s, False) for i, s in enumerate(off_sizes)]
    return InstalledMod(uid, name, vpks=vpks, enabled=enabled)


def test_weights_count_active_variants_only_and_sort_biggest_first(tmp_path, monkeypatch):
    small = _mod(tmp_path, monkeypatch, "a", "Small", [10], off_sizes=[5000])
    big = _mod(tmp_path, monkeypatch, "b", "Big", [100, 50])
    off = _mod(tmp_path, monkeypatch, "c", "Off", [9000], enabled=False)
    weights = perf.mod_weights([small, big, off])
    assert [(w.name, w.size) for w in weights] == [("Big", 150), ("Small", 10)]


def test_weight_reports_missing_files(tmp_path, monkeypatch):
    mod = _mod(tmp_path, monkeypatch, "a", "Gone", [10, 20])
    mod.file_path(mod.vpks[0].files[0]).unlink()
    w = perf.mod_weight(mod)
    assert w.size == 20 and w.missing == 1
