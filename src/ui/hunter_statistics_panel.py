"""Páginas operacionais de estatísticas embutidas no Monitor."""
from __future__ import annotations

import customtkinter as ctk

from src.statistics.repository import StatisticsRepository
from src.delivery_diagnostics import DeliveryDiagnosticsRepository


class HunterStatisticsPanel(ctk.CTkFrame):
    TABS = (
        "Resumo", "Lojas", "Categorias", "Produtos", "Envios",
        "Evolução", "Erros", "Últimos envios", "Atividade", "Monitores",
        "Diagnóstico de entrega",
    )

    def __init__(
        self, master, database, repository=None, on_visibility_change=None,
        on_back=None, on_tab_change=None, diagnostic_repository=None,
    ):
        super().__init__(master, fg_color="#20262e")
        self.owns_repository = repository is None
        self.repository = None
        self.diagnostic_repository = None
        self.repository = repository or StatisticsRepository(database.db)
        self.owns_diagnostic_repository = diagnostic_repository is None
        self.diagnostic_repository = (
            diagnostic_repository
            or DeliveryDiagnosticsRepository(
                database.db.resolve().parent / "promotion_hunter.db",
                database.db,
            )
        )
        self.on_visibility_change = on_visibility_change
        self.on_back = on_back
        self.on_tab_change = on_tab_change
        self.selected_tab = "Resumo"
        self.expanded = True
        self.snapshot = None
        self.snapshot_signature = None
        self.buttons = {}
        self.pages = {}
        self.page_widgets = {}
        self.rendered_signatures = {}
        self.diagnostic_snapshot = None
        self.diagnostic_signature = None
        self._build()

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(9, 5))
        ctk.CTkLabel(
            header, text="ESTATÍSTICAS DO CAÇADOR",
            font=("Arial", 16, "bold"), text_color="#8fdf8f",
        ).pack(side="left")
        self.back_button = ctk.CTkButton(
            header, text="← Voltar ao Monitor", width=150, height=30,
            command=self.back,
        )
        self.back_button.pack(side="right")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        navigation = ctk.CTkFrame(self.body, fg_color="transparent")
        navigation.pack(fill="x", pady=(0, 7))
        for index, tab in enumerate(self.TABS):
            navigation.grid_columnconfigure(index % 4, weight=1)
            button = ctk.CTkButton(
                navigation, text=tab, height=32,
                command=lambda value=tab: self.select(value),
            )
            button.grid(
                row=index // 4, column=index % 4, sticky="ew", padx=3, pady=3
            )
            self.buttons[tab] = button

        self.workspace = ctk.CTkFrame(self.body, fg_color="#171c22")
        self.workspace.pack(fill="both", expand=True)
        for tab in self.TABS:
            self._create_page(tab)
        self.pages[self.selected_tab].pack(fill="both", expand=True)
        self._highlight()

    def _create_page(self, tab):
        """Cria cada view uma única vez; alternar abas não recria widgets."""
        page = ctk.CTkFrame(self.workspace, fg_color="transparent")
        ctk.CTkLabel(
            page, text=tab.upper(), font=("Arial", 20, "bold"), anchor="w",
        ).pack(fill="x", padx=18, pady=(16, 8))
        self.pages[tab] = page
        if tab in {"Atividade", "Monitores"}:
            return
        content = ctk.CTkTextbox(page, wrap="word", font=("Arial", 14))
        content.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        content.configure(state="disabled")
        self.page_widgets[tab] = content

    def back(self):
        if self.on_back is not None:
            self.on_back()

    def select(self, tab):
        if tab not in self.TABS or tab == self.selected_tab:
            return
        self.pages[self.selected_tab].pack_forget()
        self.selected_tab = tab
        self.pages[tab].pack(fill="both", expand=True)
        self._highlight()
        on_tab_change = getattr(self, "on_tab_change", None)
        if on_tab_change is not None:
            on_tab_change(tab)
        self.render_selected()

    def _highlight(self):
        for name, button in self.buttons.items():
            button.configure(
                fg_color="#287a45" if name == self.selected_tab else "#3b4654"
            )

    @staticmethod
    def signature(snapshot):
        if snapshot is None:
            return None
        values = vars(snapshot).copy()
        values.pop("generated_at", None)
        return repr(values)

    def refresh(self):
        """Usa apenas o timer central do Monitor e o snapshot já existente."""
        if not self.expanded:
            return False
        if getattr(self, "selected_tab", "Resumo") == "Diagnóstico de entrega":
            snapshot = self.diagnostic_repository.snapshot()
            signature = self.signature(snapshot)
            if signature == self.diagnostic_signature:
                return False
            self.diagnostic_snapshot = snapshot
            self.diagnostic_signature = signature
            return self.render_delivery_diagnostics()
        snapshot = self.repository.snapshot()
        signature = self.signature(snapshot)
        if signature == self.snapshot_signature:
            return False
        self.snapshot = snapshot
        self.snapshot_signature = signature
        self.render_selected()
        return True

    def render_selected(self):
        if self.selected_tab == "Diagnóstico de entrega":
            if self.diagnostic_snapshot is None:
                return self.refresh()
            return self.render_delivery_diagnostics()
        if self.snapshot is None:
            return False
        tab = self.selected_tab
        if tab in {"Atividade", "Monitores"}:
            return False
        if self.rendered_signatures.get(tab) == self.snapshot_signature:
            return False
        widget = self.page_widgets[tab]
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", "\n".join(self.content_lines(tab, self.snapshot)))
        widget.configure(state="disabled")
        self.rendered_signatures[tab] = self.snapshot_signature
        return True

    def render_delivery_diagnostics(self):
        snapshot = self.diagnostic_snapshot
        if snapshot is None:
            return False
        widget = self.page_widgets["Diagnóstico de entrega"]
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        lines = ["FUNIL OPERACIONAL REAL", ""]
        for stage in snapshot.funnel:
            total = "não confirmado" if stage.total is None else str(stage.total)
            percentage = (
                "—" if stage.percentage is None
                else f"{stage.percentage:.1f}%"
            )
            reason = f" | motivo: {stage.main_reason}" if stage.main_reason else ""
            lines.append(f"{stage.name}: {total} ({percentage}){reason}")
        sections = (
            ("TOP MOTIVOS DE PERDA", snapshot.top_losses),
            ("IMAGENS INVÁLIDAS POR LOJA", snapshot.image_failures_by_store),
            ("LINKS AFILIADOS AUSENTES", snapshot.affiliate_failures),
            ("FALHAS EVOLUTION/DELIVERY", snapshot.evolution_failures),
            ("DESTINOS/CANAIS", snapshot.destinations),
        )
        for title, items in sections:
            lines.extend(("", title))
            lines.extend(f"{label}: {total}" for label, total in items)
            if not items:
                lines.append("Nenhum registro.")
        lines.extend(("", "FALHAS SQLITE"))
        lines.extend(
            f"{reason} | {total} | última: {latest}"
            for reason, total, latest in snapshot.sqlite_failures
        )
        if not snapshot.sqlite_failures:
            lines.append("Nenhuma falha registrada.")
        lines.extend(("", "RASTREAMENTO RECENTE"))
        for trace in snapshot.traces:
            reason = f" | {trace.reason}" if trace.reason else ""
            lines.append(
                f"#{trace.queue_id} | {trace.store} | {trace.stage} | "
                f"{trace.status} | tentativas={trace.attempts} | "
                f"{trace.title[:70]}{reason}"
            )
        lines.extend(("", "LIMITAÇÕES COMPROVADAS DO HISTÓRICO"))
        lines.extend(f"• {item}" for item in snapshot.limitations)
        widget.insert("end", "\n".join(lines))
        widget.configure(state="disabled")
        return True

    @staticmethod
    def _groups(groups, limit=10):
        values = tuple(groups)[:limit]
        return [f"{item.label}: {item.total}" for item in values] or [
            "Nenhum dado disponível."
        ]

    @classmethod
    def content_lines(cls, tab, value):
        if tab == "Resumo":
            return [
                f"Produtos encontrados: {value.total_products}",
                f"Envios realizados: {value.total_sends}",
                f"Pendências / bloqueios: {value.pending_reviews}",
                f"Erros: {value.failed_deliveries}",
            ]
        if tab == "Lojas":
            return cls._groups(value.products_by_store)
        if tab == "Categorias":
            return cls._groups(value.products_by_category.items)
        if tab == "Produtos":
            return cls._groups(value.most_sent_products)
        if tab == "Envios":
            return [f"Enviados: {value.total_sends}", *cls._groups(
                value.sends_by_channel
            )]
        if tab == "Evolução":
            return [
                "Coletas por dia", *[
                    f"{point.period}: {point.total}"
                    for point in value.daily_collections[-30:]
                ],
                "", "Envios por dia", *[
                    f"{point.period}: {point.total}"
                    for point in value.daily_sends[-30:]
                ],
            ]
        if tab == "Erros":
            return [f"Falhas registradas: {value.failed_deliveries}"]
        return [
            f"{item.sent_at} | {item.title} | {item.store} | "
            f"{item.channel} | {item.status}"
            for item in value.recent_sends
        ] or ["Nenhum envio disponível."]

    def destroy(self):
        if self.owns_repository:
            self.repository.close()
            self.owns_repository = False
        if self.owns_diagnostic_repository:
            self.diagnostic_repository.close()
            self.owns_diagnostic_repository = False
        super().destroy()
