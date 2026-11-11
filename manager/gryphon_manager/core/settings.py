from __future__ import annotations

import copy
import json

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
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
        except (OSError, ValueError):
            return
        for k, v in stored.items():
            if v is not None or k not in DEFAULTS:
                self.data[k] = v

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2)
        except OSError:
            pass

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))
