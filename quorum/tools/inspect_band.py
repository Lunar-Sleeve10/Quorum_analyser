"""
tools/inspect_band.py — Discover your band-sdk's REST method names + signatures.

Run this once, locally, with the SDK installed and DASHBOARD_API_KEY set. It
prints every callable on the REST services Quorum uses, plus the request types
available, so you can confirm (or correct) the method names used in
core/band_client.py for create_room / add_agent / delete_room.

    pip install "band-sdk[pydantic-ai]"
    export DASHBOARD_API_KEY=...           # or set in your shell
    python tools/inspect_band.py
"""

from __future__ import annotations

import inspect
import os
import sys


def main() -> None:
    try:
        from band.client.rest import RestClient
        import band.client.rest as rest_mod
    except Exception as exc:
        sys.exit(f"band-sdk not importable: {exc}\nInstall: pip install \"band-sdk[pydantic-ai]\"")

    # Load .env if present so you don't have to export the key by hand.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    key = os.getenv("DASHBOARD_API_KEY") or os.getenv("BAND_API_KEY") or ""
    base = os.getenv("BAND_REST_URL", "https://app.band.ai")
    if not key:
        sys.exit("DASHBOARD_API_KEY not found.\n"
                 "  PowerShell:  $env:DASHBOARD_API_KEY=\"your_key\"\n"
                 "  or add DASHBOARD_API_KEY=your_key to .env in this folder.")

    client = RestClient(api_key=key, base_url=base)

    services = [
        "agent_api_chats",          # expect create / delete here
        "agent_api_participants",   # expect add-participant here
        "agent_api_messages",       # post (already used)
        "agent_api_identity",       # whoami (already used)
    ]
    for svc in services:
        obj = getattr(client, svc, None)
        print(f"\n=== {svc} -> {type(obj).__name__ if obj else 'MISSING'} ===")
        if obj is None:
            continue
        for name in sorted(dir(obj)):
            if name.startswith("_"):
                continue
            attr = getattr(obj, name)
            if not callable(attr):
                continue
            try:
                sig = str(inspect.signature(attr))
            except (TypeError, ValueError):
                sig = "(...)"
            print(f"  {name}{sig}")

    print("\n=== request/response types in band.client.rest ===")
    hits = [n for n in dir(rest_mod)
            if any(k in n for k in ("Chat", "Participant", "Message", "Request"))]
    for n in sorted(hits):
        print(" ", n)

    # Connection sanity check
    try:
        me = client.agent_api_identity.get_agent_me()
        data = getattr(me, "data", me)
        print(f"\nConnected as: id={getattr(data,'id',None)} "
              f"handle={getattr(data,'handle',None)} name={getattr(data,'name',None)}")
    except Exception as exc:
        print(f"\nwhoami failed: {exc}")


if __name__ == "__main__":
    main()
