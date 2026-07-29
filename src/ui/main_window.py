import threading
import time

import customtkinter as ctk

from src.core.monitor import MonitorRunner
from src.ui.affiliate_links_page import AffiliateLinksPage
from src.ui.alerts_page import AlertsPage
from src.ui.dashboard import Dashboard
from src.ui.history_page import HistoryPage
from src.ui.monitor_page import MonitorPage
from src.ui.offers_page import OffersPage
from src.ui.search_page import SearchPage
from src.ui.products_page import ProductsPage
from src.ui.settings_page import SettingsPage
from src.ui.groups_page import GroupsPage
from src.ui.review_page import ReviewPage
from src.ui.growth_page import GrowthPage
from src.ui.category_hub_page import CategoryHubPage
from src.ui.daily_deals_page import DailyDealsPage
from src.ui.offer_dashboard import OfferDashboard
from src.ui.delivery_dashboard import DeliveryDashboard


class MainWindow(ctk.CTk):

    def __init__(self, database):
        super().__init__()

        self.database = database
        self.background_workers = set()
        self.background_workers_lock = threading.Lock()
        self.pages = {}
        self.current_page = None
        self.shutdown_clean = None
        self.monitor_runner = MonitorRunner(database, self.log_monitor_status)
        self.monitor_runner.start_supervisor()

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

            ("Inteligencia", self.mostrar_inteligencia),

            ("Central Categorias", self.mostrar_central_categorias),

            ("Ofertas do Dia", self.mostrar_ofertas_do_dia),

            ("Buscar", self.mostrar_busca),

            ("Produtos", self.mostrar_produtos),

            ("Ofertas", self.mostrar_ofertas),

            ("Alertas", self.mostrar_alertas),

            ("Links Afiliados", self.mostrar_links_afiliados),

            ("Pendencias", self.mostrar_pendencias),

            ("Crescimento", self.mostrar_crescimento),

            ("Grupos & Categorias", self.mostrar_grupos),

            ("Monitor", self.mostrar_monitor),

            ("Historico", self.mostrar_historico),

            ("Entregas", self.mostrar_entregas),

            ("Configuracoes", self.mostrar_configuracoes)

        ]

        for texto, comando in botoes:

            ctk.CTkButton(
                self.menu,
                text=texto,
                width=180,
                height=34,
                command=comando
            ).pack(pady=3)

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
            widget.pack_forget()

    def mostrar_pagina(self, key, factory, status_text):

        if self.current_page == key:
            return self.pages.get(key)

        self.status.configure(text=f"Abrindo {status_text}...")
        self.update_idletasks()
        self.limpar()

        page = self.pages.get(key)
        if page is None or not page.winfo_exists():
            page = factory()
            self.pages[key] = page

        page.pack(fill="both", expand=True)
        page.tkraise()
        self.current_page = key
        self.status.configure(text=status_text)
        return page

    # ===============================================

    def mostrar_dashboard(self):

        self.mostrar_pagina(
            "dashboard",
            lambda: Dashboard(self.area, self.database, self.monitor_runner),
            "Dashboard",
        )

    def mostrar_inteligencia(self):

        self.mostrar_pagina(
            "inteligencia",
            lambda: OfferDashboard(self.area),
            "Inteligência de ofertas — modo sombra",
        )

    # ===============================================

    def mostrar_busca(self):

        self.mostrar_pagina(
            "busca",
            lambda: SearchPage(self.area, self.database),
            "Busca",
        )

    def mostrar_central_categorias(self):

        self.mostrar_pagina(
            "central_categorias",
            lambda: CategoryHubPage(self.area, self.database),
            "Central de Categorias",
        )

    def mostrar_ofertas_do_dia(self):

        self.mostrar_pagina(
            "ofertas_dia",
            lambda: DailyDealsPage(
                self.area, self.database, self.monitor_runner
            ),
            "Ofertas do Dia e Promocoes",
        )

    # ===============================================

    def mostrar_produtos(self):

        self.mostrar_pagina(
            "produtos",
            lambda: ProductsPage(self.area, self.database),
            f"Produtos cadastrados: {self.database.total_produtos()}",
        )

    # ===============================================

    def mostrar_historico(self):

        self.mostrar_pagina(
            "historico",
            lambda: HistoryPage(self.area, self.database),
            "Historico",
        )

    def mostrar_entregas(self):

        self.mostrar_pagina(
            "entregas",
            lambda: DeliveryDashboard(self.area, self.database),
            "Entregas por destino",
        )

    # ===============================================

    def mostrar_alertas(self):

        self.mostrar_pagina(
            "alertas",
            lambda: AlertsPage(self.area, self.database),
            "Alertas",
        )

    # ===============================================

    def mostrar_monitor(self):

        self.mostrar_pagina(
            "monitor",
            lambda: MonitorPage(
                self.area, self.database, self.monitor_runner
            ),
            "Monitoramento",
        )

    # ===============================================

    def mostrar_links_afiliados(self):

        self.mostrar_pagina(
            "links_afiliados",
            lambda: AffiliateLinksPage(self.area, self.database),
            "Links de afiliado pendentes",
        )

    # ===============================================

    def mostrar_ofertas(self):

        self.mostrar_pagina(
            "ofertas",
            lambda: OffersPage(self.area, self.database),
            "Ofertas",
        )

    def mostrar_pendencias(self):

        self.mostrar_pagina(
            "pendencias",
            lambda: ReviewPage(self.area, self.database),
            f"Pendencias para revisao: {self.database.total_pendencias_revisao()}",
        )

    def mostrar_grupos(self):

        self.mostrar_pagina(
            "grupos",
            lambda: GroupsPage(self.area, self.database),
            "Grupos, categorias e relatorios",
        )

    def mostrar_crescimento(self):

        self.mostrar_pagina(
            "crescimento",
            lambda: GrowthPage(self.area, self.database),
            "Plano de crescimento e oferta do dia",
        )

    # ===============================================

    def mostrar_configuracoes(self):

        self.mostrar_pagina(
            "configuracoes",
            lambda: SettingsPage(self.area, self.database),
            "Configuracoes",
        )

    # ===============================================

    def iniciar_monitor_automatico(self):

        ativos = self.database.listar_monitoramentos(somente_ativos=True)
        self.monitor_runner.notify_pending_async()

        if ativos and not self.monitor_runner.running:
            self.monitor_runner.start()
            self.status.configure(
                text=f"Monitor automatico iniciado | {len(ativos)} ativo(s)"
            )

    # ===============================================

    def log_monitor_status(self, texto):

        self.after(0, lambda: self.status.configure(text=texto))

    def register_background_worker(self, worker):

        with self.background_workers_lock:
            self.background_workers.add(worker)

    def unregister_background_worker(self, worker):

        with self.background_workers_lock:
            self.background_workers.discard(worker)

    def wait_for_background_workers(self, timeout=5):

        current = threading.current_thread()
        deadline = time.monotonic() + max(float(timeout), 0)
        with self.background_workers_lock:
            workers = list(self.background_workers)
        for worker in workers:
            if worker is not current:
                worker.join(max(deadline - time.monotonic(), 0))
        return all(
            worker is current or not worker.is_alive()
            for worker in workers
        )

    # ===============================================

    def fechar(self):

        monitor_clean = self.monitor_runner.shutdown(timeout=5)
        workers_clean = self.wait_for_background_workers(timeout=5)
        self.shutdown_clean = monitor_clean and workers_clean
        self.destroy()
