import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path


logger = logging.getLogger(__name__)
VALID_RESULTS = {"criado", "atualizado", "inalterado"}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def shortcut_script() -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle_root / "scripts" / "ensure_desktop_shortcut.ps1"
    return project_root() / "scripts" / "ensure_desktop_shortcut.ps1"


def launch_configuration() -> dict[str, str]:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        return {
            "target": str(executable),
            "arguments": "",
            "working_directory": str(executable.parent),
            "icon": f"{executable},0",
        }

    root = project_root()
    python = Path(sys.executable).resolve()
    pythonw = python.with_name("pythonw.exe")
    if sys.platform == "win32" and pythonw.is_file():
        python = pythonw
    return {
        "target": str(python),
        "arguments": f'"{(root / "main.py").resolve()}"',
        "working_directory": str(root),
        "icon": f"{python},0",
    }


def powershell_executable() -> str:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidate = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.is_file() else (shutil.which("powershell") or "powershell")


def ensure_desktop_shortcut() -> str:
    """Create or repair the desktop shortcut without blocking application startup."""
    try:
        script = shortcut_script()
        if not script.is_file():
            raise FileNotFoundError(f"Rotina de atalho ausente: {script}")
        config = launch_configuration()
        command = [
            powershell_executable(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-TargetPath",
            config["target"],
            "-Arguments",
            config["arguments"],
            "-WorkingDirectory",
            config["working_directory"],
            "-IconLocation",
            config["icon"],
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=creationflags,
        )
        output = (completed.stdout or "").strip().splitlines()
        result = output[-1].strip().casefold() if output else ""
        if completed.returncode != 0 or result not in VALID_RESULTS:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(detail or f"resultado inesperado: {result!r}")
        logger.info("Atalho PromoBot_PRO_V3.lnk: %s", result)
        return result
    except Exception as error:
        logger.warning(
            "Atalho PromoBot_PRO_V3.lnk: falha não bloqueante: %s",
            error,
        )
        return "falha não bloqueante"
