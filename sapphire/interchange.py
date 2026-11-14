"""Exporting a profile as a Deadlock Mod Interchange bundle (RFC 001), the
manager-neutral format Deadlock Mod Manager and Grimoire both read.

Sapphire already *reads* DMM's and Grimoire's native data (see importers.py);
this is the other direction, written in the shared format so DMM can import a
Sapphire profile. A bundle is a folder:

    <bundle>/
      mod-interchange.json
      files/<NNNN-slug>/<file>.vpk

The document lists every mod once (the library), with each exported profile in
`profiles`. File paths are relative to the folder, forward-slashed, and never
leave it. The format is specified in Deadlock Mod Manager's
rfcs/001-mod-interchange/proposal.md; this writer matches version 1.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from sapphire.library import InstalledMod, Library, StoredVpk
from sapphire.vpk import PAK_NAME_RE

log = logging.getLogger(__name__)

FORMAT_ID = "deadlock-mod-interchange"
FORMAT_VERSION = 1
MANIFEST_FILENAME = "mod-interchange.json"
MANAGER_ID = "sapphire"


class ExportError(Exception):
    pass


@dataclass
class SkippedMod:
    uid: str
    name: str
    reason: str


@dataclass
class ExportReport:
    bundle_path: Path
    exported: int = 0
    profiles: int = 0
    skipped: list[SkippedMod] = field(default_factory=list)


def slugify(value: str, max_len: int = 40) -> str:
    """Lowercase, filesystem-safe slug (matches DMM's format::slugify): ASCII
    alphanumerics kept, every other run becomes one '_', trimmed, cut to length."""
    out: list[str] = []
    last_dash = True
    for ch in value:
        if ch.isascii() and ch.isalnum():
            out.append(ch.lower())
            last_dash = False
        elif not last_dash:
            out.append("_")
            last_dash = True
        if len(out) >= max_len:
            break
    return "".join(out).strip("_")


def is_plain_vpk_name(name: str) -> bool:
    """True for a stock pakNN_dir.vpk / pakNN_NNN.vpk name (kept as-is on export)."""
    return bool(PAK_NAME_RE.match(name))


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError as exc:
        log.warning("couldn't hash %s: %s", path, exc)
        return None


def _mod_key(mod: InstalledMod, primary_sha: str | None) -> str:
    """A document-stable key: gamebanana:mod:<id> / gamebanana:sound:<id>, or
    local:sha256:<hex> (so the same file dedupes on import) falling back to the uid."""
    if mod.source == "gamebanana" and mod.gb_id:
        kind = "sound" if mod.model == "Sound" else "mod"
        return f"gamebanana:{kind}:{mod.gb_id}"
    if primary_sha:
        return f"local:sha256:{primary_sha}"
    return f"local:{mod.uid}"


def _origin(mod: InstalledMod) -> dict:
    if mod.source == "gamebanana" and mod.gb_id:
        origin = {
            "provider": "gamebanana",
            "submissionType": "sound" if mod.model == "Sound" else "mod",
            "submissionId": str(mod.gb_id),
        }
        if mod.file_id:
            origin["fileId"] = int(mod.file_id)
        if mod.file_name:
            origin["fileName"] = mod.file_name
        return origin
    return {"provider": "local", "localId": mod.uid}


def _entry_stem(vpk: StoredVpk, slug: str, used: set[str]) -> str:
    """A unique VPK stem for this mod: the stock pakNN name when the variant has
    one, else the mod's slug; suffixed if two variants would collide."""
    base = Path(vpk.label).name
    if is_plain_vpk_name(base) and base.lower().endswith("_dir.vpk"):
        stem = base[: -len("_dir.vpk")]
    else:
        stem = slug or "mod"
    candidate, n = stem, 2
    while candidate.lower() in used:
        candidate = f"{stem}_{n}"
        n += 1
    used.add(candidate.lower())
    return candidate


def _copy_mod_files(mod: InstalledMod, folder: Path, rel_prefix: str) -> list[dict]:
    """Copy a mod's VPKs into `folder`, returning interchange `files` entries.
    Chunks are named <stem>_<chunk>.vpk so importers group them with their main."""
    files: list[dict] = []
    stems: set[str] = set()
    slug = slugify(mod.name)
    for vpk in mod.vpks:
        try:
            main = vpk.main
        except StopIteration:
            continue
        src_main = mod.file_path(main)
        if not src_main.is_file():
            continue
        stem = _entry_stem(vpk, slug, stems)
        # main first, then chunks, so the _dir.vpk anchors the group
        ordered = [main] + [f for f in vpk.files if f.chunk is not None]
        for f in ordered:
            name = f"{stem}_dir.vpk" if f.chunk is None else f"{stem}_{f.chunk}.vpk"
            src = mod.file_path(f)
            if not src.is_file():
                continue
            dst = folder / name
            shutil.copy2(src, dst)
            entry = {"name": name, "path": f"{rel_prefix}/{name}"}
            sha = _sha256(dst)
            if sha:
                entry["sha256"] = sha
            try:
                entry["size"] = dst.stat().st_size
            except OSError:
                pass
            if f.chunk is None:            # only the main carries selected
                entry["selected"] = bool(vpk.active)
            files.append(entry)
    return files


def export_bundle(lib: Library, dest_dir: Path | str, profile_names: list[str] | None = None,
                  manager_version: str = "", progress=None) -> ExportReport:
    """Write a bundle under `dest_dir` for the given profiles (default: the active
    one). The first profile's on/off and order become the library-level state."""
    from sapphire import __version__
    manager_version = manager_version or __version__
    names = profile_names or ([lib.active_profile] if lib.active_profile else [])
    names = [n for n in names if n in lib.profiles]
    if not names:
        raise ExportError("No profile to export.")

    # Live state lives in `members`/`order`, not the stored entries, until a save.
    lib._sync_active()
    # Union of mods across the chosen profiles, in the first profile's order first.
    order: list[str] = []
    seen: set[str] = set()
    enabled_in_first: dict[str, bool] = {}
    for i, name in enumerate(names):
        for uid, on in lib.profiles[name].entries:
            if uid in lib.mods and uid not in seen:
                seen.add(uid)
                order.append(uid)
            if i == 0:
                enabled_in_first[uid] = bool(on)

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bundle = dest_dir / f"deadlock-mods-export-{stamp}"
    n = 2
    while bundle.exists():
        bundle = dest_dir / f"deadlock-mods-export-{stamp}-{n}"
        n += 1
    (bundle / "files").mkdir(parents=True)

    report = ExportReport(bundle_path=bundle)
    key_by_uid: dict[str, str] = {}
    doc_mods: list[dict] = []
    total = len(order)
    for index, uid in enumerate(order):
        mod = lib.mods[uid]
        if progress:
            progress(mod.name, index, total)
        primary = next((v for v in mod.vpks), None)
        primary_src = mod.file_path(primary.main) if primary else None
        primary_sha = _sha256(primary_src) if primary_src and primary_src.is_file() else None
        slug = slugify(mod.name) or "mod"
        folder_rel = f"files/{index:04d}-{slug}"
        folder = bundle / folder_rel
        folder.mkdir(parents=True, exist_ok=True)
        files = _copy_mod_files(mod, folder, folder_rel)
        if not files:
            shutil.rmtree(folder, ignore_errors=True)
            report.skipped.append(SkippedMod(uid, mod.name, "no VPK files on disk"))
            continue
        key = _mod_key(mod, primary_sha)
        key_by_uid[uid] = key
        entry = {
            "key": key,
            "name": mod.name,
            "enabled": bool(enabled_in_first.get(uid, False)),
            "order": len(doc_mods),
            "origin": _origin(mod),
            "author": mod.author or None,
            "description": None,
            "category": mod.category or None,
            "hero": None,
            "thumbnailUrl": mod.thumb_url if mod.thumb_url.startswith("http") else None,
            "link": mod.url if mod.url.startswith("http") else None,
            "nsfw": bool(mod.nsfw),
            "files": files,
            "extensions": {MANAGER_ID: {"uid": mod.uid}},
        }
        doc_mods.append(entry)
    if progress:
        progress("", total, total)

    doc_profiles = []
    for name in names:
        prof = lib.profiles[name]
        pmods = []
        o = 0
        for uid, on in prof.entries:
            key = key_by_uid.get(uid)
            if key is None:
                continue
            pmods.append({"modKey": key, "enabled": bool(on), "order": o})
            o += 1
        doc_profiles.append({
            "key": f"profile:{slugify(name) or name}",
            "name": name,
            "active": name == lib.active_profile,
            "description": None,
            "mods": pmods,
            "crosshairKey": None,
            "autoexec": None,
        })

    document = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": {"manager": MANAGER_ID, "managerVersion": manager_version,
                   "profileName": names[0]},
        "contents": ["mods", "profiles"],
        "mods": doc_mods,
        "profiles": doc_profiles,
        "crosshairs": [],
        "warnings": [f"“{s.name}”: {s.reason}" for s in report.skipped],
    }
    (bundle / MANIFEST_FILENAME).write_text(
        json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    report.exported = len(doc_mods)
    report.profiles = len(doc_profiles)
    log.info("exported %d mods, %d profile(s) to %s", report.exported, report.profiles, bundle)
    return report
