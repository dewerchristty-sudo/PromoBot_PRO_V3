from src.database import Database
from src.ui.main_window import MainWindow


class PromoBot:

    def __init__(self, db_path=None, startup_probe=False) -> None:

        from src.startup_diagnostics import startup_log
        startup_log("06g PromoBot.init iniciado")


        self.database = Database(db_path)
        startup_log("06h Database criado")

        self.app = MainWindow(self.database, startup_probe=startup_probe)
        startup_log("06i MainWindow criada")

        self.integrar()
        startup_log("06j PromoBot.init concluido")

    # =========================================

    def integrar(self) -> None:

        self.app.database = self.database

    # =========================================

    def run(self) -> None:

        try:
            self.app.mainloop()
        finally:
            clean = self.app.shutdown_clean
            if clean is None:
                clean = self.app.monitor_runner.shutdown(timeout=5)
                clean = self.app.wait_for_background_workers(timeout=5) and clean
            if clean:
                self.database.fechar()
