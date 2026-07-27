import base64
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import requests
from PIL import Image


class WhatsAppControl:
    """Controla o Docker Desktop e a Evolution API instalados localmente."""

    def __init__(self, request_timeout=15):
        self.request_timeout = request_timeout

    @staticmethod
    def _creation_flags():
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    @staticmethod
    def _compose_directory():
        candidates = [Path(__file__).resolve().parents[2] / "docker" / "evolution"]
        if getattr(sys, "frozen", False):
            executable_dir = Path(sys.executable).resolve().parent
            candidates = [executable_dir / "docker" / "evolution", executable_dir.parent / "docker" / "evolution"] + candidates
        for directory in candidates:
            if (directory / "docker-compose.yml").is_file():
                return directory
        raise RuntimeError("A pasta docker/evolution não foi encontrada.")

    def docker_available(self):
        return bool(shutil.which("docker"))

    def docker_running(self):
        if not self.docker_available():
            return False
        result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=15, creationflags=self._creation_flags())
        return result.returncode == 0

    def open_docker_desktop(self):
        if sys.platform != "win32":
            raise RuntimeError("Este botão está disponível somente no Windows.")
        candidates = [
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker/Docker Desktop.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Docker/Docker Desktop.exe",
        ]
        executable = next((path for path in candidates if path.is_file()), None)
        if executable is None:
            raise RuntimeError("Docker Desktop não encontrado. Instale-o antes de continuar.")
        subprocess.Popen([str(executable)], creationflags=self._creation_flags())
        return "Docker Desktop aberto. Aguarde até ele concluir a inicialização."

    def start_evolution(self):
        if not self.docker_available():
            raise RuntimeError("Docker não encontrado. Instale o Docker Desktop primeiro.")
        if not self.docker_running():
            raise RuntimeError("O Docker Desktop ainda não está pronto. Aguarde e tente novamente.")
        result = subprocess.run(["docker", "compose", "up", "-d"], cwd=self._compose_directory(), capture_output=True, text=True, timeout=180, creationflags=self._creation_flags())
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "Falha ao iniciar a Evolution API.")
        return "Evolution API iniciada."

    def stop_evolution(self):
        if not self.docker_available():
            raise RuntimeError("Docker não encontrado.")
        result = subprocess.run(["docker", "compose", "down"], cwd=self._compose_directory(), capture_output=True, text=True, timeout=120, creationflags=self._creation_flags())
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "Falha ao parar a Evolution API.")
        return "Evolution API parada."

    @staticmethod
    def _evolution_settings():
        url = os.getenv("EVOLUTION_API_URL", "http://localhost:8080").rstrip("/")
        instance = os.getenv("EVOLUTION_INSTANCE", "promobot").strip()
        key = os.getenv("EVOLUTION_API_KEY", "").strip()
        if not instance or not key:
            raise RuntimeError("Preencha EVOLUTION_INSTANCE e EVOLUTION_API_KEY no arquivo .env.")
        return url, instance, {"apikey": key}

    def connection_state(self):
        url, instance, headers = self._evolution_settings()
        response = requests.get(f"{url}/instance/connectionState/{instance}", headers=headers, timeout=self.request_timeout)
        if response.status_code == 404:
            return "not_created"
        response.raise_for_status()
        data = response.json()
        return str(data.get("instance", {}).get("state") or data.get("state") or data.get("status") or "unknown").lower()

    def _create_instance(self):
        url, instance, headers = self._evolution_settings()
        response = requests.post(
            f"{url}/instance/create", headers=headers,
            json={"instanceName": instance, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
            timeout=self.request_timeout,
        )
        if response.status_code not in (200, 201, 403, 409):
            response.raise_for_status()
        return response.json() if response.content else {}

    @staticmethod
    def _qr_image(data):
        qr = data.get("qrcode") or data
        encoded = qr.get("base64") if isinstance(qr, dict) else None
        if not encoded:
            return None
        return Image.open(io.BytesIO(base64.b64decode(encoded.split(",", 1)[-1]))).convert("RGB")

    def connect_whatsapp(self):
        state = self.connection_state()
        if state in {"open", "connected", "online"}:
            return "connected", None
        data = self._create_instance() if state == "not_created" else {}
        image = self._qr_image(data)
        if image is None:
            url, instance, headers = self._evolution_settings()
            response = requests.get(f"{url}/instance/connect/{instance}", headers=headers, timeout=self.request_timeout)
            response.raise_for_status()
            image = self._qr_image(response.json())
        if image is None:
            raise RuntimeError("A Evolution API não retornou um QR Code. Verifique os logs do container.")
        return "qr", image
