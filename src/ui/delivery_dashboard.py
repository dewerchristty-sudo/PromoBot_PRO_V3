import re
from tkinter import ttk

import customtkinter as ctk

from src.core.delivery_models import (
    DeliveryStatus,
    mask_delivery_destination,
)
from src.database.delivery_repository import DeliveryRepository


class DeliveryDashboard(ctk.CTkFrame):
    """Painel estritamente somente leitura das entregas por destino."""

    STATUS_FILTERS = {
        "Todos": None,
        "Enviado": DeliveryStatus.SENT,
        "Aguardando nova tentativa": DeliveryStatus.WAITING_RETRY,
        "Falha definitiva": DeliveryStatus.DEFINITIVE_FAILURE,
        "Revisão necessária": DeliveryStatus.REVIEW_REQUIRED,
    }
    CHANNEL_FILTERS = ("Todos os canais", "WhatsApp", "Telegram")
    SUMMARY_FIELDS = (
        ("Total", "total"),
        ("Enviados", "sent"),
        ("Pendentes", "pending"),
        ("Aguardando retry", "waiting_retry"),
        ("Falhas definitivas", "definitive_failure"),
        ("Revisões necessárias", "review_required"),
    )

    def __init__(self, master, database, repository=None):
        super().__init__(master)
        self.database = database
        self.owns_repository = repository is None
        self.repository = repository or DeliveryRepository(database.db)
        self.deliveries_by_item = {}
        self.summary_labels = {}
        self.create_interface()
        self.refresh()

    def create_interface(self):
        ctk.CTkLabel(
            self,
            text="Entregas por Destino",
            font=("Arial", 28, "bold"),
        ).pack(pady=(18, 8))
        ctk.CTkLabel(
            self,
            text="Consulta operacional somente leitura.",
        ).pack(pady=(0, 12))

        filters = ctk.CTkFrame(self)
        filters.pack(fill="x", padx=18, pady=(0, 8))
        self.status_filter = ctk.CTkOptionMenu(
            filters,
            values=list(self.STATUS_FILTERS),
            command=lambda _value: self.apply_filters(),
        )
        self.status_filter.set("Todos")
        self.status_filter.pack(side="left", padx=6, pady=8)
        self.channel_filter = ctk.CTkOptionMenu(
            filters,
            values=list(self.CHANNEL_FILTERS),
            command=lambda _value: self.apply_filters(),
        )
        self.channel_filter.set("Todos os canais")
        self.channel_filter.pack(side="left", padx=6, pady=8)
        ctk.CTkButton(
            filters,
            text="Atualizar",
            width=100,
            command=self.refresh,
        ).pack(side="left", padx=6, pady=8)
        self.status_label = ctk.CTkLabel(filters, text="", anchor="e")
        self.status_label.pack(side="right", padx=8)

        summary = ctk.CTkFrame(self, fg_color="transparent")
        summary.pack(fill="x", padx=18, pady=(0, 8))
        for index, (title, field) in enumerate(self.SUMMARY_FIELDS):
            card = ctk.CTkFrame(summary)
            card.grid(row=0, column=index, padx=4, sticky="nsew")
            ctk.CTkLabel(card, text=title, font=("Arial", 11, "bold")).pack(
                pady=(8, 2)
            )
            label = ctk.CTkLabel(card, text="0", font=("Arial", 20))
            label.pack(pady=(0, 8))
            self.summary_labels[field] = label
            summary.grid_columnconfigure(index, weight=1)

        content = ctk.CTkFrame(self)
        content.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        columns = (
            "canal",
            "destino",
            "status",
            "tentativas",
            "proxima",
            "erro",
            "externo",
            "criado",
            "atualizado",
            "enviado",
        )
        headings = (
            "Canal",
            "Destino",
            "Status",
            "Tentativas",
            "Próxima tentativa",
            "Último erro",
            "ID externo",
            "Criado",
            "Atualizado",
            "Enviado",
        )
        widths = (80, 120, 155, 75, 145, 230, 115, 145, 145, 145)
        self.tree = ttk.Treeview(
            content,
            columns=columns,
            show="headings",
            height=12,
        )
        for column, heading, width in zip(columns, headings, widths):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, minwidth=60)
        scrollbar = ttk.Scrollbar(
            content,
            orient="vertical",
            command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(fill="both", expand=True, padx=(8, 0), pady=(8, 4))
        scrollbar.place(relx=1.0, rely=0, relheight=0.68, anchor="ne")
        self.tree.bind("<<TreeviewSelect>>", self.show_attempts)

        ctk.CTkLabel(
            content,
            text="Histórico de tentativas da entrega selecionada",
            anchor="w",
        ).pack(fill="x", padx=8, pady=(6, 2))
        self.attempts = ctk.CTkTextbox(content, height=125)
        self.attempts.pack(fill="x", padx=8, pady=(0, 8))

    def refresh(self):
        try:
            self.all_deliveries = self.repository.list(limit=1000)
            self.status_label.configure(text="Consulta atualizada")
        except Exception as error:
            self.all_deliveries = []
            self.status_label.configure(
                text=f"Falha na consulta: {self.safe_text(error)}"
            )
        counts = self.summary(self.all_deliveries)
        for field, label in self.summary_labels.items():
            label.configure(text=str(counts[field]))
        self.apply_filters()

    def apply_filters(self):
        status = self.STATUS_FILTERS.get(self.status_filter.get())
        channel = self.channel_filter.get()
        deliveries = self.filtered(
            self.all_deliveries,
            status=status,
            channel=channel,
        )
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.deliveries_by_item = {}
        for delivery in deliveries:
            item = self.tree.insert(
                "",
                "end",
                values=self.delivery_values(delivery),
            )
            self.deliveries_by_item[item] = delivery
        self.attempts.delete("1.0", "end")
        self.attempts.insert(
            "end",
            "Selecione uma entrega para consultar suas tentativas."
            if deliveries else "Nenhuma entrega encontrada.",
        )

    def show_attempts(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        delivery = self.deliveries_by_item.get(selection[0])
        if delivery is None:
            return
        try:
            attempts = self.repository.attempts_for(delivery.id)
            text = self.attempt_history(attempts, delivery.destination)
        except Exception as error:
            text = f"Falha na consulta: {self.safe_text(error)}"
        self.attempts.delete("1.0", "end")
        self.attempts.insert("end", text)

    @classmethod
    def filtered(cls, deliveries, status=None, channel="Todos os canais"):
        result = list(deliveries)
        if status is not None:
            status = DeliveryStatus(status)
            result = [item for item in result if item.status == status]
        if channel != "Todos os canais":
            expected = channel.casefold()
            result = [
                item for item in result
                if str(item.channel).casefold() == expected
            ]
        return result

    @staticmethod
    def summary(deliveries):
        deliveries = list(deliveries)
        return {
            "total": len(deliveries),
            "sent": sum(
                item.status == DeliveryStatus.SENT for item in deliveries
            ),
            "pending": sum(
                item.status == DeliveryStatus.PENDING for item in deliveries
            ),
            "waiting_retry": sum(
                item.status == DeliveryStatus.WAITING_RETRY
                for item in deliveries
            ),
            "definitive_failure": sum(
                item.status == DeliveryStatus.DEFINITIVE_FAILURE
                for item in deliveries
            ),
            "review_required": sum(
                item.status == DeliveryStatus.REVIEW_REQUIRED
                for item in deliveries
            ),
        }

    @classmethod
    def delivery_values(cls, delivery):
        return (
            cls.safe_text(delivery.channel),
            mask_delivery_destination(delivery.destination),
            delivery.status.value,
            delivery.attempts,
            cls.datetime_text(delivery.next_attempt_at),
            cls.safe_text(delivery.last_error, delivery.destination),
            cls.safe_text(delivery.external_id, delivery.destination),
            cls.datetime_text(delivery.created_at),
            cls.datetime_text(delivery.updated_at),
            cls.datetime_text(delivery.sent_at),
        )

    @classmethod
    def attempt_history(cls, attempts, destination=""):
        rows = []
        for attempt in attempts:
            rows.append(
                " | ".join((
                    f"Tentativa {attempt.attempt_number}",
                    attempt.status.value,
                    f"início: {cls.datetime_text(attempt.started_at)}",
                    f"fim: {cls.datetime_text(attempt.finished_at)}",
                    f"erro: {cls.safe_text(attempt.error, destination)}",
                    f"ID externo: {cls.safe_text(attempt.external_id, destination)}",
                ))
            )
        return "\n".join(rows) if rows else "Nenhuma tentativa registrada."

    @staticmethod
    def datetime_text(value):
        if value is None:
            return ""
        return value.astimezone().strftime("%d/%m/%Y %H:%M:%S")

    @staticmethod
    def safe_text(value, destination=""):
        text = str(value or "")
        if destination:
            text = text.replace(str(destination), "***DESTINO***")
        text = re.sub(
            r"(?i)data:[^;\s]+;base64,[a-z0-9+/=]+",
            "[BASE64 OMITIDO]",
            text,
        )
        text = re.sub(
            r"(?i)\b(token|authorization|password|senha|api[_-]?key)"
            r"\s*[:=]\s*\S+",
            r"\1=***",
            text,
        )
        text = re.sub(r"\b\d{10,22}(?:@g\.us)?\b", "***DESTINO***", text)
        text = re.sub(
            r"\b[A-Za-z0-9+/]{120,}={0,2}\b",
            "[CONTEÚDO OMITIDO]",
            text,
        )
        return text[:300]

    def destroy(self):
        if self.owns_repository:
            self.repository.close()
            self.owns_repository = False
        super().destroy()
