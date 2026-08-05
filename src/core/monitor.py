import threading
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from src.core.browser_manager import BrowserManager
from src.core.notifier import Notifier
from src.core.delivery_models import mask_delivery_destination
from src.core.delivery_retry_service import (
    RetryExecution,
    TransactionalRetryService,
)
from src.core.retry_policy import TransactionalRetryPolicy
from src.core.store_manager import StoreManager
from src.database.delivery_repository import DeliveryRepository
from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.monitoring_telemetry.service import MonitorTelemetryService
from src.offers.activation import OfferActivationFlags
from src.offers.activation_control import OfferActivationManager
from src.offers.auto_stop import OfferCanaryAutoStop
from src.offers.canary import OfferCanaryController
from src.stores.active import is_active_store


class MonitorRunner:

    MAX_MONITORS_PER_BATCH = 2
    SCHEDULER_POLL_SECONDS = 60

    def __init__(
        self,
        database,
        progress_callback=None,
        telemetry_service=None,
    ):

        self.database = database
        self.progress_callback = progress_callback
        self.stop_event = threading.Event()
        self.supervisor_stop_event = threading.Event()
        self.thread = None
        self.running = False
        self.notifier = Notifier(database)
        self.notification_lock = threading.Lock()
        self.execution_lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.current_monitor_id = None
        self.current_monitor_term = ""
        self.current_execution_started_at = None
        self.last_activity_at = None
        self.last_activity_message = ""
        self.next_loop_check_at = None
        self.supervisor_thread = None
        self.health = {
            "monitor": "parado",
            "whatsapp": "verificando",
            "last_cycle": None,
            "last_error": "",
        }
        self._last_shopee_detect = None
        self.SHOPEE_DETECT_INTERVAL_MINUTES = 10
        self.owns_telemetry_service = telemetry_service is None
        self.telemetry_service = (
            telemetry_service
            if telemetry_service is not None
            else MonitorTelemetryService.from_environment()
        )

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
        clean = acquired and workers_stopped
        if clean and self.owns_telemetry_service and self.telemetry_service:
            self.telemetry_service.close()
            self.telemetry_service = None
        return clean

    def set_progress_callback(self, progress_callback):

        self.progress_callback = progress_callback

    def run_once(self):

        with self.execution_lock:
            return self._run_once_unlocked()

    def run_monitor_once(self, monitoramento):

        if not self.execution_lock.acquire(blocking=False):
            raise RuntimeError("Já existe uma execução de monitoramento em andamento.")
        try:
            return self.execute_monitoring(monitoramento)
        finally:
            self.execution_lock.release()

    def _run_once_unlocked(self):

        self.process_transactional_retries()
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
                self.run_due_batch()
            except Exception as error:
                self.health["last_error"] = str(error)
                self.database.registrar_evento_sistema(
                    "erro", "monitor", str(error)
                )
                self.log(f"Erro no monitoramento: {error}")

            with self.state_lock:
                self.next_loop_check_at = (
                    datetime.now()
                    + timedelta(seconds=self.SCHEDULER_POLL_SECONDS)
                )
            self.stop_event.wait(self.SCHEDULER_POLL_SECONDS)

        self.running = False
        self.health["monitor"] = "parado"
        with self.state_lock:
            self.next_loop_check_at = None

    def run_due_batch(self):

        with self.execution_lock:
            self.process_transactional_retries()
            self.retry_notification_queue()
            self.notify_pending_alerts()

            monitoramentos = self.database.listar_monitoramentos(
                somente_ativos=True
            )
            devidos = [
                item for item in monitoramentos
                if self.monitoramento_devido(item)
            ]
            devidos.sort(key=lambda item: (
                item["ultima_execucao"] is not None,
                item["ultima_execucao"] or "",
                item["id"],
            ))

            total = 0
            for monitoramento in devidos[:self.MAX_MONITORS_PER_BATCH]:
                if self.stop_event.is_set():
                    break
                total += self.execute_monitoring(monitoramento)

            self.notify_pending_alerts()
            self.health["last_cycle"] = datetime.now().isoformat(
                timespec="seconds"
            )
            self.health["last_error"] = ""
            return total

    @staticmethod
    def transactional_retry_enabled():
        delivery = os.getenv(
            "ENABLE_TRANSACTIONAL_DELIVERY",
            "false",
        ).strip().casefold() in {"1", "true", "yes", "on", "sim"}
        retry = TransactionalRetryPolicy.from_environment()
        return delivery and retry.enabled

    def process_transactional_retries(self):
        if not self.transactional_retry_enabled():
            return ()
        repository = DeliveryRepository(self.database.db)
        try:
            repository.migrate()
            service = TransactionalRetryService(
                repository,
                TransactionalRetryPolicy.from_environment(),
            )
            return service.process_due(self.retry_execution)
        finally:
            repository.close()

    def retry_execution(self, delivery):
        item = self.database.buscar_produto_por_link(
            delivery.original_link
        )
        if item is None:
            raise ValueError(
                "Validacao local permanente: produto do retry nao encontrado."
            )
        message = self.notifier.format_alert(item)
        if delivery.channel.casefold() == "whatsapp":
            image = self.notifier.verified_whatsapp_image(item)
            prepared = self.notifier.value(item, "imagem_whatsapp")
            if self.notifier.evolution_configured() and prepared:
                image = prepared
            return RetryExecution(
                send=lambda: self.notifier.send_whatsapp_message(
                    message,
                    image,
                    delivery.destination,
                ),
                record_history=lambda: self.notifier.record_single_delivery(
                    self.database,
                    item,
                    "WhatsApp",
                    delivery.destination,
                ),
                sanitized_metadata={
                    "content_type": (
                        "image/bytes"
                        if isinstance(image, (bytes, bytearray))
                        else "image/url"
                    ),
                    "size_bytes": (
                        len(image)
                        if isinstance(image, (bytes, bytearray))
                        else 0
                    ),
                    "destination_masked": mask_delivery_destination(
                        delivery.destination
                    ),
                },
            )
        if delivery.channel.casefold() == "telegram":
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            image = self.notifier.value(item, "imagem", "") or ""
            if not token or not image:
                raise ValueError(
                    "Validacao local permanente: Telegram incompleto."
                )
            return RetryExecution(
                send=lambda: self.notifier.send_telegram_photo(
                    token,
                    delivery.destination,
                    image,
                    message,
                ),
                record_history=lambda: self.notifier.record_single_delivery(
                    self.database,
                    item,
                    "Telegram",
                    delivery.destination,
                ),
                sanitized_metadata={
                    "content_type": "image/url",
                    "destination_masked": mask_delivery_destination(
                        delivery.destination
                    ),
                },
            )
        raise ValueError(
            "Validacao local permanente: canal de retry nao suportado."
        )

    @staticmethod
    def monitoramento_devido(monitoramento, agora=None):

        ultima_execucao = monitoramento["ultima_execucao"]
        if not ultima_execucao:
            return True

        try:
            ultima = datetime.fromisoformat(str(ultima_execucao))
        except (TypeError, ValueError):
            return True

        agora = agora or datetime.utcnow()
        intervalo = max(int(monitoramento["intervalo_minutos"] or 1), 1)
        return agora >= ultima + timedelta(minutes=intervalo)

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
        result["review"] = self.database.total_pendencias_revisao()
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
        for name in StoreManager.default_store_names():
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
        lojas_configuradas = self.parse_stores(monitoramento["lojas"])
        lojas = list(lojas_configuradas)
        lojas = [loja for loja in lojas if is_active_store(loja)]

        if not lojas:
            lojas = self.active_stable_stores()

        self.log(f"Monitorando '{termo}' em {', '.join(lojas)}")

        execution_id = self.start_telemetry_execution(
            monitoramento,
            termo,
            lojas_configuradas,
        )
        with self.state_lock:
            self.current_monitor_id = monitoramento["id"]
            self.current_monitor_term = termo
            self.current_execution_started_at = datetime.now()
        manager = None
        try:
            manager = StoreManager(
                progress_callback=self.progress_callback,
                enabled_stores=lojas,
                telemetry_observer=self.telemetry_observer(execution_id),
            )
            resultados = manager.search_all(termo)
            self.database.salvar_lista(resultados)
            self.database.registrar_execucao_monitoramento(
                monitoramento["id"],
                len(resultados)
            )

            self.log(
                f"Monitoramento '{termo}' concluiu com "
                f"{len(resultados)} produto(s)."
            )
            self.finish_telemetry_execution(
                execution_id,
                len(resultados),
                "success",
            )
            return len(resultados)
        except Exception:
            self.finish_telemetry_execution(
                execution_id,
                None,
                "failed",
            )
            raise
        finally:
            self.close_store_resources(manager)
            with self.state_lock:
                self.current_monitor_id = None
                self.current_monitor_term = ""
                self.current_execution_started_at = None

    def status_snapshot(self):

        with self.state_lock:
            thread_alive = bool(self.thread and self.thread.is_alive())
            return {
                "automatic_running": bool(self.running and thread_alive),
                "execution_in_progress": self.execution_lock.locked(),
                "current_monitor_id": self.current_monitor_id,
                "current_monitor_term": self.current_monitor_term,
                "current_execution_started_at": self.current_execution_started_at,
                "last_activity_at": self.last_activity_at,
                "last_activity_message": self.last_activity_message,
                "next_loop_check_at": self.next_loop_check_at,
                "last_cycle": self.health.get("last_cycle"),
            }

    @staticmethod
    def close_store_resources(manager):
        for store in getattr(manager, "stores", ()) if manager else ():
            closer = getattr(store, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass

    def start_telemetry_execution(
        self,
        monitoramento,
        termo,
        lojas_configuradas,
    ):
        if self.telemetry_service is None:
            return None
        try:
            return self.telemetry_service.start_execution(
                monitoramento["id"],
                termo,
                lojas_configuradas,
            )
        except Exception:
            return None

    def telemetry_observer(self, execution_id):
        if self.telemetry_service is None or not execution_id:
            return None
        try:
            return self.telemetry_service.store_observer(execution_id)
        except Exception:
            return None

    def finish_telemetry_execution(
        self,
        execution_id,
        aggregate_total,
        status,
    ):
        if self.telemetry_service is None or not execution_id:
            return False
        try:
            return self.telemetry_service.finish_execution(
                execution_id,
                aggregate_total,
                status,
            )
        except Exception:
            return False

    def notify_pending_alerts(self):

        with self.notification_lock:

            alerts = self.database.alertas_pendentes()

            if not alerts:
                self.log("Nenhuma promocao nova para notificar.")
                return

            result = self.send_automatic_alerts(alerts)
            if result.startswith("Falha ao enviar:"):
                self.database.enfileirar_notificacoes(alerts, result)
            self.log(f"Notificacao automatica: {result}")

    def retry_notification_queue(self):

        queued = self.database.listar_fila_notificacoes(10)
        if not isinstance(queued, (list, tuple)) or not queued:
            return
        ids = [row["id"] for row, _alert in queued]
        alerts = [alert for _row, alert in queued]
        result = self.send_automatic_alerts(alerts)
        if result.startswith("Enviado por:"):
            self.database.remover_fila_notificacoes(ids)
            self.database.registrar_evento_sistema(
                "info", "fila", f"{len(ids)} notificação(ões) recuperada(s)"
            )
        elif result.startswith("Falha ao enviar:"):
            self.database.enfileirar_notificacoes(alerts, result)
        self.log(f"Recuperacao da fila: {result}")

    def send_automatic_alerts(self, alerts):
        """Ativação canary opcional; desligada mantém a chamada histórica."""

        flags = OfferActivationFlags.from_environment()
        legacy_send = lambda selected: self.notifier.send_alerts(
            selected, self.database
        )
        if (
            not flags.intelligent_scheduler_enabled
            or flags.canary_percent <= 0
        ):
            return legacy_send(alerts)

        repository = None
        try:
            repository = OfferPipelineRepository(
                Path(os.getenv(
                    "OFFER_SHADOW_DB_PATH", "offer_shadow.db"
                ))
            )
            repository.migrate()
            manager = OfferActivationManager(repository)
            stop_reason = OfferCanaryAutoStop(repository).evaluate(flags)
            if stop_reason:
                manager.auto_stop(
                    stop_reason, repository.canary_safety_metrics()
                )
                self.log(f"Auto-Stop Canary: {stop_reason}")
                return legacy_send(alerts)
            controller = OfferCanaryController(
                repository,
                flags,
                auto_stop_callback=manager.auto_stop,
            )
            return controller.execute(alerts, legacy_send)
        except Exception as error:
            if flags.enable_rollback:
                self.log(
                    "Rollback automatico para scheduler legado: "
                    f"{type(error).__name__}: {error}"
                )
                return legacy_send(alerts)
            return f"Falha ao enviar: ativacao inteligente: {error}"
        finally:
            if repository is not None:
                repository.close()

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
        with self.state_lock:
            self.last_activity_at = datetime.now()
            self.last_activity_message = str(message)

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
