from src.database import Database
from src.ui.main_window import MainWindow


class PromoBot:

    def __init__(self) -> None:

        self.database = Database()

        self.app = MainWindow(self.database)

        self.integrar()

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
