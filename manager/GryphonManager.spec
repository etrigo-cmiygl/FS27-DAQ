# PyInstaller build: one folder, no console window.  pyinstaller --noconfirm GryphonManager.spec
import sys
from pathlib import Path

root = Path(SPECPATH)
icon = root / "gryphon_manager" / "assets" / "icon.ico"

a = Analysis(
    [str(root / "run.py")],
    pathex=[str(root)],
    datas=[
        (str(root / "config" / "channels.yaml"), "config"),
        (str(root / "gryphon_manager" / "assets"), "gryphon_manager/assets"),
    ],
    hiddenimports=[
        "can.interfaces.pcan", "can.interfaces.pcan.pcan", "can.interfaces.pcan.basic",
        "can.interfaces.slcan", "can.interfaces.virtual",
        "serial.tools.list_ports", "serial.tools.list_ports_windows",
        "cantools.database.can.formats.dbc",
    ],
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
              "PyQt5", "PyQt6", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="GryphonManager",
    console=False,
    icon=str(icon) if icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="GryphonManager")
