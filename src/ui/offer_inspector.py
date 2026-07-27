import json

import customtkinter as ctk


class OfferInspector(ctk.CTkToplevel):

    def __init__(self, master, item):
        super().__init__(master)
        self.title("Diagnóstico da Oferta")
        self.geometry("820x680")
        self.minsize(680, 520)

        ctk.CTkLabel(
            self,
            text=item.get("title", "Oferta"),
            font=("Arial", 22, "bold"),
            wraplength=760,
        ).pack(fill="x", padx=20, pady=(18, 10))

        summary = ctk.CTkFrame(self)
        summary.pack(fill="x", padx=20, pady=(0, 10))
        fields = (
            ("Loja", item.get("store", "")),
            ("Categoria", item.get("category", "")),
            ("Preço atual", self.money(item.get("current_price"))),
            ("Menor preço", self.money(item.get("historical_minimum"))),
            ("Maior preço", self.money(item.get("historical_maximum"))),
            ("Média", self.money(item.get("historical_average"))),
            ("Observações", item.get("history_samples", 0)),
            ("Score", item.get("score", 0)),
            ("Status", item.get("status", "")),
            ("Scheduler", item.get("scheduler_status", "")),
        )
        for index, (label, value) in enumerate(fields):
            row, column = divmod(index, 2)
            ctk.CTkLabel(
                summary,
                text=f"{label}: {value}",
                anchor="w",
            ).grid(
                row=row,
                column=column,
                sticky="ew",
                padx=12,
                pady=5,
            )
        summary.grid_columnconfigure((0, 1), weight=1)

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=20, pady=(0, 18))
        diagnostic_tab = tabs.add("Diagnóstico")
        decisions_tab = tabs.add("Decisões")
        raw_tab = tabs.add("Dados")

        diagnostic = item.get("diagnostic") or {}
        diagnostic_text = ctk.CTkTextbox(diagnostic_tab)
        diagnostic_text.pack(fill="both", expand=True, padx=8, pady=8)
        for key, value in diagnostic.items():
            diagnostic_text.insert("end", f"{key}: {value}\n")
        diagnostic_text.configure(state="disabled")

        decisions_text = ctk.CTkTextbox(decisions_tab)
        decisions_text.pack(fill="both", expand=True, padx=8, pady=8)
        for decision in item.get("decisions", ()):
            decisions_text.insert(
                "end",
                f"{decision.get('created_at', '')} | "
                f"{decision.get('previous_status', '')} → "
                f"{decision.get('new_status', '')} | "
                f"{decision.get('reason', '')}\n",
            )
        decisions_text.configure(state="disabled")

        raw_text = ctk.CTkTextbox(raw_tab)
        raw_text.pack(fill="both", expand=True, padx=8, pady=8)
        raw_text.insert(
            "end",
            json.dumps(item, ensure_ascii=False, indent=2, default=str),
        )
        raw_text.configure(state="disabled")

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
