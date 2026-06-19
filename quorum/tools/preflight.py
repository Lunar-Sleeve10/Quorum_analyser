"""
tools/preflight.py — verify your Band setup BEFORE launching the agents.

Checks, in order:
  1. .env has the Band platform URLs and (optionally) the console key;
  2. agent_config.yaml exists and has all 7 roles with real (non-placeholder)
     agent_id + api_key;
  3. each api_key is actually LINKED to a Band agent (calls get_agent_me) —
     this is what catches the 401 "API key not linked to a user or agent".

Run:  python tools/preflight.py
Exit code 0 = safe to launch; non-zero = fix the reported items first.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

ROLES = ["supervisor", "sql_analyst", "cost_sentinel", "guardian",
         "decision_reporter", "investigator", "adjudicator"]


def _check_key(rest_url: str, api_key: str) -> tuple[bool, str]:
    """Return (ok, detail) by calling get_agent_me with this key."""
    try:
        from core.band_client import BandDashboardClient
    except Exception as exc:
        return False, f"Band SDK not importable ({exc}) — pip install \"band-sdk[pydantic-ai]\""
    try:
        who = BandDashboardClient(api_key, rest_url).whoami()
        ident = who.get("handle") or who.get("name") or who.get("id") or "(connected)"
        return True, str(ident)
    except Exception as exc:
        msg = str(exc).lower()
        if "401" in msg or "unauthorized" in msg or "not linked" in msg:
            return False, "401 — API key not linked to a Band agent (wrong/expired key)"
        return False, str(exc)[:180]


def main() -> int:
    ok = True
    print("== Quorum preflight ==\n")

    rest = (os.getenv("THENVOI_REST_URL") or os.getenv("BAND_REST_URL") or "").strip()
    ws = (os.getenv("THENVOI_WS_URL") or "").strip()
    print(f"REST URL : {rest or '(MISSING)'}")
    print(f"WS URL   : {ws or '(MISSING)'}")
    if not rest:
        ok = False
        print("  ! Set THENVOI_REST_URL (e.g. https://app.band.ai/) in .env")
    if not ws:
        print("  ~ THENVOI_WS_URL not set — the websocket connection needs it")
    print()

    try:
        import yaml
    except Exception:
        print("PyYAML not installed — pip install pyyaml")
        return 2

    cfg = ROOT / "agent_config.yaml"
    if not cfg.exists():
        print("agent_config.yaml : MISSING")
        print("  ! cp agent_config.example.yaml agent_config.yaml and fill in your 7 agents")
        print("    (create each on app.band.ai -> Agents -> New Agent -> Remote Agent)")
        return 2
    data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}

    print("Per-agent credential check:")
    for role in ROLES:
        entry = data.get(role) or {}
        aid = str(entry.get("agent_id", "")).strip()
        key = str(entry.get("api_key", "")).strip()
        tag = f"  [{role:<17}]"
        if not aid or aid.startswith("<") or not key or key.startswith("<"):
            ok = False
            print(f"{tag} MISSING/placeholder agent_id or api_key")
            continue
        if not rest:
            print(f"{tag} skipped (no REST URL)")
            continue
        good, detail = _check_key(rest, key)
        print(f"{tag} {'OK   -> ' + detail if good else 'FAIL -> ' + detail}")
        ok = ok and good

    print()
    print("PREFLIGHT:", "ALL GOOD — safe to launch (python launch_all.py)"
          if ok else "PROBLEMS ABOVE — fix before launching")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
