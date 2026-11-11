from __future__ import annotations

import json
import os
import shutil
import string
import sys
import urllib.request
from pathlib import Path

from .. import REPO, __version__

API = "https://api.github.com/repos/{repo}/releases?per_page=20"


def find_pico_drives() -> list[tuple[str, str]]:
    """Drives that look like a Pico in BOOTSEL mode: they hold a file called INFO_UF2.TXT."""
    roots: list[Path] = []
    if sys.platform.startswith("win"):
        roots = [Path(f"{c}:\\") for c in string.ascii_uppercase if c not in "AB"]
    elif sys.platform == "darwin":
        roots = list(Path("/Volumes").glob("*"))
    else:
        roots = []
        for base in ("/media", "/run/media"):
            b = Path(base)
            if b.is_dir():
                roots += list(b.glob("*")) + list(b.glob("*/*"))
    out = []
    for r in roots:
        info = r / "INFO_UF2.TXT"
        try:
            if info.is_file():
                text = info.read_text(errors="replace")
                board = next((l.split(":", 1)[1].strip() for l in text.splitlines() if l.startswith("Board-ID")), "")
                model = next((l.split(":", 1)[1].strip() for l in text.splitlines() if l.startswith("Model")), "")
                out.append((str(r), board or model or "Pico"))
        except OSError:
            continue
    return out


def is_rp2350(description: str) -> bool:
    return "RP2350" in description.upper() or "PICO2" in description.upper().replace(" ", "")


def _get_json(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"GryphonManager/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_releases(repo: str = REPO) -> list[dict]:
    return _get_json(API.format(repo=repo))


def latest_firmware(releases: list[dict]) -> dict | None:
    for rel in releases:
        if rel.get("draft"):
            continue
        for asset in rel.get("assets", []):
            if asset.get("name", "").lower().endswith(".uf2"):
                return {"tag": rel.get("tag_name", ""), "name": asset["name"],
                        "url": asset["browser_download_url"], "size": asset.get("size", 0),
                        "published": rel.get("published_at", "")[:10], "notes": rel.get("body") or ""}
    return None


def version_tuple(text: str) -> tuple:
    digits = "".join(c if c.isdigit() or c == "." else " " for c in text).split()
    if not digits:
        return ()
    return tuple(int(p) for p in digits[0].split(".") if p)


def newer_manager(releases: list[dict], current: str = __version__) -> dict | None:
    best = None
    for rel in releases:
        tag = rel.get("tag_name", "")
        if not tag.startswith("manager-v") or rel.get("draft") or rel.get("prerelease"):
            continue
        v = version_tuple(tag[len("manager-v"):])
        if v > version_tuple(current) and (best is None or v > best[0]):
            best = (v, {"tag": tag, "url": rel.get("html_url", ""), "version": ".".join(map(str, v))})
    return best[1] if best else None


def download(url: str, dest: Path, timeout: float = 30.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": f"GryphonManager/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    return dest


def check_uf2(path: Path) -> str:
    """Returns '' if the file looks like a UF2, otherwise why not."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError as exc:
        return f"Can't read the file: {exc}"
    if size == 0 or size % 512:
        return "That isn't a UF2 file (wrong size)."
    if head[:4] != b"UF2\n" or head[4:8] != bytes.fromhex("5751 5D9E".replace(" ", "")):
        return "That isn't a UF2 file (wrong header)."
    return ""


def flash(uf2: Path, drive: str) -> None:
    target = Path(drive) / uf2.name
    with open(uf2, "rb") as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        try:
            os.fsync(dst.fileno())
        except OSError:
            pass
