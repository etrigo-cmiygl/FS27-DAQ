from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime

from .. import __version__


@dataclass
class Check:
    label: str
    ok: bool | None
    detail: str = ""


@dataclass
class Step:
    key: str
    title: str
    intro: str
    inputs: list = field(default_factory=list)


STEPS = [
    Step("wiring", "Wiring and termination",
         "With the car's power OFF, measure the resistance between CAN H and CAN L with a multimeter "
         "(pins 7 and 2 on the debug port C41). Two 120 ohm terminators in parallel read about 60 ohm.\n"
         "Then plug the PCAN-USB into C41, switch the ignition on and press Connect.",
         [("ohms", "Multimeter reading (ohm)", "number")]),
    Step("ecu", "ECU present and rate OK",
         "Ignition on, engine off. The app looks for the FT550's nine frames and measures how often they arrive."),
    Step("engine_off", "Values sane with the engine off",
         "Ignition on, engine off, throttle closed. These should all look like a car that's sitting still."),
    Step("daq", "DAQ frames present",
         "The DAQ should be sending frames 0x600 to 0x603 about 20 times a second, with the same values as the ECU."),
    Step("screen", "Steering wheel screen",
         "Look at the steering wheel screen and tick what it shows correctly. Blip the throttle pedal to see "
         "the throttle value move.",
         [("scr_rpm", "RPM is shown (0 with the engine off)", "tick"),
          ("scr_temp", "Engine temp matches the app", "tick"),
          ("scr_tps", "Throttle moves when you press the pedal", "tick"),
          ("scr_map", "MAP reads about 101 kPa", "tick"),
          ("scr_gps", "GPS / satellites page shows a value", "tick")]),
    Step("running", "Engine running",
         "Start the engine and let it idle. Make sure the car is safe to run first: in neutral, "
         "nobody near the rear wheels, extinguisher to hand."),
    Step("ftmanager", "Compare with FTManager",
         "With FTManager connected to the ECU, type in what it shows. The app compares it with what it "
         "reads from the bus right now. Leave a box empty to skip it.",
         [("ft_rpm", "RPM in FTManager", "number"), ("ft_engine_temp", "Engine temp in FTManager (°C)", "number"),
          ("ft_tps", "TPS in FTManager (%)", "number"), ("ft_map", "MAP in FTManager (bar)", "number"),
          ("ft_oil_pressure", "Oil pressure in FTManager (bar)", "number")]),
]

FT_COMPARE = {"ft_rpm": ("rpm", "RPM", 150.0, 0.05), "ft_engine_temp": ("engine_temp", "Engine temp", 2.0, 0.0),
              "ft_tps": ("tps", "TPS", 2.0, 0.0), "ft_map": ("map", "MAP", 0.03, 0.0),
              "ft_oil_pressure": ("oil_pressure", "Oil pressure", 0.2, 0.05)}


def _num(inputs: dict, key: str):
    v = inputs.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _range(e, key: str, label: str, lo: float, hi: float, units: str, factor: float = 1.0) -> Check:
    v = e.value(key)
    if v is None:
        return Check(label, None, "no data")
    v *= factor
    ok = lo <= v <= hi
    return Check(label, ok, f"{v:.2f} {units} (expected {lo:g} to {hi:g})")


def evaluate(step: str, e, inputs: dict) -> list[Check]:
    """Live automatic checks for one step. ok=None means 'can't tell yet'."""
    out: list[Check] = []
    if step == "wiring":
        ohms = _num(inputs, "ohms")
        if ohms is None:
            out.append(Check("Termination resistance", None, "type in the multimeter reading"))
        elif 54 <= ohms <= 66:
            out.append(Check("Termination resistance", True, f"{ohms:g} ohm: two terminators, as it should be"))
        elif 100 <= ohms <= 135:
            out.append(Check("Termination resistance", False,
                             f"{ohms:g} ohm: only one terminator. Check C17/C20 and C52/C55."))
        elif 34 <= ohms <= 46:
            out.append(Check("Termination resistance", False,
                             f"{ohms:g} ohm: three terminators. Switch the DAQ board's own terminator off."))
        elif ohms > 1000:
            out.append(Check("Termination resistance", False,
                             f"{ohms:g} ohm: no terminators, or a broken CAN wire."))
        else:
            out.append(Check("Termination resistance", False, f"{ohms:g} ohm: expected about 60 ohm"))
        connected = e.can_expected and e.connected_since > 0
        out.append(Check("CAN cable connected", True if connected else None,
                         "adapter open, listening" if connected else "press Connect in the top bar"))
        if connected:
            st, text = e.bus_summary()
            out.append(Check("Bus has traffic and no errors", {"green": True, "grey": None}.get(st, False), text))
    elif step == "ecu":
        d = e.devices.get("ecu")
        if d is None or not d.last_seen:
            out.append(Check("ECU frames on the bus", None if not e.can_expected else False,
                             "none seen. Is the ignition on?"))
            return out
        out.append(Check("ECU frames on the bus", d.status != "red", d.text))
        out.append(Check("All 9 frames arriving", not d.missing, f"{d.seen_ids} of {d.total_ids}"))
        out.append(Check("Broadcast rate", e.ecu_check.status == "green", e.ecu_check.text))
    elif step == "engine_off":
        rpm = e.value("rpm")
        out.append(Check("RPM is 0", None if rpm is None else rpm == 0, "no data" if rpm is None else f"{rpm:.0f} rpm"))
        out.append(_range(e, "map", "MAP reads atmospheric", 95, 105, "kPa", 100.0))
        out.append(_range(e, "tps", "Throttle closed", -1, 5, "%"))
        out.append(_range(e, "engine_temp", "Engine temp believable", -10, 110, "°C"))
        out.append(_range(e, "air_temp", "Air temp believable", -10, 60, "°C"))
        out.append(_range(e, "oil_pressure", "No oil pressure", -0.1, 0.3, "bar"))
    elif step == "daq":
        d = e.devices.get("daq")
        if d is None or not d.last_seen:
            out.append(Check("DAQ frames 0x600-0x603", None if not e.can_expected else False,
                             "none seen. Is the DAQ powered?"))
            return out
        out.append(Check("DAQ frames 0x600-0x603", d.status != "red" and not d.missing,
                         f"{d.seen_ids} of {d.total_ids} arriving"))
        out.append(Check("About 20 a second", 15 <= d.rate <= 25, f"{d.rate:.1f} Hz"))
        for name, ev, dv, units, state in e.daq_check.rows:
            ok = {"green": True, "red": False}.get(state)
            detail = "waiting" if ev is None or dv is None else f"ECU {ev:.1f} / DAQ {dv:.1f} {units}"
            out.append(Check(f"{name} matches the ECU", ok, detail))
        batt = e.value("battery")
        if batt is not None and batt == 0:
            out.append(Check("Battery voltage", None, "reads 0: known gap, not in the FT550 simplified frames"))
    elif step == "screen":
        ticks = [k for k, _, kind in STEPS[4].inputs if kind == "tick"]
        done = sum(1 for k in ticks if inputs.get(k))
        out.append(Check("Screen values ticked", done == len(ticks), f"{done} of {len(ticks)}"))
        d = e.devices.get("daq")
        out.append(Check("DAQ is feeding the screen", None if d is None or not d.last_seen else d.status == "green",
                         d.text if d else ""))
    elif step == "running":
        rpm = e.value("rpm")
        out.append(Check("Engine is running", None if rpm is None else rpm > 500,
                         "no data" if rpm is None else f"{rpm:.0f} rpm"))
        out.append(_range(e, "oil_pressure", "Oil pressure", 1.0, 7.0, "bar"))
        out.append(_range(e, "fuel_pressure", "Fuel pressure", 2.0, 5.0, "bar"))
        out.append(_range(e, "lambda", "Lambda", 0.7, 1.3, "λ"))
        out.append(_range(e, "engine_temp", "Engine temp", 0, 105, "°C"))
        batt = e.value("battery")
        if batt is None or batt == 0:
            out.append(Check("Battery charging", None, "not measured yet"))
        else:
            out.append(Check("Battery charging", batt >= 13.0, f"{batt:.2f} V (expected 13 V or more)"))
    elif step == "ftmanager":
        any_typed = False
        for key, (sig, name, tol, rel) in FT_COMPARE.items():
            typed = _num(inputs, key)
            if typed is None:
                continue
            any_typed = True
            v = e.value(sig)
            if v is None:
                out.append(Check(name, None, f"FTManager {typed:g}, app has no data"))
                continue
            limit = max(tol, abs(typed) * rel)
            out.append(Check(name, abs(v - typed) <= limit,
                             f"FTManager {typed:g} / app {v:.2f} (allowed difference {limit:g})"))
        if not any_typed:
            out.append(Check("FTManager values", None, "type at least one value to compare"))
    return out


