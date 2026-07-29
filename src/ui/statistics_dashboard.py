from tkinter import ttk

import customtkinter as ctk

from src.statistics.repository import StatisticsRepository


class StatisticsDashboard(ctk.CTkFrame):
    """Central de estatísticas estritamente somente leitura."""

    SUMMARY_FIELDS = (
        ("Produtos coletados", "total_products"),
        ("Envios realizados", "total_sends"),
        ("Pendências de revisão", "pending_reviews"),
        ("Alertas ativos", "active_alerts"),
        ("Entregas em falha", "failed_deliveries"),
    )

    def __init__(self, master, database, repository=None):
        super().__init__(master)
        self.database = database
        self.owns_repository = repository is None
        self.repository = repository or StatisticsRepository(database.db)
        self.summary_labels = {}
        self.create_interface()
        self.refresh()

    def create_interface(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(14, 8))
        ctk.CTkLabel(
            header,
            text="Central de Estatísticas",
            font=("Arial", 28, "bold"),
        ).pack(side="left")
        self.status_label = ctk.CTkLabel(
            header,
            text="Consulta somente leitura",
        )
        self.status_label.pack(side="right", padx=8)
        ctk.CTkButton(
            header,
            text="Atualizar",
            width=100,
            command=self.refresh,
        ).pack(side="right", padx=8)

        summary = ctk.CTkFrame(self, fg_color="transparent")
        summary.pack(fill="x", padx=18, pady=(0, 8))
        for index, (title, field) in enumerate(self.SUMMARY_FIELDS):
            card = ctk.CTkFrame(summary)
            card.grid(row=0, column=index, padx=4, sticky="nsew")
            ctk.CTkLabel(
                card,
                text=title,
                font=("Arial", 11, "bold"),
            ).pack(pady=(8, 2))
            label = ctk.CTkLabel(card, text="0", font=("Arial", 20))
            label.pack(pady=(0, 8))
            self.summary_labels[field] = label
            summary.grid_columnconfigure(index, weight=1)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        overview = self.tabs.add("Distribuição")
        coverage = self.tabs.add("Cobertura")
        evolution = self.tabs.add("Evolução")
        recent = self.tabs.add("Últimos envios")
        self.create_distribution(overview)
        self.create_coverage(coverage)
        self.create_evolution(evolution)
        self.create_recent_sends(recent)

    def create_distribution(self, parent):
        self.stores_text = self.create_text_panel(parent, "Produtos por loja")
        self.channels_text = self.create_text_panel(parent, "Envios por canal")
        self.products_text = self.create_text_panel(
            parent, "Produtos mais enviados"
        )

    @staticmethod
    def create_text_panel(parent, title):
        frame = ctk.CTkFrame(parent)
        frame.pack(side="left", fill="both", expand=True, padx=5, pady=8)
        ctk.CTkLabel(
            frame, text=title, font=("Arial", 15, "bold")
        ).pack(pady=(8, 4))
        text = ctk.CTkTextbox(frame)
        text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        return text

    def create_coverage(self, parent):
        self.coverage_summary = ctk.CTkTextbox(parent, height=105)
        self.coverage_summary.pack(fill="x", padx=8, pady=8)
        lower = ctk.CTkFrame(parent, fg_color="transparent")
        lower.pack(fill="both", expand=True, padx=3, pady=(0, 8))
        self.categories_text = self.create_text_panel(
            lower, "Produtos por categoria"
        )
        self.sent_categories_text = self.create_text_panel(
            lower, "Categorias mais enviadas"
        )

    def create_evolution(self, parent):
        self.evolution_text = ctk.CTkTextbox(parent)
        self.evolution_text.pack(fill="both", expand=True, padx=8, pady=8)

    def create_recent_sends(self, parent):
        columns = ("data", "loja", "produto", "canal", "status")
        headings = ("Data", "Loja", "Produto", "Canal", "Status")
        widths = (145, 110, 410, 130, 90)
        self.recent_tree = ttk.Treeview(
            parent,
            columns=columns,
            show="headings",
            height=15,
        )
        for column, heading, width in zip(columns, headings, widths):
            self.recent_tree.heading(column, text=heading)
            self.recent_tree.column(column, width=width, minwidth=65)
        scrollbar = ttk.Scrollbar(
            parent,
            orient="vertical",
            command=self.recent_tree.yview,
        )
        self.recent_tree.configure(yscrollcommand=scrollbar.set)
        self.recent_tree.pack(
            side="left", fill="both", expand=True, padx=(8, 0), pady=8
        )
        scrollbar.pack(side="right", fill="y", padx=(0, 8), pady=8)

    def refresh(self):
        try:
            snapshot = self.repository.snapshot()
        except Exception as error:
            self.status_label.configure(
                text=f"Falha na consulta: {self.safe_text(error)}"
            )
            return
        for _title, field in self.SUMMARY_FIELDS:
            self.summary_labels[field].configure(
                text=str(getattr(snapshot, field))
            )
        self.fill_groups(self.stores_text, snapshot.products_by_store)
        self.fill_groups(self.channels_text, snapshot.sends_by_channel)
        self.fill_groups(self.products_text, snapshot.most_sent_products)
        self.fill_groups(
            self.categories_text,
            snapshot.products_by_category.items,
        )
        self.fill_groups(
            self.sent_categories_text,
            snapshot.sent_categories.items,
        )
        self.fill_coverage(snapshot)
        self.fill_evolution(snapshot)
        self.fill_recent(snapshot)
        self.status_label.configure(
            text=f"Atualizado às {snapshot.generated_at.astimezone():%H:%M:%S}"
        )

    @staticmethod
    def fill_groups(widget, groups):
        widget.delete("1.0", "end")
        text = "\n".join(
            f"{item.label}: {item.total}" for item in groups
        )
        widget.insert("end", text or "Nenhum dado disponível.")

    def fill_coverage(self, snapshot):
        products = snapshot.products_by_category
        sent = snapshot.sent_categories
        discount = snapshot.average_discount
        savings = snapshot.average_savings
        lines = (
            f"Categorias preenchidas: {products.covered} de {products.total} "
            f"produtos ({products.percentage:.1f}%).",
            f"Categoria identificada nos envios: {sent.covered} de "
            f"{sent.total} envios ({sent.percentage:.1f}%).",
            f"Desconto calculável: {discount.covered} de {discount.total} "
            f"produtos ({discount.percentage:.1f}%) | "
            f"média: {discount.average:.1f}%.",
            f"Economia calculável: {savings.covered} de {savings.total} "
            f"produtos ({savings.percentage:.1f}%) | "
            f"média: R$ {savings.average:.2f}.",
        )
        self.coverage_summary.delete("1.0", "end")
        self.coverage_summary.insert("end", "\n".join(lines))

    def fill_evolution(self, snapshot):
        sections = (
            ("Coletas por dia", snapshot.daily_collections),
            ("Envios por dia", snapshot.daily_sends),
            ("Coletas por semana", snapshot.weekly_collections),
            ("Envios por semana", snapshot.weekly_sends),
        )
        lines = []
        for title, points in sections:
            lines.append(title)
            lines.append("-" * len(title))
            lines.extend(
                f"{point.period}: {point.total}" for point in points
            )
            if not points:
                lines.append("Nenhum dado disponível.")
            lines.append("")
        self.evolution_text.delete("1.0", "end")
        self.evolution_text.insert("end", "\n".join(lines).rstrip())

    def fill_recent(self, snapshot):
        for item in self.recent_tree.get_children():
            self.recent_tree.delete(item)
        for send in snapshot.recent_sends:
            self.recent_tree.insert(
                "",
                "end",
                values=(
                    send.sent_at,
                    send.store,
                    send.title,
                    send.channel,
                    send.status,
                ),
            )

    @staticmethod
    def safe_text(value):
        text = str(value or "")
        return text[:160].replace("\n", " ")

    def destroy(self):
        if self.owns_repository:
            self.repository.close()
            self.owns_repository = False
        super().destroy()
