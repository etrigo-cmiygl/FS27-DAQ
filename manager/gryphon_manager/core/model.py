from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Frame:
    ts: float
    id: int
    ext: bool
    data: bytes
    is_error: bool = False

    @property
    def key(self) -> tuple[int, bool]:
        return (self.id, self.ext)


@dataclass(slots=True)
class RadioPacket:
    ts: float
    values: dict
    rssi: float | None = None
    snr: float | None = None
    raw: bytes | None = None


@dataclass(slots=True)
class DaqLine:
    ts: float
    kind: str
    values: dict
    text: str = ""


@dataclass(slots=True)
class SourceStatus:
    ts: float
    state: str = ""
    error_frames: int | None = None
    dropped: int | None = None
    detail: str = ""
    extra: dict = field(default_factory=dict)


def fmt_id(can_id: int, ext: bool) -> str:
    return f"0x{can_id:08X}" if ext else f"0x{can_id:03X}"


def parse_int(value) -> int:
    if isinstance(value, int):
        return value
    return int(str(value).strip(), 0)


def parse_id_list(items) -> list[int]:
    out: list[int] = []
    if items is None:
        return out
    if isinstance(items, (int, str)):
        items = [items] if isinstance(items, int) else [p for p in str(items).replace(";", ",").split(",")]
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        if "-" in text:
            lo, hi = text.split("-", 1)
            lo_i, hi_i = parse_int(lo), parse_int(hi)
            if hi_i < lo_i or hi_i - lo_i > 4096:
                raise ValueError(f"bad ID range {text}")
            out.extend(range(lo_i, hi_i + 1))
        else:
            out.append(parse_int(text))
    return out