def suggest(checks: list[Check]) -> str:
    if any(c.ok is False for c in checks):
        return "fail"
    if checks and all(c.ok is True for c in checks):
        return "pass"
    return "pending"


def overall(results: dict) -> str:
    states = [results.get(s.key, {}).get("result", "pending") for s in STEPS]
    if "fail" in states:
        return "FAIL"
    if all(s in ("pass", "skip") for s in states) and "pass" in states:
        return "PASS"
    return "INCOMPLETE"


RESULT_WORD = {"pass": "PASS", "fail": "FAIL", "skip": "Skipped", "pending": "Not done"}
RESULT_COLOR = {"pass": "#1E7A4A", "fail": "#B3261E", "skip": "#777777", "pending": "#777777"}


def build_report_html(meta: dict, results: dict) -> str:
    """results: {step_key: {result, notes, checks: [Check], inputs: {}}}"""
    esc = html.escape
    verdict = overall(results)
    vcol = {"PASS": "#1E7A4A", "FAIL": "#B3261E"}.get(verdict, "#8A6D1B")
    rows = []
    for i, step in enumerate(STEPS, 1):
        r = results.get(step.key, {})
        res = r.get("result", "pending")
        rows.append(f'<h3>{i}. {esc(step.title)} '
                    f'<span style="color:{RESULT_COLOR[res]}">&nbsp;{RESULT_WORD[res]}</span></h3>')
        checks = r.get("checks") or []
        if checks:
            rows.append('<table width="100%" cellspacing="0" cellpadding="4">')
            for c in checks:
                mark, col = ("OK", "#1E7A4A") if c.ok is True else (("FAIL", "#B3261E") if c.ok is False
                                                                     else ("--", "#777777"))
                rows.append(f'<tr><td width="34%">{esc(c.label)}</td>'
                            f'<td width="10%" style="color:{col}"><b>{mark}</b></td>'
                            f'<td>{esc(c.detail)}</td></tr>')
            rows.append("</table>")
        typed = [(label, r.get("inputs", {}).get(key)) for key, label, kind in step.inputs]
        typed = [(l, v) for l, v in typed if v not in (None, "", False)]
        if typed:
            rows.append("<p><i>Entered by the tester:</i> " +
                        "; ".join(f"{esc(l)}: {esc('yes' if v is True else str(v))}" for l, v in typed) + "</p>")
        if r.get("notes"):
            rows.append(f"<p><i>Notes:</i> {esc(r['notes'])}</p>")
    info = [("Date", meta.get("date", datetime.now().strftime("%Y-%m-%d %H:%M"))),
            ("Tester", meta.get("tester", "")), ("Car", meta.get("car", "")),
            ("Data source", meta.get("source", "")), ("Config version", str(meta.get("config_version", ""))),
            ("Raw log", meta.get("log", "not recorded")), ("App", f"Gryphon Manager {__version__}")]
    info_rows = "".join(f"<tr><td width='22%'><b>{esc(k)}</b></td><td>{esc(str(v))}</td></tr>"
                        for k, v in info if v)
    notes = f"<p><b>Overall notes:</b> {esc(meta['notes'])}</p>" if meta.get("notes") else ""
    return f"""<html><head><meta charset="utf-8"><title>Gryphon car test report</title>
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; color: #111111; }}
h1 {{ font-size: 18pt; margin-bottom: 2px; }}
h2 {{ font-size: 15pt; margin-top: 2px; }}
h3 {{ font-size: 11.5pt; margin-top: 14px; margin-bottom: 4px; border-bottom: 1px solid #CCCCCC; }}
td {{ border-bottom: 1px solid #EEEEEE; vertical-align: top; }}
</style></head><body>
<h1>Gryphon Racing: car test report</h1>
<h2 style="color:{vcol}">Result: {verdict}</h2>
<table width="100%" cellspacing="0" cellpadding="3">{info_rows}</table>
{notes}
{''.join(rows)}
</body></html>"""
