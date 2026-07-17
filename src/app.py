from src.database import Database
from src.ui.main_window import MainWindow


class PromoBot:

    def __init__(self):

        self.database = Database()

        self.app = MainWindow(self.database)

        self.integrar()

    # =========================================

    def integrar(self):

        self.app.database = self.database

    # =========================================

    def run(self):

        self.app.mainloop()

        self.database.fechar()