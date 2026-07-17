import threading

from src.core.notifier import Notifier
from src.core.store_manager import StoreManager


class MonitorRunner:

    def __init__(self, database, progress_callback=None):

        self.database = database
        self.progress_callback = progress_callback
        self.stop_event = threading.Event()
        self.thread = None
        self.running = False
        self.notifier = Notifier()
        self.notification_lock = threading.Lock()

    def start(self):

        if self.running:
            return

        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        self.running = True
        self.log("Monitoramento iniciado.")

    def stop(self):

        self.stop_event.set()
        self.running = False
        self.log("Monitoramento parado.")

    def set_progress_callback(self, progress_callback):

        self.progress_callback = progress_callback

    def run_once(self):

        self.notify_pending_alerts()

        total = 0

        for monitoramento in self.database.listar_monitoramentos(somente_ativos=True):

            total += self.execute_monitoring(monitoramento)

        self.notify_pending_alerts()

        return total

    def run(self):

        while not self.stop_event.is_set():

            try:
                self.run_once()
            except Exception as error:
                self.log(f"Erro no monitoramento: {error}")

            monitoramentos = self.database.listar_monitoramentos(somente_ativos=True)
            intervalo = min(
                [item["intervalo_minutos"] for item in monitoramentos],
                default=30
            )

            self.stop_event.wait(max(intervalo, 1) * 60)

        self.running = False

    def execute_monitoring(self, monitoramento):

        termo = monitoramento["termo"]
        lojas = self.parse_stores(monitoramento["lojas"])

        if not lojas:
            lojas = StoreManager.stable_store_names()

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
            self.log(f"Notificacao automatica: {result}")

    def notify_pending_async(self):

        threading.Thread(
            target=self.notify_pending_alerts,
            daemon=True
        ).start()

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
