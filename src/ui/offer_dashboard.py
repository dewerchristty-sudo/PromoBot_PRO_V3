from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.charts import OfferCharts
from src.offers.statistics import (
    OfferDashboardFilter,
    OfferStatistics,
)
from src.ui.offer_charts import OfferChartCanvas
from src.ui.offer_inspector import OfferInspector
from src.ui.offer_activation_wizard import OfferActivationWizard


class OfferDashboard(ctk.CTkFrame):
    """Painel somente leitura do domínio inteligente em modo sombra."""

    CARD_FIELDS = (
        ("Analisados", "total_analyzed"),
        ("Aprovados", "total_approved"),
        ("Excelentes", "excellent_offers"),
        ("Boas", "good_offers"),
        ("Descartados", "total_discarded"),
        ("Duplicados", "total_duplicate"),
        ("Bloqueados", "total_blocked"),
        ("Na fila", "total_queued"),
        ("Scheduler sombra", "total_selected_shadow"),
        ("Score médio", "average_score"),
        ("Maior Score", "maximum_score"),
        ("Tempo médio ms", "average_processing_ms"),
        ("Modo atual", "current_mode"),
        ("Scheduler ativo", "active_scheduler"),
        ("Canary %", "canary_percent"),
        ("Envios legado", "legacy_sends"),
        ("Envios inteligente", "intelligent_sends"),
        ("Comparações", "comparisons"),
        ("Rollbacks", "rollbacks"),
        ("Diferenças", "differences"),
    )

    def __init__(self, master, repository=None):
        super().__init__(master)
        self.owns_repository = repository is None
        self.repository = repository or OfferPipelineRepository(
            Path(os.getenv("OFFER_SHADOW_DB_PATH", "offer_shadow.db"))
        )
        self.repository.migrate()
        self.statistics = OfferStatistics(self.repository)
        self.snapshot = None
        self.loading = False
        self.destroyed = False
        self.refresh_ms = max(int(float(os.getenv(
            "OFFER_DASHBOARD_REFRESH_SECONDS",
            "10",
        )) * 1000), 2000)
        self.card_labels = {}
        self.tree_items = {}
        self.create_interface()
        self.refresh_async()

    def create_interface(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(14, 8))
        ctk.CTkLabel(
            header,
            text="Inteligência de Ofertas — Modo Sombra",
            font=("Arial", 27, "bold"),
        ).pack(side="left")
        self.status = ctk.CTkLabel(
            header,
            text="Carregando...",
            text_color="#a9c9ff",
        )
        self.status.pack(side="right")

        self.create_filters()

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        overview = self.tabs.add("Visão geral")
        queue_tab = self.tabs.add("Fila e Top 20")
        charts_tab = self.tabs.add("Gráficos")
        logs_tab = self.tabs.add("Logs")
        activation_tab = self.tabs.add("Ativação Controlada")

        self.create_overview(overview)
        self.create_queue_table(queue_tab)
        self.create_charts(charts_tab)
        self.create_logs(logs_tab)
        OfferActivationWizard(activation_tab, self.repository).pack(
            fill="both", expand=True
        )

    def create_filters(self):
        frame = ctk.CTkFrame(self)
        frame.pack(fill="x", padx=18, pady=(0, 8))
        self.store_filter = ctk.CTkOptionMenu(frame, values=["Todas as lojas"])
        self.category_filter = ctk.CTkOptionMenu(
            frame, values=["Todas as categorias"]
        )
        self.status_filter = ctk.CTkOptionMenu(
            frame,
            values=["Todos os estados", *OfferStatistics.QUEUE_STATES],
        )
        self.score_filter = ctk.CTkEntry(
            frame, width=95, placeholder_text="Score mín."
        )
        self.product_filter = ctk.CTkEntry(
            frame, width=210, placeholder_text="Buscar produto"
        )
        self.date_filter = ctk.CTkOptionMenu(
            frame,
            values=["Todo período", "Últimas 24h", "Últimos 7 dias", "Últimos 30 dias"],
        )
        for widget in (
            self.store_filter,
            self.category_filter,
            self.status_filter,
            self.score_filter,
            self.product_filter,
            self.date_filter,
        ):
            widget.pack(side="left", padx=5, pady=8)
        ctk.CTkButton(
            frame,
            text="Aplicar",
            width=90,
            command=self.refresh_async,
        ).pack(side="left", padx=5)

    def create_overview(self, parent):
        self.cards_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.cards_frame.pack(fill="x", padx=8, pady=8)
        for index, (title, field) in enumerate(self.CARD_FIELDS):
            frame = ctk.CTkFrame(self.cards_frame, height=78)
            frame.grid(
                row=index // 6,
                column=index % 6,
                padx=4,
                pady=4,
                sticky="nsew",
            )
            ctk.CTkLabel(frame, text=title, font=("Arial", 12, "bold")).pack(
                pady=(9, 2)
            )
            label = ctk.CTkLabel(frame, text="0", font=("Arial", 21))
            label.pack(pady=(0, 8))
            self.card_labels[field] = label
        for column in range(6):
            self.cards_frame.grid_columnconfigure(column, weight=1)

        self.queue_summary = ctk.CTkTextbox(parent, height=180)
        self.queue_summary.pack(fill="both", expand=True, padx=10, pady=10)

    def create_queue_table(self, parent):
        columns = (
            "produto", "loja", "categoria", "preco",
            "minimo", "score", "status", "motivo",
        )
        self.tree = ttk.Treeview(parent, columns=columns, show="headings")
        headings = (
            "Produto", "Loja", "Categoria", "Preço atual",
            "Menor preço", "Score", "Status", "Motivo",
        )
        widths = (300, 105, 120, 90, 90, 65, 115, 180)
        for column, heading, width in zip(columns, headings, widths):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, minwidth=55)
        scrollbar = ttk.Scrollbar(
            parent, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=10)
        self.tree.bind("<Double-1>", self.open_selected)

    def create_charts(self, parent):
        self.chart_widgets = []
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=6, pady=6)
        for index in range(6):
            chart = OfferChartCanvas(grid)
            chart.grid(
                row=index // 2,
                column=index % 2,
                padx=5,
                pady=5,
                sticky="nsew",
            )
            self.chart_widgets.append(chart)
        grid.grid_columnconfigure((0, 1), weight=1)
        grid.grid_rowconfigure((0, 1, 2), weight=1)

    def create_logs(self, parent):
        self.logs = ctk.CTkTextbox(parent)
        self.logs.pack(fill="both", expand=True, padx=10, pady=10)

    def current_filters(self):
        minimum_score = None
        try:
            text = self.score_filter.get().strip()
            minimum_score = float(text.replace(",", ".")) if text else None
        except ValueError:
            minimum_score = None
        date_from = None
        selected_date = self.date_filter.get()
        now = datetime.now(timezone.utc)
        if selected_date == "Últimas 24h":
            date_from = now - timedelta(hours=24)
        elif selected_date == "Últimos 7 dias":
            date_from = now - timedelta(days=7)
        elif selected_date == "Últimos 30 dias":
            date_from = now - timedelta(days=30)
        store = self.store_filter.get()
        category = self.category_filter.get()
        status = self.status_filter.get()
        return OfferDashboardFilter(
            store="" if store == "Todas as lojas" else store,
            category="" if category == "Todas as categorias" else category,
            minimum_score=minimum_score,
            queue_status="" if status == "Todos os estados" else status,
            date_from=date_from,
            product_query=self.product_filter.get().strip(),
        )

    def refresh_async(self):
        if self.loading or self.destroyed:
            return
        self.loading = True
        filters = self.current_filters()
        self.status.configure(text="Atualizando...")

        def worker():
            try:
                snapshot = self.statistics.snapshot(filters)
                error = ""
            except Exception as exc:
                snapshot = None
                error = str(exc)
            if not self.destroyed:
                self.after(0, lambda: self.apply_snapshot(snapshot, error))

        threading.Thread(target=worker, daemon=True).start()

    def apply_snapshot(self, snapshot, error=""):
        self.loading = False
        if self.destroyed:
            return
        if error:
            self.status.configure(text=f"Falha ao consultar: {error}")
            return
        self.snapshot = snapshot
        self.status.configure(
            text=f"Atualizado {snapshot.generated_at.astimezone().strftime('%H:%M:%S')}"
        )
        self.update_filter_values(snapshot)
        self.update_cards(snapshot)
        self.update_table(snapshot)
        self.update_charts(snapshot)
        self.update_logs(snapshot)
        self.after(self.refresh_ms, self.refresh_async)

    def update_filter_values(self, snapshot):
        self.store_filter.configure(values=["Todas as lojas", *snapshot.stores])
        self.category_filter.configure(
            values=["Todas as categorias", *snapshot.categories]
        )

    def update_cards(self, snapshot):
        for _title, field in self.CARD_FIELDS:
            value = getattr(snapshot.metrics, field)
            if isinstance(value, float):
                text = f"{value:.2f}"
            else:
                text = str(value)
            self.card_labels[field].configure(text=text)
        self.queue_summary.delete("1.0", "end")
        self.queue_summary.insert("end", "Estados da fila\n\n")
        for status, total in snapshot.queue_counts.items():
            self.queue_summary.insert("end", f"{status}: {total}\n")

    def update_table(self, snapshot):
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.tree_items.clear()
        for item in snapshot.top_offers:
            tree_id = self.tree.insert("", "end", values=(
                item["title"],
                item["store"],
                item["category"],
                self.money(item["current_price"]),
                self.money(item["historical_minimum"]),
                f"{item['score']:.1f}",
                item["status"],
                item["blocked_reason"] or item["scheduler_status"],
            ))
            self.tree_items[tree_id] = item["pipeline_item_id"]

    def update_charts(self, snapshot):
        series = (
            OfferCharts.score_over_time(snapshot.hourly),
            OfferCharts.processing_time(snapshot.hourly),
            OfferCharts.products_by_group(
                "Produtos por loja", snapshot.by_store
            ),
            OfferCharts.products_by_group(
                "Produtos por categoria", snapshot.by_category, "#e78940"
            ),
            OfferCharts.approval(snapshot.metrics),
            OfferCharts.products_by_group(
                "Aprovados por loja",
                [
                    {"label": row["label"], "total": row["approved"]}
                    for row in snapshot.by_store
                ],
                "#55b86a",
            ),
        )
        for widget, chart_series in zip(self.chart_widgets, series):
            widget.set_series(chart_series)

    def update_logs(self, snapshot):
        self.logs.configure(state="normal")
        self.logs.delete("1.0", "end")
        for item in snapshot.recent_logs:
            self.logs.insert(
                "end",
                f"{item['created_at']} | Pipeline | {item['store']} | "
                f"Score {item['score']:.1f} | {item['classification']} | "
                f"Fila {item['queue_status'] or '-'} | "
                f"Scheduler {item['scheduler_status'] or '-'} | "
                f"{item['processing_ms']:.3f} ms | "
                f"{item['title']}\n",
            )
        self.logs.configure(state="disabled")

    def open_selected(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        pipeline_item_id = self.tree_items.get(selection[0])
        if pipeline_item_id is None:
            return
        item = self.statistics.inspect(pipeline_item_id)
        if item:
            OfferInspector(self, item)

    def destroy(self):
        self.destroyed = True
        if self.owns_repository:
            try:
                self.repository.close()
            except Exception:
                pass
        super().destroy()

    @staticmethod
    def money(value):
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            number = 0
        return (
            f"R$ {number:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )
