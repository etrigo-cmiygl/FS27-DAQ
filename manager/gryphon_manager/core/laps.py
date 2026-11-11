from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_R = 6371000.0


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def to_xy(lat, lon, lat0, lon0) -> tuple[float, float]:
    x = math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0))
    y = math.radians(lat - lat0) * EARTH_R
    return x, y


@dataclass
class Lap:
    number: int
    start_ts: float
    end_ts: float

    @property
    def time(self) -> float:
        return self.end_ts - self.start_ts


class LapTimer:
    """Counts laps when the car crosses a start/finish gate.

    The gate is a short line across the track, placed by clicking the map. A lap is
    counted when the path between two GPS points crosses it in the driving direction.
    """

    GATE_HALF_WIDTH_M = 20.0
    MIN_LAP_S = 8.0

    def __init__(self):
        self.gate: tuple[float, float, float, float] | None = None
        self.reset()

    def reset(self) -> None:
        self.laps: list[Lap] = []
        self._last: tuple[float, float, float] | None = None
        self._lap_start: float | None = None

    def clear_gate(self) -> None:
        self.gate = None
        self.reset()

    def set_gate(self, lat: float, lon: float, dir_x: float, dir_y: float) -> None:
        n = math.hypot(dir_x, dir_y) or 1.0
        self.gate = (lat, lon, dir_x / n, dir_y / n)
        self.laps = []
        self._lap_start = None

    def set_gate_from_track(self, lat: float, lon: float, track) -> bool:
        pts = list(track)
        if len(pts) < 2:
            return False
        best_i = min(range(len(pts)), key=lambda i: haversine_m(lat, lon, pts[i][1], pts[i][2]))
        i0, i1 = (best_i - 1, best_i) if best_i > 0 else (0, 1)
        x0, y0 = to_xy(pts[i0][1], pts[i0][2], lat, lon)
        x1, y1 = to_xy(pts[i1][1], pts[i1][2], lat, lon)
        if math.hypot(x1 - x0, y1 - y0) < 0.5:
            return False
        self.set_gate(pts[best_i][1], pts[best_i][2], x1 - x0, y1 - y0)
        return True

    def gate_line(self) -> tuple[tuple[float, float], tuple[float, float]] | None:
        if not self.gate:
            return None
        lat, lon, dx, dy = self.gate
        px, py = -dy * self.GATE_HALF_WIDTH_M, dx * self.GATE_HALF_WIDTH_M
        dlat = math.degrees(py / EARTH_R)
        dlon = math.degrees(px / (EARTH_R * math.cos(math.radians(lat))))
        return (lat - dlat, lon - dlon), (lat + dlat, lon + dlon)

    def add_point(self, ts: float, lat: float, lon: float) -> Lap | None:
        prev = self._last
        self._last = (ts, lat, lon)
        if not self.gate or prev is None:
            return None
        glat, glon, dx, dy = self.gate
        ax, ay = to_xy(prev[1], prev[2], glat, glon)
        bx, by = to_xy(lat, lon, glat, glon)
        da, db = ax * dx + ay * dy, bx * dx + by * dy
        if not (da < 0 <= db):
            return None
        frac = -da / (db - da) if db != da else 0.0
        cx, cy = ax + (bx - ax) * frac, ay + (by - ay) * frac
        if abs(-cx * dy + cy * dx) > self.GATE_HALF_WIDTH_M:
            return None
        cross_ts = prev[0] + (ts - prev[0]) * frac
        if self._lap_start is None:
            self._lap_start = cross_ts
            return None
        if cross_ts - self._lap_start < self.MIN_LAP_S:
            return None
        lap = Lap(len(self.laps) + 1, self._lap_start, cross_ts)
        self.laps.append(lap)
        self._lap_start = cross_ts
        return lap

    @property
    def best(self) -> Lap | None:
        return min(self.laps, key=lambda l: l.time) if self.laps else None

    def current_time(self, now: float) -> float | None:
        return None if self._lap_start is None else now - self._lap_start


def fmt_lap(seconds: float | None) -> str:
    if seconds is None:
        return "--:--.--"
    m, s = divmod(max(0.0, seconds), 60.0)
    return f"{int(m)}:{s:05.2f}"
