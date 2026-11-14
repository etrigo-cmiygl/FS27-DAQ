from __future__ import annotations

import copy
import json
import os

from .alarms import DEFAULT_RULES
from .paths import settings_path

DEFAULTS = {
    "first_run_done": False,
    "source": "sim",
    "can_interface": "pcan",
    "can_channel": "PCAN_USBBUS1",
    "slcan_port": "",
    "receiver_port": "",
    "daq_port": "",
    "serial_baud": 115200,
    "allow_transmit": False,
    "auto_record": False,
    "log_format": "blf",
    "pressure_units": "bar",
    "temp_units": "C",
    "pit_wall": False,
    "text_size": 13,
    "alarm_sound": True,
    "check_updates": True,
    "pdm_ids": "",
    "lambda_ids": "",
    "screen_ids": "",
    "ecu_expected_hz": 10.0,
    "extra_dbcs": [],
    "id_labels": {},
    "graph_signals": ["rpm", "tps", "engine_temp"],
    "sim_mode": "drive",
    "sim_fault": "none",
    "sim_parts": "all",
    "accent": "#1E5C3A",
    "driver": "",
    "last_view": 0,
    "alarms": None,
}


class Settings:
    def __init__(self, path=None):
        self.path = path or settings_path()
        self.data = copy.deepcopy(DEFAULTS)
        self.data["alarms"] = copy.deepcopy(DEFAULT_RULES)
        self.load()

    def load(self) -> None:
        stored = None
        for path in (self.path, self.path.with_suffix(".bak")):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    stored = json.load(fh)
                if isinstance(stored, dict):
                    break
                stored = None
            except (OSError, ValueError):
                continue
        if not stored:
            return
        for k, v in stored.items():
            if v is not None or k not in DEFAULTS:
                self.data[k] = v

    def save(self) -> None:
        """Writes to a temporary file first, so a crash or power cut mid-save can't leave a broken file."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            if self.path.exists():
                try:
                    with open(self.path, "r", encoding="utf-8") as fh:
                        json.load(fh)
                    os.replace(self.path, self.path.with_suffix(".bak"))
                except (OSError, ValueError):
                    pass
            os.replace(tmp, self.path)
        except OSError:
            pass

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))
