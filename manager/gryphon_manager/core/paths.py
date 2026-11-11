from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def bundled_config_path() -> Path:
    return app_root() / "config" / "channels.yaml"


def asset_path(name: str) -> Path:
    if is_frozen():
        return app_root() / "gryphon_manager" / "assets" / name
    return Path(__file__).resolve().parents[1] / "assets" / name


def user_home() -> Path:
    override = os.environ.get("GRYPHON_HOME")
    if override:
        return Path(override)
    return Path.home() / "Documents" / "Gryphon Manager"


def sessions_dir() -> Path:
    p = user_home() / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def reports_dir() -> Path:
    p = user_home() / "test reports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_path() -> Path:
    p = user_home()
    p.mkdir(parents=True, exist_ok=True)
    return p / "settings.json"


def active_config_path() -> Path:
    if not is_frozen():
        return bundled_config_path()
    target = user_home() / "config" / "channels.yaml"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(bundled_config_path().read_text(encoding="utf-8"), encoding="utf-8")
    return target
