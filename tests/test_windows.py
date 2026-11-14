"""The Windows code paths, exercised on Linux by flipping the platform flags.

They cover what differs on Windows: where Sapphire keeps its files, finding
Steam and Deadlock from the registry, and reading whether the game is running.
"""

from __future__ import annotations

import pytest

from sapphire import paths, steam


# --------------------------------------------------------------------- paths
def test_windows_dirs_use_appdata(tmp_path, monkeypatch):
    monkeypatch.delenv("SAPPHIRE_HOME", raising=False)
    monkeypatch.setattr(paths, "WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert paths.data_dir() == tmp_path / "Roaming" / "Sapphire"
    assert paths.cache_dir() == tmp_path / "Local" / "Sapphire" / "cache"
    assert paths.state_file() == tmp_path / "Roaming" / "Sapphire" / "state.json"
    assert paths.library_dir().is_dir() and paths.downloads_dir().is_dir()


def test_sapphire_home_wins_even_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "WINDOWS", True)
    monkeypatch.setenv("SAPPHIRE_HOME", str(tmp_path / "portable"))
    assert paths.data_dir() == tmp_path / "portable"
    assert paths.cache_dir() == tmp_path / "portable" / "cache"


# --------------------------------------------------------------------- steam
def _fake_steam(root, drive="D"):
    """A Windows-shaped Steam tree with Deadlock in a second library folder."""
    (root / "steamapps").mkdir(parents=True)
    lib = root.parent / "SteamLibrary"
    (lib / "steamapps" / "common" / "Deadlock" / "game" / "citadel").mkdir(parents=True)
    (lib / "steamapps" / "common" / "Deadlock" / "game" / "citadel" / "gameinfo.gi").write_text("x")
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n'
        f'  "0" {{ "path" "{str(root).replace(chr(92), "/")}" }}\n'
        f'  "1" {{ "path" "{str(lib).replace(chr(92), "/")}" }}\n'
        "}\n")
    (lib / "steamapps" / "appmanifest_1422450.acf").write_text(
        '"AppState"\n{\n  "appid" "1422450"\n  "installdir" "Deadlock"\n}\n')
    return lib / "steamapps" / "common" / "Deadlock"


def test_finds_steam_and_deadlock_from_the_registry(tmp_path, monkeypatch):
    steam_root = tmp_path / "Program Files (x86)" / "Steam"
    game = _fake_steam(steam_root)
    monkeypatch.setattr(steam, "WINDOWS", True)
    monkeypatch.setattr(steam, "_registry_steam_paths", lambda: [steam_root])
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)

    assert steam.steam_roots() == [steam_root.resolve()]
    assert steam.find_deadlock() == game
    assert steam.is_valid_game_dir(game)


def test_running_app_and_game_running_from_registry(monkeypatch):
    # (is_game_running itself is stubbed out by the test harness, so drive the
    # real Windows branch directly.)
    monkeypatch.setattr(steam, "WINDOWS", True)
    monkeypatch.setattr(steam, "_windows_running_app", lambda: "1422450")
    assert steam.steam_running_app() == "1422450"
    assert steam._windows_game_running() is True

    monkeypatch.setattr(steam, "_windows_running_app", lambda: None)
    # nothing running and tasklist shows no Deadlock
    monkeypatch.setattr(steam.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "system idle process\n"})())
    assert steam._windows_game_running() is False

    monkeypatch.setattr(steam.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "deadlock.exe,1234,Console\n"})())
    assert steam._windows_game_running() is True


def test_registry_reader_is_empty_without_winreg(monkeypatch):
    # On a machine with no winreg (i.e. Linux) the reader simply finds nothing.
    import builtins
    real_import = builtins.__import__

    def no_winreg(name, *a, **k):
        if name == "winreg":
            raise ImportError("no winreg here")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_winreg)
    assert steam._registry_steam_paths() == []
    assert steam._windows_running_app() is None


def test_linux_modules_import_even_when_fcntl_is_missing():
    # The background helper must import on Windows (no fcntl) without blowing up.
    from sapphire import helper
    assert hasattr(helper, "SUPPORTED")
    # enable() refuses cleanly rather than crashing when unsupported.
    if not helper.SUPPORTED:
        with pytest.raises(RuntimeError):
            helper.enable()
