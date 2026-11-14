"""Exporting a profile as a Deadlock Mod Interchange bundle (RFC 001).

The assertions here mirror what DMM's own `format::parse_document` enforces, so
a bundle that passes these is one DMM will accept: right format id and version,
non-empty unique keys, a valid origin per mod, and file paths that stay inside
the bundle and point at real VPKs.
"""

from __future__ import annotations

import json

import pytest

from sapphire import interchange
from sapphire.core import Manager
from sapphire.library import InstalledMod, Library, StoredFile, StoredVpk


def _mod(lib: Library, uid, name, *, gb_id=0, model="Mod", source="gamebanana",
         file_id=0, variants=(("pak01", ("dir", "000")),), member=True):
    """Add a mod with real files on disk under the library folder."""
    vpks = []
    for label_stem, chunks in variants:
        files = []
        for chunk in chunks:
            stored = f"{len(vpks):02d}_{label_stem}_{chunk}.vpk"
            files.append(StoredFile(stored=stored, chunk=None if chunk == "dir" else chunk))
        vpks.append(StoredVpk(label=f"{label_stem}_dir.vpk", files=files, active=True))
    mod = InstalledMod(uid=uid, name=name, source=source, model=model, gb_id=gb_id,
                       file_id=file_id, file_name=f"{name}.zip", author="someone",
                       category="Skins", url=f"https://gamebanana.com/mods/{gb_id}" if gb_id else "",
                       vpks=vpks)
    lib.add(mod, top=False, member=member)
    mod.folder.mkdir(parents=True, exist_ok=True)
    for v in mod.vpks:
        for f in v.files:
            mod.file_path(f).write_bytes(f"{uid}:{f.stored}".encode() * 32)
    return mod


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_bundle_has_the_dmm_shape(tmp_path):
    lib = Library()
    _mod(lib, "gb-Mod-650634", "QOL Lock", gb_id=650634, file_id=1720039)
    _mod(lib, "gb-Sound-42", "Boom pack", gb_id=42, model="Sound")
    lib.mods["gb-Mod-650634"].enabled = True
    lib.mods["gb-Sound-42"].enabled = False
    mgr = Manager(lib)

    report = mgr.export_interchange(tmp_path)
    assert report.exported == 2 and report.profiles == 1
    doc = _load(report.bundle_path / interchange.MANIFEST_FILENAME)

    assert doc["format"] == "deadlock-mod-interchange"
    assert doc["version"] == 1
    assert doc["source"]["manager"] == "sapphire"
    assert doc["contents"] == ["mods", "profiles"]
    keys = [m["key"] for m in doc["mods"]]
    assert keys == ["gamebanana:mod:650634", "gamebanana:sound:42"]
    assert len(keys) == len(set(keys))                       # unique, as the parser demands
    assert all(k.strip() for k in keys)                      # non-empty

    qol = doc["mods"][0]
    assert qol["origin"] == {"provider": "gamebanana", "submissionType": "mod",
                             "submissionId": "650634", "fileId": 1720039, "fileName": "QOL Lock.zip"}
    assert qol["enabled"] is True and qol["nsfw"] is False
    assert doc["mods"][1]["origin"]["submissionType"] == "sound"
    assert doc["mods"][1]["enabled"] is False
    # the active profile is carried, pointing only at keys in `mods`
    prof = doc["profiles"][0]
    assert prof["active"] is True
    assert {m["modKey"] for m in prof["mods"]} <= set(keys)


def test_files_are_real_grouped_and_inside_the_bundle(tmp_path):
    lib = Library()
    _mod(lib, "gb-Mod-7", "Chunky", gb_id=7, variants=(("pak01", ("dir", "000", "001")),))
    mgr = Manager(lib)
    doc = _load((report := mgr.export_interchange(tmp_path)).bundle_path / interchange.MANIFEST_FILENAME)
    base = report.bundle_path.resolve()

    files = doc["mods"][0]["files"]
    assert [f["name"] for f in files] == ["pak01_dir.vpk", "pak01_000.vpk", "pak01_001.vpk"]
    assert files[0]["selected"] is True                       # main carries selected
    assert "selected" not in files[1]                         # chunks don't
    for f in files:
        assert not f["path"].startswith("/") and ".." not in f["path"]   # relative, no escape
        on_disk = (report.bundle_path / f["path"]).resolve()
        assert on_disk.is_file() and on_disk.is_relative_to(base)
        assert len(f["sha256"]) == 64 and f["size"] > 0
    # chunks share the main's stem so an importer groups them together
    stems = {f["name"].rsplit("_", 1)[0] for f in files}
    assert stems == {"pak01"}


