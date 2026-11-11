from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QPlainTextEdit

from ... import REPO, theme
from ...core import firmware as fw
from ...core.paths import user_home
from ...core.sources import list_serial_ports
from ..widgets import Card, View, button, hbox, label, vbox


class FirmwareView(View):
    title = "Firmware"
    subtitle = "Put new firmware on the DAQ. No Pico SDK or VS Code needed."
    refresh_every = 10
    log_line = Signal(str)
    release_found = Signal(object)
    done = Signal(bool)

    def __init__(self, hub):
        super().__init__(hub)
        self.uf2: Path | None = None
        self.release = None
        self.busy = False

        pick = Card("1. Choose the firmware")
        self.rel_text = label("Press 'Look for the latest' to check GitHub, or choose a .uf2 file from this laptop.",
                              "dim", wrap=True)
        self.file_text = label("No firmware chosen yet.", wrap=True)
        self.file_text.setStyleSheet("font-size: 14px;")
        pick.add(self.file_text)
        pick.add(self.rel_text)
        pick.add(hbox(button("Look for the latest on GitHub", self._fetch, "primary",
                             f"Checks the Releases of {REPO} for a .uf2"),
                      button("Choose a file...", self._choose), None))

        steps = Card("2. Put the DAQ into update mode")
        steps.add(label(
            "1. Unplug the DAQ from USB (and switch the car off).\n"
            "2. Hold down the white BOOTSEL button on the Pico.\n"
            "3. Still holding it, plug the USB cable into the laptop. Then let go.\n"
            "4. The Pico shows up as a small USB drive called RP2350. It's found automatically below.",
            wrap=True))
        self.drive_text = label("", wrap=True)
        self.drive_text.setStyleSheet("font-size: 14px; font-weight: 600;")
        steps.add(self.drive_text)

        go = Card("3. Flash")
        self.flash_btn = button("Flash the DAQ", self._flash, "primary")
        self.flash_btn.setEnabled(False)
        self.flash_hint = label("", "dim", wrap=True)
        go.add(hbox(self.flash_btn, self.flash_hint, None))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("What happens during flashing shows up here.")
        go.add(self.log, 1)

        self.root.addWidget(pick)
        self.root.addWidget(steps)
        self.root.addWidget(go, 1)
        self.log_line.connect(self.log.appendPlainText)
        self.release_found.connect(self._on_release)
        self.done.connect(self._on_done)
        self.drives: list = []

    def _say(self, text: str):
        self.log_line.emit(time.strftime("%H:%M:%S  ") + text)

    def _choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the firmware", str(Path.home()), "Pico firmware (*.uf2)")
        if path:
            self._set_file(Path(path), "chosen from this laptop")

    def _set_file(self, path: Path, where: str):
        problem = fw.check_uf2(path)
        if problem:
            self.hub.notice.emit("warn", problem)
            return
        self.uf2 = path
        self.file_text.setText(f"{path.name}   ({path.stat().st_size / 1024:.0f} KB, {where})")
        self.refresh()

    def _fetch(self):
        self.rel_text.setText("Checking GitHub...")

        def work():
            try:
                rel = fw.latest_firmware(fw.list_releases())
                if rel is None:
                    self.release_found.emit("none")
                    return
                dest = user_home() / "firmware" / rel["name"]
                fw.download(rel["url"], dest)
                rel["path"] = str(dest)
                self.release_found.emit(rel)
            except Exception as exc:
                self.release_found.emit(exc)
        threading.Thread(target=work, daemon=True).start()

    def _on_release(self, rel):
        if rel == "none":
            self.rel_text.setText("There's no .uf2 on GitHub Releases yet. Build it (see the repo's "
                                  "Build-and-Deploy wiki page) and use 'Choose a file...'.")
        elif isinstance(rel, Exception):
            self.rel_text.setText("Couldn't reach GitHub Releases (no internet, or the repo is private). "
                                  f"Use 'Choose a file...' instead.  ({rel})")
        else:
            self.release = rel
            self.rel_text.setText(f"Latest release: {rel['tag']}, published {rel['published']}.")
            self._set_file(Path(rel["path"]), f"release {rel['tag']}")

    def _flash(self):
        if self.busy or not self.uf2 or not self.drives:
            return
        if self.hub.kind == "daq" and self.hub.state != "disconnected":
            self.hub.disconnect_source()
        drive, desc = self.drives[0]
        self.busy = True
        self.flash_btn.setEnabled(False)
        before = {p for p, _ in list_serial_ports()}
        uf2 = self.uf2

        def work():
            try:
                self._say(f"Copying {uf2.name} to {drive} ...")
                try:
                    fw.flash(uf2, drive)
                except OSError as exc:
                    if Path(drive).exists():
                        raise
                    self._say(f"(The drive vanished while finishing the copy, which is normal: {exc})")
                self._say("Copied. The Pico restarts by itself. Waiting for it to come back...")
                end = time.time() + 15
                port = None
                while time.time() < end and port is None:
                    time.sleep(0.5)
                    new = [p for p, _ in list_serial_ports() if p not in before]
                    port = new[0] if new else None
                if port is None:
                    ports = [p for p, _ in list_serial_ports()]
                    if not ports:
                        self._say("The drive has gone, so the firmware was accepted, but no COM port appeared. "
                                  "Unplug and replug the DAQ, then connect with 'DAQ over USB' to check it.")
                        self.done.emit(False)
                        return
                    port = ports[-1]
                self._say(f"Found the DAQ on {port}. Reading its startup messages...")
                import serial
                seen = False
                end = time.time() + 10
                with serial.Serial(port, 115200, timeout=0.3) as ser:
                    while time.time() < end:
                        line = ser.readline().decode("utf-8", "replace").strip()
                        if not line:
                            continue
                        if line.startswith(("Core 0:", "Core 1:", "CAN:", "GPS", "[TX]", "[CAN]", "[ECU]", "[GPS]")):
                            self._say("DAQ says: " + line)
                            seen = True
                            if line.startswith("["):
                                break
                self._say("Done. The DAQ booted with the new firmware." if seen else
                          "The DAQ is back but didn't print anything. Connect with 'DAQ over USB' to check it.")
                self.done.emit(seen)
            except Exception as exc:
                self._say(f"Something went wrong: {exc}")
                self.done.emit(False)
        threading.Thread(target=work, daemon=True).start()

    def _on_done(self, ok: bool):
        self.busy = False
        self.hub.notice.emit("info" if ok else "warn",
                             "DAQ flashed and running." if ok else "Flashing finished, but check the log.")
        self.refresh()

    def refresh(self) -> None:
        if self.busy:
            return
        self.drives = fw.find_pico_drives()
        if self.drives:
            drive, desc = self.drives[0]
            ok = fw.is_rp2350(desc)
            self.drive_text.setText(f"✔  Found the Pico: {drive}  ({desc})" if ok else
                                    f"Found a Pico at {drive}, but it says '{desc}', not RP2350. Is it the right board?")
            self.drive_text.setStyleSheet("font-size: 14px; font-weight: 600; color: %s;" %
                                          (theme.GREEN_BRIGHT if ok else theme.AMBER))
        else:
            self.drive_text.setText("○  No Pico in update mode yet. Follow the steps above.")
            self.drive_text.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {theme.TEXT_DIM};")
        ready = bool(self.uf2 and self.drives)
        self.flash_btn.setEnabled(ready)
        self.flash_hint.setText("" if ready else ("Choose the firmware first." if not self.uf2 else
                                                  "Waiting for the Pico to show up as a drive."))
