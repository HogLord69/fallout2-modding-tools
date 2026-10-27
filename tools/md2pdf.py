"""
md2pdf.py - render a docs/*.md design document to PDF in the house style of
REDWELL_DESIGN.pdf / LAMESA_DEPOT_DESIGN.pdf (maroon headings, maroon table
headers, "FOC Mod · <title>  n / N" footer), via wkhtmltopdf.

    python tools/md2pdf.py docs/CLAIREMONT_DESIGN.md            # -> docs/CLAIREMONT_DESIGN.pdf
    python tools/md2pdf.py docs/X.md -o out.pdf --footer "X Design Document"

Needs: pip markdown; wkhtmltopdf at C:\\Program Files\\wkhtmltopdf\\bin.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

import markdown

WKHTML = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"

CSS = """
body { font-family: 'Open Sans', 'Segoe UI', Arial, sans-serif; font-size: 10.5pt;
       color: #222; line-height: 1.45; }
h1 { color: #6b2419; font-size: 22pt; margin: 0 0 6px 0;
     border-bottom: 8px solid #6b2419; padding-bottom: 6px; }
h2 { color: #6b2419; font-size: 14pt; margin-top: 22px; padding-bottom: 4px;
     border-bottom: 1px solid #c9a9a3; page-break-after: avoid; }
h3 { color: #222; font-size: 11.5pt; margin-top: 16px; page-break-after: avoid; }
a { color: #a0402f; text-decoration: none; }
code { font-family: Consolas, 'Courier New', monospace; font-size: 9pt;
       background: #f3eeec; padding: 0 2px; }
pre { background: #f7f3f2; border: 1px solid #e0d2cf; padding: 8px;
      font-size: 7.6pt; line-height: 1.25; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 7.6pt; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px 0;
        font-size: 9pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th { background: #6b2419; color: #fff; text-align: left; padding: 5px 7px; }
td { border: 1px solid #e3d6d3; padding: 5px 7px; vertical-align: top; }
tr:nth-child(even) td { background: #faf6f5; }
blockquote { background: #f7f0ee; border-left: 4px solid #a0402f; margin: 10px 0;
             padding: 6px 12px; color: #333; }
hr { border: 0; border-top: 1px solid #c9a9a3; margin: 18px 0; }
/* the metadata table right under the title: bold key column, no header bar */
table.meta th { display: none; }
table.meta td:first-child { font-weight: bold; width: 42%; }
"""


LIST_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s")


def normalize_lists(src):
    """Python-Markdown wants a blank line before a list and 4-space nesting;
    the docs are written GitHub-style (list straight after a paragraph,
    2-space nesting). Outside fenced code only."""
    out, fenced, prev = [], False, ""
    for line in src.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        # lists inside a blockquote: work on the text after the "> " marker
        quote = ""
        if not fenced and line.startswith(">"):
            quote, line = "> ", line[1:].lstrip(" ")
        m = None if fenced else LIST_RE.match(line)
        if m:
            indent = len(m.group(1))
            line = " " * (indent * 2) + line[indent:]  # 2-space -> 4-space levels
            p = prev[1:].lstrip(" ") if prev.startswith(">") else prev
            if p.strip() and not LIST_RE.match(p) and not p.startswith("|"):
                out.append(quote.rstrip())
        out.append(quote + line)
        prev = quote + line
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("-o", "--out")
    ap.add_argument("--footer", help="footer label (default: from the H1)")
    a = ap.parse_args()

    src = open(a.md, encoding="utf-8").read()
    out = a.out or os.path.splitext(a.md)[0] + ".pdf"

    h1 = re.search(r"^# (.+)$", src, re.M)
    title = h1.group(1).strip() if h1 else os.path.basename(a.md)
    label = a.footer or re.sub(r"\s+—\s+", " ", title).title().replace("Location ", "")

    body = markdown.markdown(normalize_lists(src), extensions=["tables", "fenced_code", "sane_lists"])
    # first table after the H1 is the metadata block ("| | |" header)
    body = body.replace("<table>", '<table class="meta">', 1)

    html = ("<!doctype html><html><head><meta charset='utf-8'><style>" + CSS +
            "</style></head><body>" + body + "</body></html>")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    try:
        cmd = [WKHTML, "--quiet", "--encoding", "utf-8", "--page-size", "Letter",
               "--margin-top", "14mm", "--margin-bottom", "16mm",
               "--margin-left", "14mm", "--margin-right", "14mm",
               "--enable-local-file-access",
               "--footer-center", f"FOC Mod  ·  {label}      [page] / [topage]",
               "--footer-font-name", "Segoe UI", "--footer-font-size", "7",
               "--footer-spacing", "4", tmp, out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"wkhtmltopdf failed ({r.returncode}):\n{r.stderr}")
    finally:
        os.unlink(tmp)
    print(out)


if __name__ == "__main__":
    main()
