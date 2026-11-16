"""Builds docs/Gryphon-Manager-Manual.pdf from the Markdown, with bookmarks.

    python tools/manual_shots.py      (retakes the screenshots, optional)
    python tools/build_manual.py

Needs pandoc, wkhtmltopdf and pypdf (pip install pypdf).
"""
import re
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

docs = Path(__file__).resolve().parents[1] / "docs"
source = docs / "Gryphon-Manager-Manual.md"
target = docs / "Gryphon-Manager-Manual.pdf"
CSS = """
body { font-family: "DejaVu Sans", Arial, sans-serif; font-size: 10.5pt; line-height: 1.45; color: #1a1a1a; }
h1 { font-size: 24pt; color: #14532d; border-bottom: 3px solid #14532d; padding-bottom: 6px; }
h2 { font-size: 16pt; color: #14532d; margin-top: 26px; border-bottom: 1px solid #c9d6cd; padding-bottom: 3px;
     page-break-after: avoid; }
h3 { font-size: 12.5pt; margin-top: 18px; page-break-after: avoid; }
img { max-width: 100%; border: 1px solid #c9d6cd; margin: 6px 0 10px 0; page-break-inside: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px 0; page-break-inside: avoid; }
th, td { border: 1px solid #c9d6cd; padding: 4px 7px; text-align: left; vertical-align: top; font-size: 9.5pt; }
th { background: #e8f1ea; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 9pt; background: #f1f4f2; padding: 0 2px; }
pre { background: #f1f4f2; padding: 8px; font-size: 9pt; }
pre code { background: none; }
"""


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


with tempfile.TemporaryDirectory() as tmp:
    css, html, plain = Path(tmp) / "manual.css", Path(tmp) / "manual.html", Path(tmp) / "plain.pdf"
    css.write_text(CSS, encoding="utf-8")
    subprocess.run(["pandoc", source.name, "-f", "gfm", "-t", "html5", "-s", "--metadata",
                    "title=Gryphon Manager manual", "-c", str(css), "--embed-resources", "-o", str(html)],
                   cwd=docs, check=True)
    page = re.sub(r'<header id="title-block-header">.*?</header>', "", html.read_text(encoding="utf-8"), flags=re.S)
    html.write_text(page, encoding="utf-8")
    subprocess.run(["wkhtmltopdf", "--quiet", "--enable-local-file-access", "--page-size", "A4", "--margin-top", "16mm",
                    "--margin-bottom", "16mm", "--margin-left", "15mm", "--margin-right", "15mm", str(html), str(plain)],
                   check=True)
    reader = PdfReader(str(plain))
    pages = [{squash(text_line) for text_line in (p.extract_text() or "").splitlines()} for p in reader.pages]
    writer = PdfWriter()
    writer.append(reader, import_outline=False)
    at, parent, missing = 0, None, []
    for line in source.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(#{1,3}) (.+)$", line)
        if not m:
            continue
        level, title = len(m.group(1)), m.group(2).strip()
        found = next((i for i in range(at, len(pages)) if squash(title) in pages[i]), None)
        if found is None:
            missing.append(title)
            found = at
        at = found
        if level <= 2:
            parent = writer.add_outline_item(title, found)
        else:
            writer.add_outline_item(title, found, parent=parent)
    writer.add_metadata({"/Title": "Gryphon Manager manual", "/Author": "Leeds Gryphon Racing"})
    writer.page_mode = "/UseOutlines"
    with open(target, "wb") as f:
        writer.write(f)
print(f"{target.name}: {len(reader.pages)} pages, headings not found: {missing or 'none'}")
