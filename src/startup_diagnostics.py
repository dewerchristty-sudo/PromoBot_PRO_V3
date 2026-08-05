from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path


def startup_log_path() -> Path:
    configured = os.getenv("PROMOBOT_STARTUP_LOG", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base = Path(os.getenv("LOCALAPPDATA", Path.cwd())) / "PromoBot_PRO_V3" / "logs"
    return base / "frozen_startup_probe.log"


def startup_log(stage: str, detail: str = "") -> None:
    path = startup_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        thread = threading.current_thread()
        line = (
            f"{datetime.now().astimezone().isoformat(timespec='milliseconds')} "
            f"pid={os.getpid()} thread={thread.name}:{thread.ident} {stage}"
        )
        if detail:
            line += f" | {detail}"
        with path.open("a", encoding="utf-8") as output:
            output.write(line + "\n")
            output.flush()
    except OSError:
        pass


def thread_snapshot() -> str:
    frames = sys._current_frames()
    entries = []
    for thread in threading.enumerate():
        frame = frames.get(thread.ident)
        stack = "".join(traceback.format_stack(frame)) if frame else "sem stack"
        entries.append(
            f"name={thread.name!r} ident={thread.ident} daemon={thread.daemon}\n{stack}"
        )
    return "\n--- thread ---\n".join(entries)


def install_exception_logging() -> None:
    def sys_hook(exc_type, exc_value, exc_traceback):
        startup_log("EXCECAO PRINCIPAL", "".join(traceback.format_exception(
            exc_type, exc_value, exc_traceback
        )))
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def thread_hook(args):
        startup_log("EXCECAO THREAD", "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback
        )))

    sys.excepthook = sys_hook
    threading.excepthook = thread_hook
