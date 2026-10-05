"""runs/<key>/status.json: where a run says how far it has got.

`run.py` writes it at each stage, and `serve.py` creates it when it starts a run and settles it if the run
dies without doing so. Shape: {"state": "running"|"done"|"failed"|"canceled", "stage": one of STAGES,
"started": epoch seconds, "finished": epoch seconds once the run has ended, "error": last line of the
error, on failure}. A run with no file is "idle".
"""
import json
import os
import time
from pathlib import Path
from typing import Any

STAGES: tuple[str, ...] = ("fetch", "context", "write", "render")
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELED = "canceled"
IDLE = "idle"


def status_path(home: Path, key: str) -> Path:
    return home / "runs" / key / "status.json"


def read_status(home: Path, key: str) -> dict[str, Any] | None:
    try:
        data: Any = json.loads(status_path(home, key).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_status(home: Path, key: str, **fields: Any) -> dict[str, Any]:
    """Merge `fields` into the run's status and write it atomically, so a reader never sees half a file.
    `started` is set on the first write and kept after that unless `fields` gives one."""
    path: Path = status_path(home, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[str, Any] = {**(read_status(home, key) or {}), **fields}
    merged.setdefault("started", time.time())
    temporary: Path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(merged) + "\n")
    os.replace(temporary, path)
    return merged


def begin_status(home: Path, key: str, **fields: Any) -> dict[str, Any]:
    """Start a fresh status for a new run: nothing of an earlier run's error or finish time is kept."""
    path: Path = status_path(home, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh: dict[str, Any] = {"state": RUNNING, "stage": STAGES[0], "started": time.time(), **fields}
    temporary: Path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(fresh) + "\n")
    os.replace(temporary, path)
    return fresh


def last_line(text: str) -> str:
    """The last non-empty line of `text`, trimmed to a length a card can show."""
    lines: list[str] = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


def elapsed(status: dict[str, Any], now: float | None = None) -> int:
    """Whole seconds a run took, or has taken so far while it is running."""
    started: float = float(status.get("started", 0) or 0)
    end: float = float(status["finished"]) if status.get("finished") else (now if now is not None else time.time())
    return max(0, round(end - started)) if started else 0
