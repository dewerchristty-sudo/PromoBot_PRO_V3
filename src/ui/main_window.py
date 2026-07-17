import customtkinter as ctk

from src.core.monitor import MonitorRunner
from src.ui.alerts_page import AlertsPage
from src.ui.dashboard import Dashboard
from src.ui.history_page import HistoryPage
from src.ui.monitor_page import MonitorPage
from src.ui.offers_page import OffersPage
from src.ui.search_page import SearchPage
from src.ui.products_page import ProductsPage
from src.ui.settings_page import SettingsPage


class MainWindow(ctk.CTk):

    def __init__(self, database):
        super().__init__()

        self.database = database
        self.monitor_runner = MonitorRunner(database, self.log_monitor_status)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("PromoBot_PRO V3")
        self.geometry("1280x720")
        self.minsize(1100, 650)

        self.criar_interface()
        self.after(1000, self.iniciar_monitor_automatico)
        self.protocol("WM_DELETE_WINDOW", self.fechar)

    # ===============================================

    def criar_interface(self):

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.menu = ctk.CTkFrame(
            self,
            width=220,
            corner_radius=0
        )

        self.menu.grid(
            row=0,
            column=0,
            sticky="ns"
        )

        self.menu.grid_propagate(False)

        ctk.CTkLabel(
            self.menu,
            text="PromoBot_PRO",
            font=("Arial", 22, "bold")
        ).pack(pady=25)

        botoes = [

            ("Dashboard", self.mostrar_dashboard),

            ("Buscar", self.mostrar_busca),

            ("Produtos", self.mostrar_produtos),

            ("Ofertas", self.mostrar_ofertas),

            ("Alertas", self.mostrar_alertas),

            ("Monitor", self.mostrar_monitor),

            ("Historico", self.mostrar_historico),

            ("Configuracoes", self.mostrar_configuracoes)

        ]

        for texto, comando in botoes:

            ctk.CTkButton(
                self.menu,
                text=texto,
                width=180,
                height=40,
                command=comando
            ).pack(pady=6)

        self.area = ctk.CTkFrame(self)

        self.area.grid(
            row=0,
            column=1,
            sticky="nsew"
        )

        self.status = ctk.CTkLabel(
            self,
            text="Sistema iniciado.",
            anchor="w",
            height=28
        )

        self.status.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew"
        )

        self.mostrar_dashboard()

    # ===============================================

    def limpar(self):

        for widget in self.area.winfo_children():
            widget.destroy()

    # ===============================================

    def mostrar_dashboard(self):

        self.limpar()

        dashboard = Dashboard(self.area, self.database)

        dashboard.pack(
            fill="both",
            expand=True
        )

        self.status.configure(
            text="Dashboard"
        )

    # ===============================================

    def mostrar_busca(self):

        self.limpar()

        SearchPage(
            self.area,
            self.database
        ).pack(
            fill="both",
            expand=True
        )

        self.status.configure(
            text="Busca"
        )

    # ===============================================

    def mostrar_produtos(self):

        self.limpar()

        ProductsPage(
            self.area,
            self.database
        ).pack(
            fill="both",
            expand=True
        )

        self.status.configure(
            text=f"Produtos cadastrados: {self.database.total_produtos()}"
        )

    # ===============================================

    def mostrar_historico(self):

        self.limpar()

        HistoryPage(
            self.area,
            self.database
        ).pack(
            fill="both",
            expand=True
        )

        self.status.configure(
            text="Historico"
        )

    # ===============================================

    def mostrar_alertas(self):

        self.limpar()

        AlertsPage(
            self.area,
            self.database
        ).pack(
            fill="both",
            expand=True
        )

        self.status.configure(
            text="Alertas"
        )

    # ===============================================

    def mostrar_monitor(self):

        self.limpar()

        MonitorPage(
            self.area,
            self.database,
            self.monitor_runner
        ).pack(
            fill="both",
            expand=True
        )

        self.status.configure(
            text="Monitoramento"
        )

    # ===============================================

    def mostrar_ofertas(self):

        self.limpar()

        OffersPage(
            self.area,
            self.database
        ).pack(
            fill="both",
            expand=True
        )

        self.status.configure(
            text="Ofertas"
        )

    # ===============================================

    def mostrar_configuracoes(self):

        self.limpar()

        SettingsPage(
            self.area,
            self.database
        ).pack(
            fill="both",
            expand=True
        )

        self.status.configure(
            text="Configuracoes"
        )

    # ===============================================

    def iniciar_monitor_automatico(self):

        ativos = self.database.listar_monitoramentos(somente_ativos=True)

        if ativos and not self.monitor_runner.running:
            self.monitor_runner.start()
            self.status.configure(
                text=f"Monitor automatico iniciado | {len(ativos)} ativo(s)"
            )

    # ===============================================

    def log_monitor_status(self, texto):

        self.after(0, lambda: self.status.configure(text=texto))

    # ===============================================

    def fechar(self):

        self.monitor_runner.stop()
        self.destroy()
