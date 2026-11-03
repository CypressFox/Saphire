"""The Performance page: a removable low-end preset and a list of mods by size."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from sapphire import performance as perf
from sapphire.ui import theme
from sapphire.ui.dialogs import error, human_size


class PerformancePage(QWidget):
    status = Signal(str)

    def __init__(self, manager):
        super().__init__()
        self.mgr = manager
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(8)
        title = QLabel("Performance")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        heading = QLabel("Low-end preset (experimental)")
        heading.setObjectName("SideTitle")
        root.addWidget(heading)
        commands = "; ".join(cmd for cmd, _ in perf.PRESET)
        hint = QLabel(f"Adds {commands} to autoexec.cfg. The rest of the file stays as it is, and you can remove "
                      "the preset at any time. Its effect on FPS hasn't been measured, and lowering the game's own "
                      "graphics settings is likely to help more. Deadlock only reads autoexec.cfg when its Steam "
                      f"launch options include {perf.LAUNCH_OPTION}, and the change applies the next time it starts.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        row = QHBoxLayout()
        self.toggle_btn = QPushButton()
        self.toggle_btn.setProperty("kind", "primary")
        self.toggle_btn.clicked.connect(self.toggle_preset)
        copy = QPushButton("Copy launch option")
        copy.setToolTip(f"Copies {perf.LAUNCH_OPTION} to paste into Deadlock's Steam launch options")
        copy.clicked.connect(self.copy_launch_option)
        self.preset_state = QLabel()
        self.preset_state.setObjectName("Muted")
        row.addWidget(self.toggle_btn)
        row.addWidget(copy)
        row.addStretch(1)
        row.addWidget(self.preset_state)
        root.addLayout(row)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        root.addWidget(line)

        heading = QLabel("Mod sizes")
        heading.setObjectName("SideTitle")
        root.addWidget(heading)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setHeaderLabels(["Mod", "Size", "Share"])
        self.table.setUniformRowHeights(True)
        self.table.setColumnWidth(0, theme.px(420))
        root.addWidget(self.table, 1)
        self.refresh()

    def refresh(self):
        self._refresh_preset()
        self._refresh_sizes()

    def _refresh_preset(self):
        gd = self.mgr.game_dir
        on = bool(gd) and perf.preset_applied(gd)
        self.toggle_btn.setEnabled(bool(gd))
        self.toggle_btn.setText("Remove preset" if on else "Add preset")
        if not gd:
            self.preset_state.setText("Set your Deadlock folder in Settings first.")
        else:
            self.preset_state.setText("Preset is in autoexec.cfg" if on else "Preset isn't in autoexec.cfg")

    def _refresh_sizes(self):
        weights = perf.mod_weights(self.mgr.lib.visible())
        total = sum(w.size for w in weights)
        missing = sum(w.missing for w in weights)
        count = f"{len(weights)} mod{'' if len(weights) == 1 else 's'} on"
        text = (f"{count} in this profile, {human_size(total)} in total. Bigger mods often take more memory and "
                "loading time, but size doesn't tell you the effect on FPS. To compare, turn some off in Installed.")
        if missing:
            text += f" {missing} file{' is' if missing == 1 else 's are'} missing from the library."
        self.summary.setText(text)
        self.table.clear()
        for w in weights:
            share = f"{w.size / total:.0%}" if total else "–"
            self.table.addTopLevelItem(QTreeWidgetItem([w.name, human_size(w.size), share]))

    def toggle_preset(self):
        gd = self.mgr.game_dir
        if not gd:
            return
        adding = not perf.preset_applied(gd)
        try:
            perf.apply_preset(gd) if adding else perf.remove_preset(gd)
        except OSError as exc:
            error(self, "Couldn't save autoexec.cfg", str(exc))
            return
        self._refresh_preset()
        self.status.emit("Preset added. It applies the next time Deadlock starts." if adding
                         else "Preset removed. This applies the next time Deadlock starts.")

    def copy_launch_option(self):
        QGuiApplication.clipboard().setText(perf.LAUNCH_OPTION)
        self.status.emit(f"Copied {perf.LAUNCH_OPTION}.")
