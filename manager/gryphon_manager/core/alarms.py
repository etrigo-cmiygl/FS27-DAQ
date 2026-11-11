from __future__ import annotations

import copy
from dataclasses import dataclass

OPS = {"<": lambda a, b: a < b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b}

DEFAULT_RULES = [
    {"name": "Low oil pressure", "kind": "signal", "enabled": True, "signal": "oil_pressure", "op": "<",
     "value": 1.0, "cond_signal": "rpm", "cond_op": ">", "cond_value": 2000, "hold_s": 0.5, "sound": True},
    {"name": "Engine too hot", "kind": "signal", "enabled": True, "signal": "engine_temp", "op": ">",
     "value": 105.0, "cond_signal": "", "cond_op": ">", "cond_value": 0, "hold_s": 1.0, "sound": True},
    {"name": "Battery low", "kind": "signal", "enabled": True, "signal": "battery", "op": "<",
     "value": 11.5, "cond_signal": "battery", "cond_op": ">", "cond_value": 1.0, "hold_s": 2.0, "sound": False},
    {"name": "ECU missing", "kind": "device", "enabled": True, "device": "ecu", "seconds": 3.0, "sound": True},
    {"name": "DAQ missing", "kind": "device", "enabled": True, "device": "daq", "seconds": 3.0, "sound": False},
]


@dataclass
class AlarmEvent:
    ts: float
    name: str
    text: str
    raised: bool

    def as_dict(self) -> dict:
        return {"ts": self.ts, "name": self.name, "text": self.text, "raised": self.raised}


def describe_rule(rule: dict) -> str:
    if rule.get("kind") == "device":
        return f"{rule.get('device', '?')} missing for more than {rule.get('seconds', 3):g} s"
    text = f"{rule.get('signal', '?')} {rule.get('op', '<')} {rule.get('value', 0):g}"
    if rule.get("cond_signal"):
        text += f" while {rule['cond_signal']} {rule.get('cond_op', '>')} {rule.get('cond_value', 0):g}"
    return text


class AlarmManager:
    def __init__(self, rules: list | None = None):
        self.set_rules(rules)

    def set_rules(self, rules: list | None) -> None:
        self.rules = copy.deepcopy(rules) if rules is not None else copy.deepcopy(DEFAULT_RULES)
        self.reset()

    def reset(self) -> None:
        self.active: dict[str, str] = {}
        self.events: list[AlarmEvent] = []
        self._since: dict[str, float] = {}
        self.new_events: list[AlarmEvent] = []

    def evaluate(self, engine, now: float) -> None:
        for rule in self.rules:
            name = rule.get("name", "Alarm")
            if not rule.get("enabled", True):
                self._clear(name, now)
                continue
            tripped, text = self._test(rule, engine, now)
            if tripped:
                since = self._since.setdefault(name, now)
                if name not in self.active and now - since >= float(rule.get("hold_s", 0) or 0):
                    self.active[name] = text
                    self._log(AlarmEvent(now, name, text, True))
                elif name in self.active:
                    self.active[name] = text
            else:
                self._since.pop(name, None)
                self._clear(name, now)

    def _clear(self, name: str, now: float) -> None:
        if name in self.active:
            del self.active[name]
            self._log(AlarmEvent(now, name, "back to normal", False))

    def _log(self, ev: AlarmEvent) -> None:
        self.events.append(ev)
        self.new_events.append(ev)
        del self.events[:-500]

    def take_new(self) -> list[AlarmEvent]:
        out, self.new_events = self.new_events, []
        return out

    def _test(self, rule: dict, engine, now: float) -> tuple[bool, str]:
        if rule.get("kind") == "device":
            if not engine.can_expected:
                return False, ""
            dev = engine.devices.get(rule.get("device", ""))
            if dev is None or not dev.total_ids:
                return False, ""
            secs = float(rule.get("seconds", 3) or 3)
            if dev.last_seen:
                gone = now - dev.last_seen
            elif engine.connected_since:
                gone = now - engine.connected_since
            else:
                return False, ""
            if gone > secs:
                return True, f"{dev.label} not seen for {gone:.0f} s"
            return False, ""
        op = OPS.get(rule.get("op", "<"))
        value = engine.value(rule.get("signal", ""))
        if op is None or value is None:
            return False, ""
        if rule.get("cond_signal"):
            cop = OPS.get(rule.get("cond_op", ">"))
            cv = engine.value(rule["cond_signal"])
            if cop is None or cv is None or not cop(cv, float(rule.get("cond_value", 0))):
                return False, ""
        if op(value, float(rule.get("value", 0))):
            sig = engine.best(rule["signal"])
            return True, f"{sig.name if sig else rule['signal']} is {value:.2f} {sig.units if sig else ''}".strip()
        return False, ""
