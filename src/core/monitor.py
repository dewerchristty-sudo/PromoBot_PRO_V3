import threading
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from src.core.browser_manager import BrowserManager
from src.core.notifier import Notifier
from src.core.store_manager import StoreManager


class MonitorRunner:

    def __init__(self, database, progress_callback=None):

        self.database = database
        self.progress_callback = progress_callback
        self.stop_event = threading.Event()
        self.supervisor_stop_event = threading.Event()
        self.thread = None
        self.running = False
        self.notifier = Notifier(database)
        self.notification_lock = threading.Lock()
        self.execution_lock = threading.Lock()
        self.supervisor_thread = None
        self.health = {
            "monitor": "parado",
            "whatsapp": "verificando",
            "last_cycle": None,
            "last_error": "",
        }
        self._last_shopee_detect = None
        self.SHOPEE_DETECT_INTERVAL_MINUTES = 10

    def start(self):

        if self.running:
            return

        self.stop_event.clear()
        self.supervisor_stop_event.clear()
        self.running = True
        self.health["monitor"] = "funcionando"
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        self.start_supervisor()
        self.log("Monitoramento iniciado.")

    def start_supervisor(self):

        if not self.supervisor_thread or not self.supervisor_thread.is_alive():
            self.supervisor_stop_event.clear()
            self.supervisor_thread = threading.Thread(
                target=self.supervise, daemon=True
            )
            self.supervisor_thread.start()

    def stop(self, wait=True):

        self.stop_event.set()
        self.running = False
        self.health["monitor"] = "parado"
        if wait and self.thread and self.thread is not threading.current_thread():
            self.thread.join()
        self.log("Monitoramento parado.")

    def shutdown(self, timeout=5):

        self.stop_event.set()
        self.supervisor_stop_event.set()
        self.running = False
        self.health["monitor"] = "parado"

        current = threading.current_thread()
        deadline = time.monotonic() + max(float(timeout), 0)
        for worker in (self.thread, self.supervisor_thread):
            if worker and worker is not current:
                worker.join(max(deadline - time.monotonic(), 0))

        # A manual run_once can use a separate UI thread. Waiting for this lock
        # guarantees that the database can be closed safely afterwards.
        acquired = self.execution_lock.acquire(
            timeout=max(deadline - time.monotonic(), 0)
        )
        if acquired:
            self.execution_lock.release()

        workers_stopped = all(
            not worker or worker is current or not worker.is_alive()
            for worker in (self.thread, self.supervisor_thread)
        )
        return acquired and workers_stopped

    def set_progress_callback(self, progress_callback):

        self.progress_callback = progress_callback

    def run_once(self):

        with self.execution_lock:
            return self._run_once_unlocked()

    def _run_once_unlocked(self):

        self.retry_notification_queue()
        self.notify_pending_alerts()

        total = 0

        for monitoramento in self.database.listar_monitoramentos(somente_ativos=True):

            total += self.execute_monitoring(monitoramento)

        self.notify_pending_alerts()
        self.health["last_cycle"] = datetime.now().isoformat(timespec="seconds")
        self.health["last_error"] = ""

        return total

    def run(self):

        while not self.stop_event.is_set():

            try:
                self.run_once()
            except Exception as error:
                self.health["last_error"] = str(error)
                self.database.registrar_evento_sistema(
                    "erro", "monitor", str(error)
                )
                self.log(f"Erro no monitoramento: {error}")

            monitoramentos = self.database.listar_monitoramentos(somente_ativos=True)
            intervalo = min(
                [item["intervalo_minutos"] for item in monitoramentos],
                default=30
            )

            self.stop_event.wait(max(intervalo, 1) * 60)

        self.running = False
        self.health["monitor"] = "parado"

    def supervise(self):

        previous_whatsapp = None
        while not self.supervisor_stop_event.wait(30):
            connected, detail = self.notifier.whatsapp_connection_health()
            current = "conectado" if connected else f"desconectado: {detail}"
            self.health["whatsapp"] = current
            if current != previous_whatsapp:
                level = "info" if connected else "alerta"
                self.database.registrar_evento_sistema(
                    level, "whatsapp", current
                )
                previous_whatsapp = current

            if self.running and (not self.thread or not self.thread.is_alive()):
                self.database.registrar_evento_sistema(
                    "alerta", "supervisor", "Monitor reiniciado automaticamente"
                )
                self.running = False
                self.start()

            # Periodically run the Shopee verify detector to update disabled list
            # but only when the monitor is not running (parado).
            try:
                if not self.running:
                    now = time.time()
                    interval = self.SHOPEE_DETECT_INTERVAL_MINUTES * 60
                    if (
                        self._last_shopee_detect is None
                        or (now - self._last_shopee_detect) >= interval
                    ):
                        self._last_shopee_detect = now
                        threading.Thread(
                            target=self._run_shopee_detector,
                            daemon=True,
                        ).start()
            except Exception:
                # never let detector errors stop supervise loop
                pass

    def health_status(self):

        result = dict(self.health)
        result["queue"] = self.database.total_fila_notificacoes()
        return result

    def active_stable_stores(self):

        # Load disabled stores with expiry from logs/disabled_stores.json
        disabled_file = self.disabled_stores_file()
        disabled = {}
        now = datetime.now()

        if disabled_file.exists():
            try:
                disabled = json.loads(disabled_file.read_text(encoding='utf-8') or '{}')
            except Exception:
                disabled = {}

        active = []
        for name in StoreManager.stable_store_names():
            expiry = disabled.get(name)
            if not expiry:
                active.append(name)
                continue
            try:
                exp_dt = datetime.fromisoformat(expiry)
            except Exception:
                # malformed expiry -> treat as disabled
                continue
            if exp_dt <= now:
                # expired -> treat as active
                active.append(name)
            else:
                # still disabled
                continue

        return active

    def execute_monitoring(self, monitoramento):

        termo = monitoramento["termo"]
        lojas = self.parse_stores(monitoramento["lojas"])

        if not lojas:
            lojas = self.active_stable_stores()

        self.log(f"Monitorando '{termo}' em {', '.join(lojas)}")

        manager = StoreManager(
            progress_callback=self.progress_callback,
            enabled_stores=lojas
        )
        resultados = manager.search_all(termo)
        self.database.salvar_lista(resultados)
        self.database.registrar_execucao_monitoramento(
            monitoramento["id"],
            len(resultados)
        )

        self.log(
            f"Monitoramento '{termo}' concluiu com {len(resultados)} produto(s)."
        )

        return len(resultados)

    def notify_pending_alerts(self):

        with self.notification_lock:

            alerts = self.database.alertas_pendentes()

            if not alerts:
                self.log("Nenhuma promocao nova para notificar.")
                return

            result = self.notifier.send_alerts(alerts, self.database)
            if result.startswith("Falha ao enviar:"):
                self.database.enfileirar_notificacoes(alerts, result)
            self.log(f"Notificacao automatica: {result}")

    def retry_notification_queue(self):

        queued = self.database.listar_fila_notificacoes(10)
        if not isinstance(queued, (list, tuple)) or not queued:
            return
        ids = [row["id"] for row, _alert in queued]
        alerts = [alert for _row, alert in queued]
        result = self.notifier.send_alerts(alerts, self.database)
        if result.startswith("Enviado por:"):
            self.database.remover_fila_notificacoes(ids)
            self.database.registrar_evento_sistema(
                "info", "fila", f"{len(ids)} notificação(ões) recuperada(s)"
            )
        elif result.startswith("Falha ao enviar:"):
            self.database.enfileirar_notificacoes(alerts, result)
        self.log(f"Recuperacao da fila: {result}")

    def notify_pending_async(self):

        threading.Thread(
            target=self._notify_pending_safely,
            daemon=True
        ).start()

    def _notify_pending_safely(self):

        # shutdown() waits for this lock before the database is closed.
        with self.execution_lock:
            if not self.supervisor_stop_event.is_set():
                self.notify_pending_alerts()

    def parse_stores(self, text):

        return [
            item.strip()
            for item in (text or "").split(",")
            if item.strip()
        ]

    def log(self, message):

        print(message)

        if self.progress_callback:
            self.progress_callback(message)

    def _run_shopee_detector(self):

        manager = None
        try:
            manager = BrowserManager(headless=True)
            page = manager.new_page(stealth=True)
            page.goto(
                "https://shopee.com.br/search?keyword=ssd+1tb",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(3000)
            url = (page.url or "").lower()
            content = page.content().lower()
            blocked = (
                "/verify/traffic/error" in url
                or "verify/traffic/error" in content
                or "redirect_to_error_page" in content
            )

            disabled_file = self.disabled_stores_file()
            disabled_file.parent.mkdir(parents=True, exist_ok=True)
            disabled = {}
            if disabled_file.exists():
                try:
                    disabled = json.loads(
                        disabled_file.read_text(encoding="utf-8") or "{}"
                    )
                except (OSError, ValueError):
                    disabled = {}

            if blocked:
                disabled["Shopee"] = (
                    datetime.now() + timedelta(minutes=60)
                ).isoformat(timespec="seconds")
                status = "bloqueada temporariamente"
            else:
                disabled.pop("Shopee", None)
                status = "disponivel"

            disabled_file.write_text(
                json.dumps(disabled, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.log(f"Detector Shopee: {status}.")
        except Exception as e:
            self.log(f'Erro ao executar detector Shopee: {e}')
        finally:
            if manager is not None:
                manager.close()

    def disabled_stores_file(self):

        database_path = Path(getattr(self.database, "db", "promobot.db"))
        return database_path.resolve().parent / "logs" / "disabled_stores.json"
