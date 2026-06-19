"""fix_imports.py - undo an IDE 'absolutize imports' pass that prefixed the
project's imports with the top-level folder name (quorum.*). Run once from the
project root:

    python fix_imports.py

It rewrites import statements such as 'from quorum.<pkg> import ...' and
'import quorum.<pkg>' back to '<pkg>' across all .py files (skipping venvs and
this script itself), so the app runs correctly when launched from inside the
project folder.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAT = re.compile(r'^(\s*)(from|import)\s+quorum\.', re.MULTILINE)
SKIP_DIRS = {"venv", ".venv", "venvpandas", "__pycache__", ".git"}
SELF = Path(__file__).name

changed = 0
for p in ROOT.rglob("*.py"):
    if p.name == SELF or any(part in SKIP_DIRS for part in p.parts):
        continue
    text = p.read_text(encoding="utf-8")
    new = PAT.sub(lambda m: f"{m.group(1)}{m.group(2)} ", text)
    if new != text:
        p.write_text(new, encoding="utf-8")
        changed += 1
        print("fixed", p.relative_to(ROOT))

print(f"\nDone. {changed} file(s) repaired." if changed
      else "\nNothing to fix - no quorum-prefixed imports found.")
