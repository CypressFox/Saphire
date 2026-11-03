"""Help for low-end PCs: a removable autoexec.cfg preset and a report of mod sizes.

The preset lives between two marker lines in autoexec.cfg, so it can be taken out
again without touching anything else in the file. It goes at the end so it wins
over the same command earlier in the file, and that earlier value comes back when
the preset is removed.

The sizes are the mod files on disk. They're a rough guide to what a mod adds to
loading and memory, not a measurement of its effect on FPS.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

from sapphire import crosshair as ch
from sapphire.library import InstalledMod

log = logging.getLogger(__name__)

BEGIN = "// >>> Sapphire low-end preset (remove it from Sapphire's Performance page)"
END = "// <<< Sapphire low-end preset"
LAUNCH_OPTION = "+exec autoexec"

# (command, what it does). Only add a command once it has been tried in the game.
PRESET: list[tuple[str, str]] = [
    ("fps_max_ui 30", "Caps the frame rate in menus, so the PC does less work there"),
    ("cl_ragdoll_limit 0", "Turns off ragdolls"),
]

_BLOCK = re.compile(rf"(?:^|\n){re.escape(BEGIN)}\n.*?{re.escape(END)}(?=\n|$)", re.S)


def _without_preset(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = _BLOCK.sub("", text)
    # a half-deleted block: drop the stray marker lines, keep what the player wrote
    lines = [line for line in text.split("\n") if line.strip() not in (BEGIN, END)]
    return "\n".join(lines).lstrip("\n")


def preset_applied(game_dir) -> bool:
    return BEGIN in ch.read_autoexec(game_dir)


def apply_preset(game_dir) -> str:
    """Add the preset to the end of autoexec.cfg, replacing any older copy. Returns what was saved."""
    kept = _without_preset(ch.read_autoexec(game_dir)).rstrip("\n")
    block = "\n".join([BEGIN, *(cmd for cmd, _ in PRESET), END])
    return ch.write_autoexec(game_dir, f"{kept}\n{block}\n" if kept else f"{block}\n")


def remove_preset(game_dir) -> str:
    """Take the preset out and leave everything else. Returns what was saved."""
    return ch.write_autoexec(game_dir, _without_preset(ch.read_autoexec(game_dir)))


@dataclass(frozen=True)
class ModWeight:
    uid: str
    name: str
    size: int
    missing: int = 0   # files the library lists that aren't on disk


def mod_weight(mod: InstalledMod) -> ModWeight:
    """How big the variants this mod has switched on are; unused variants aren't loaded, so don't count."""
    size = missing = 0
    for vpk in mod.active_vpks:
        for f in vpk.files:
            try:
                size += mod.file_path(f).stat().st_size
            except OSError:
                missing += 1
    return ModWeight(mod.uid, mod.name, size, missing)


def mod_weights(mods: Iterable[InstalledMod]) -> list[ModWeight]:
    """Mods that are switched on, biggest first."""
    weights = [mod_weight(m) for m in mods if m.enabled]
    return sorted(weights, key=lambda w: (-w.size, w.name.lower()))
