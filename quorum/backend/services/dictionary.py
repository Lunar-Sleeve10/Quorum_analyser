"""backend/services/dictionary.py — data dictionary: skeleton generation + upload.

If the user provides a dictionary (CSV / Excel / Markdown), we use it for
semantic enrichment. If not, we generate a skeleton from the discovered schema
so every column has a (blank) description slot.
"""
from __future__ import annotations

import csv
import io


def skeleton(discovered: dict) -> list[dict]:
    entries = []
    for t in discovered.get("tables", []):
        for c in t.get("columns", []):
            entries.append({"table": t["name"], "column": c, "description": "", "type": ""})
    return entries


def parse_upload(filename: str, content: bytes) -> list[dict]:
    """Parse a dictionary file into [{table, column, description, type}].
    Supports CSV, Excel (.xlsx/.xls), and a simple Markdown table."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        return _parse_excel(content)
    if name.endswith(".md"):
        return _parse_markdown(content.decode("utf-8", "ignore"))
    return _parse_csv(content.decode("utf-8", "ignore"))


def _norm(row: dict) -> dict:
    low = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
    return {"table": low.get("table", ""), "column": low.get("column", ""),
            "description": low.get("description", ""), "type": low.get("type", "")}


def _parse_csv(text: str) -> list[dict]:
    return [_norm(r) for r in csv.DictReader(io.StringIO(text)) if any(r.values())]


def _parse_excel(content: bytes) -> list[dict]:
    import pandas as pd
    df = pd.read_excel(io.BytesIO(content))
    df.columns = [str(c).strip().lower() for c in df.columns]
    return [_norm(r) for r in df.to_dict(orient="records")]


def _parse_markdown(text: str) -> list[dict]:
    rows, header = [], None
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if header is None:
            header = [c.lower() for c in cells]
            continue
        rows.append(_norm(dict(zip(header, cells))))
    return rows
