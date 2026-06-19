"""
launch_all.py — Start every Quorum Band agent at once.

Spawns one process per role (the same `python -m pipeline.run_agent --role X`
you'd run by hand) and streams their logs into this one console, each line
prefixed with the role. Ctrl+C stops them all.

    python launch_all.py                 # all 7 roles
    python launch_all.py --roles supervisor sql_analyst   # a subset
    python launch_all.py --investigators 3                # extra investigator
                                                          # processes for real
                                                          # parallel fan-out

Requires the Band SDK and a filled-in .env + agent_config.yaml
(see BAND_INTEGRATION.md).
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading
from pathlib import Path

ROLES = ["supervisor", "sql_analyst", "cost_sentinel", "guardian",
         "decision_reporter", "investigator", "adjudicator"]

ROOT = Path(__file__).resolve().parent
_procs: list[subprocess.Popen] = []
_lock = threading.Lock()


def _pump(proc: subprocess.Popen, label: str) -> None:
    """Forward a child's output to this console with a role prefix."""
    assert proc.stdout is not None
    for line in proc.stdout:
        with _lock:
            sys.stdout.write(f"[{label}] {line}")
            sys.stdout.flush()


def _spawn(role: str, label: str) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "pipeline.run_agent", "--role", role],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    threading.Thread(target=_pump, args=(proc, label), daemon=True).start()
    return proc


def _stop_all() -> None:
    for p in _procs:
        if p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
    for p in _procs:
        try:
            p.wait(timeout=10)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch all Quorum Band agents.")
    parser.add_argument("--roles", nargs="*", default=ROLES,
                        help="Subset of roles to launch (default: all).")
    parser.add_argument("--investigators", type=int, default=1,
                        help="How many investigator processes to run (parallel fan-out).")
    args = parser.parse_args()

    roles = list(args.roles)
    launch: list[tuple[str, str]] = []
    for r in roles:
        if r == "investigator":
            for i in range(max(1, args.investigators)):
                launch.append((r, f"investigator-{i+1}" if args.investigators > 1 else "investigator"))
        else:
            launch.append((r, r))

    print(f"Launching {len(launch)} agent process(es): {[l for _, l in launch]}")
    print("Press Ctrl+C to stop all.\n")

    for role, label in launch:
        _procs.append(_spawn(role, label))

    try:
        signal.pause() if hasattr(signal, "pause") else _wait_forever()
    except KeyboardInterrupt:
        print("\nStopping all agents…")
    finally:
        _stop_all()
        print("All agents stopped.")


def _wait_forever() -> None:
    # Windows has no signal.pause(); block until interrupted or a child dies.
    import time
    while True:
        if all(p.poll() is not None for p in _procs):
            print("All child processes have exited.")
            return
        time.sleep(1)


if __name__ == "__main__":
    main()