def test_local_mod_keys_on_file_hash_and_variants_stay_separate(tmp_path):
    lib = Library()
    _mod(lib, "local-abc", "My manual skin", source="local",
         variants=(("blue", ("dir",)), ("red", ("dir",))))
    mgr = Manager(lib)
    doc = _load((report := mgr.export_interchange(tmp_path)).bundle_path / interchange.MANIFEST_FILENAME)
    entry = doc["mods"][0]
    assert entry["origin"] == {"provider": "local", "localId": "local-abc"}
    assert entry["key"].startswith("local:sha256:")           # dedupe-friendly
    # two variants -> two distinct stems, all four-ish files present, unique names
    names = [f["name"] for f in entry["files"]]
    assert len(names) == len(set(names)) == 2
    assert all((report.bundle_path / f["path"]).is_file() for f in entry["files"])


def test_inactive_variant_is_kept_but_marked_unselected(tmp_path):
    lib = Library()
    _mod(lib, "gb-Mod-9", "Two tone", gb_id=9,
         variants=(("blue", ("dir",)), ("red", ("dir",))))
    lib.mods["gb-Mod-9"].vpks[1].active = False
    mgr = Manager(lib)
    doc = _load((r := mgr.export_interchange(tmp_path)).bundle_path / interchange.MANIFEST_FILENAME)
    # one main kept-and-on, one kept-but-off; both files still written
    mains = [f for f in doc["mods"][0]["files"] if "selected" in f]
    assert sorted(f["selected"] for f in mains) == [False, True]
    assert all((r.bundle_path / f["path"]).is_file() for f in doc["mods"][0]["files"])


def test_a_mod_with_no_files_is_skipped_not_fatal(tmp_path):
    lib = Library()
    good = _mod(lib, "gb-Mod-1", "Good", gb_id=1)
    ghost = _mod(lib, "gb-Mod-2", "Ghost", gb_id=2)
    # wipe the ghost's files on disk
    for v in ghost.vpks:
        for f in v.files:
            ghost.file_path(f).unlink()
    mgr = Manager(lib)
    report = mgr.export_interchange(tmp_path)
    doc = _load(report.bundle_path / interchange.MANIFEST_FILENAME)
    assert [m["key"] for m in doc["mods"]] == ["gamebanana:mod:1"]
    assert [s.uid for s in report.skipped] == ["gb-Mod-2"]
    assert any("Ghost" in w for w in doc["warnings"])
    # the skipped mod's folder isn't left behind in the bundle
    assert not any("ghost" in p.name.lower() for p in (report.bundle_path / "files").iterdir())


def test_export_a_named_non_active_profile(tmp_path):
    lib = Library()
    _mod(lib, "gb-Mod-1", "A", gb_id=1)
    _mod(lib, "gb-Mod-2", "B", gb_id=2)
    mgr = Manager(lib)
    mgr.new_profile("Kyle", copy=True)        # Kyle has both, active profile still Default
    report = mgr.export_interchange(tmp_path, names=["Kyle"])
    doc = _load(report.bundle_path / interchange.MANIFEST_FILENAME)
    assert doc["source"]["profileName"] == "Kyle"
    assert doc["profiles"][0]["name"] == "Kyle"
    assert doc["profiles"][0]["active"] is False
    assert {m["key"] for m in doc["mods"]} == {"gamebanana:mod:1", "gamebanana:mod:2"}


def test_slugify_matches_dmm_rules():
    assert interchange.slugify("QOL Lock") == "qol_lock"
    assert interchange.slugify("  weird!!name  ") == "weird_name"
    assert interchange.slugify("a" * 80, max_len=40) == "a" * 40
    assert interchange.slugify("***") == ""
    assert interchange.slugify("Café déjà") == "caf_d_j"      # non-ASCII dropped


def test_bundle_names_dont_collide(tmp_path):
    lib = Library()
    _mod(lib, "gb-Mod-1", "A", gb_id=1)
    mgr = Manager(lib)
    first = mgr.export_interchange(tmp_path).bundle_path
    second = mgr.export_interchange(tmp_path).bundle_path
    assert first != second and first.is_dir() and second.is_dir()
