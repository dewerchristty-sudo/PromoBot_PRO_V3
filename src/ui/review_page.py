import json
import webbrowser
from tkinter import messagebox

import customtkinter as ctk

from src.core.notifier import Notifier


class ReviewPage(ctk.CTkFrame):

    FILTER_TYPES = {
        "Prioritarias": {"link_afiliado", "categoria", "imagem"},
        "Links afiliados": {"link_afiliado"},
        "Categorias e imagens": {"categoria", "imagem"},
        "Desconto baixo": {"desconto_insuficiente"},
        "Ofertas vencidas": {"oferta_vencida"},
        "Todas": None,
    }

    TYPE_LABELS = {
        "link_afiliado": "Link afiliado pendente",
        "categoria": "Categoria ou grupo pendente",
        "imagem": "Imagem pendente",
        "desconto_insuficiente": "Confirmar desconto",
        "oferta_vencida": "Confirmar oferta vencida",
        "loja_desabilitada": "Loja desabilitada",
    }

    def __init__(self, master, database):
        super().__init__(master)
        self.database = database
        self.notifier = Notifier(database)
        self.pending_by_label = {}
        self.all_pending = []
        self.create_interface()
        self.load_pending()

    def create_interface(self):
        ctk.CTkLabel(
            self, text="Pendências para Revisão", font=("Arial", 30, "bold")
        ).pack(pady=(20, 8))
        ctk.CTkLabel(
            self,
            text=(
                "O monitor continua trabalhando. Somente os produtos que precisam "
                "de confirmação ficam nesta lista."
            ),
        ).pack(pady=(0, 16))

        panel = ctk.CTkFrame(self)
        panel.pack(fill="both", expand=True, padx=28, pady=(0, 22))

        self.status = ctk.CTkLabel(panel, text="", anchor="w")
        self.status.pack(fill="x", padx=16, pady=(16, 6))
        self.filter_menu = ctk.CTkOptionMenu(
            panel,
            values=list(self.FILTER_TYPES),
            command=lambda _value: self.apply_filter(),
        )
        self.filter_menu.pack(fill="x", padx=16, pady=(0, 8))
        self.filter_menu.set("Prioritarias")
        self.menu = ctk.CTkOptionMenu(
            panel, values=["Carregando..."], command=self.show_selected
        )
        self.menu.pack(fill="x", padx=16, pady=(0, 10))

        buttons = ctk.CTkFrame(panel, fg_color="transparent")
        buttons.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkButton(buttons, text="Atualizar", command=self.load_pending).pack(
            side="left", padx=(0, 6)
        )
        ctk.CTkButton(
            buttons, text="Corrigir link", command=self.open_affiliate_links
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            buttons, text="Corrigir categoria", command=self.open_categories
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            buttons,
            text="Reavaliar e enviar",
            fg_color="#17813f",
            hover_color="#116530",
            command=self.retry_selected,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            buttons,
            text="Excluir selecionada",
            fg_color="#a82424",
            hover_color="#821c1c",
            command=self.ignore_selected,
        ).pack(side="left", padx=6)

        cleanup = ctk.CTkFrame(panel, fg_color="transparent")
        cleanup.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkButton(
            cleanup,
            text="Limpar vencidas e descontos baixos",
            fg_color="#b56a12",
            hover_color="#8f510b",
            command=self.clean_low_quality,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            cleanup, text="Excluir antigas (+7 dias)", command=self.clean_old
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            cleanup, text="Excluir vencidas", command=self.clean_expired
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            cleanup, text="Excluir descontos baixos", command=self.clean_low_discount
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            cleanup, text="Manter somente prioritárias", command=self.keep_priorities
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            cleanup,
            text="Limpar todas",
            fg_color="#a82424",
            hover_color="#821c1c",
            command=self.clean_all,
        ).pack(side="right", padx=(6, 0))

        self.details = ctk.CTkTextbox(panel)
        self.details.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def load_pending(self):
        self.all_pending = self.database.listar_pendencias_revisao(
            "pendente", 2000
        )
        self.apply_filter()

    def apply_filter(self):
        selected_filter = self.filter_menu.get()
        allowed = self.FILTER_TYPES.get(selected_filter)
        items = [
            item for item in self.all_pending
            if allowed is None or item[0]["tipo"] in allowed
        ]
        items.sort(key=self.priority_key)
        self.pending_by_label = {}
        for row, alert in items:
            title = str(alert.get("titulo") or "Produto sem titulo")
            label = (
                f"#{row['id']} | {self.TYPE_LABELS.get(row['tipo'], row['tipo'])} | "
                f"{title[:85]}"
            )
            self.pending_by_label[label] = (row, alert)
        labels = list(self.pending_by_label) or ["Nenhuma pendência"]
        self.menu.configure(values=labels)
        self.menu.set(labels[0])
        self.status.configure(
            text=(
                f"Exibindo: {len(self.pending_by_label)} | "
                f"Prioritárias: {self.priority_count()} | "
                f"Total para revisão: {len(self.all_pending)}"
            )
        )
        self.show_selected()

    def priority_count(self):
        priority_types = self.FILTER_TYPES["Prioritarias"]
        return sum(row["tipo"] in priority_types for row, _alert in self.all_pending)

    def priority_key(self, item):
        row, alert = item
        type_order = {
            "link_afiliado": 0,
            "categoria": 1,
            "imagem": 2,
            "desconto_insuficiente": 3,
            "oferta_vencida": 4,
            "loja_desabilitada": 5,
        }
        discount = self.notifier.discount_percent(alert)
        price = self.notifier.value(alert, "preco_valor", float("inf"))
        return (
            type_order.get(row["tipo"], 9),
            -discount,
            price if price and price > 0 else float("inf"),
            -int(row["id"]),
        )

    def selected(self):
        return self.pending_by_label.get(self.menu.get())

    def show_selected(self, _value=None):
        self.details.delete("1.0", "end")
        selected = self.selected()
        if not selected:
            self.details.insert(
                "end", "Nenhuma pendência. O monitor continua funcionando normalmente."
            )
            return
        row, alert = selected
        self.details.insert(
            "end",
            f"Motivo: {row['motivo']}\n"
            f"Tipo: {self.TYPE_LABELS.get(row['tipo'], row['tipo'])}\n"
            f"Tentativas: {row['tentativas']}\n"
            f"Loja: {alert.get('loja', '')}\n"
            f"Produto: {alert.get('titulo', '')}\n"
            f"Preço: {alert.get('preco', '')}\n"
            f"Link: {alert.get('link', '')}\n\n"
            "Use Corrigir link ou Corrigir categoria quando necessário. "
            "Depois clique em Reavaliar e enviar.",
        )

    def open_affiliate_links(self):
        selected = self.selected()
        if selected:
            link = str(selected[1].get("link") or "")
            if link.startswith("http"):
                webbrowser.open_new_tab(link)
        window = self.winfo_toplevel()
        if hasattr(window, "mostrar_links_afiliados"):
            window.mostrar_links_afiliados()

    def open_categories(self):
        window = self.winfo_toplevel()
        if hasattr(window, "mostrar_grupos"):
            window.mostrar_grupos()

    def retry_selected(self):
        selected = self.selected()
        if not selected:
            return
        row, alert = selected
        current = self.database.buscar_produto_por_link(alert.get("link", ""))
        product = current or alert
        quality_override = row["tipo"] in {
            "desconto_insuficiente", "oferta_vencida"
        }
        if quality_override and not messagebox.askyesno(
            "Confirmar exceção",
            f"{row['motivo']}\n\nDeseja enviar mesmo assim?",
        ):
            return
        result = (
            self.notifier.send_manual_alerts([product], self.database)
            if quality_override
            else self.notifier.send_alerts([product], self.database)
        )
        if result.startswith("Enviado por:"):
            self.database.atualizar_status_pendencia(row["id"], "resolvida")
            messagebox.showinfo("Pendência resolvida", result)
            self.load_pending()
        else:
            messagebox.showerror("Ainda pendente", result)

    def ignore_selected(self):
        selected = self.selected()
        if not selected:
            return
        row, _alert = selected
        if not messagebox.askyesno(
            "Excluir pendência", "Excluir este item da lista de revisão?\n\nO produto será preservado."
        ):
            return
        self.database.excluir_pendencias_revisao(pendencia_ids=[row["id"]])
        self.load_pending()

    def _confirm_cleanup(self, title, message, **filters):
        if not messagebox.askyesno(title, message):
            return
        try:
            total = self.database.excluir_pendencias_revisao(**filters)
        except Exception as error:
            messagebox.showerror("Falha na limpeza", str(error))
            return
        self.load_pending()
        messagebox.showinfo(
            "Limpeza concluída",
            f"{total} pendência(s) removida(s).\n\nProdutos e configurações foram preservados.",
        )

    def clean_low_quality(self):
        self._confirm_cleanup(
            "Limpeza recomendada",
            "Excluir ofertas vencidas e produtos com desconto insuficiente?\n\n"
            "Links afiliados, categorias e imagens pendentes serão preservados.",
            tipos=["oferta_vencida", "desconto_insuficiente"],
        )

    def clean_expired(self):
        self._confirm_cleanup(
            "Excluir ofertas vencidas",
            "Excluir todas as ofertas vencidas da lista de revisão?",
            tipos=["oferta_vencida"],
        )

    def clean_low_discount(self):
        self._confirm_cleanup(
            "Excluir descontos insuficientes",
            "Excluir todos os produtos com desconto insuficiente da lista?",
            tipos=["desconto_insuficiente"],
        )

    def clean_old(self):
        self._confirm_cleanup(
            "Excluir pendências antigas",
            "Excluir todas as pendências que não foram atualizadas nos últimos 7 dias?",
            antigas_dias=7,
        )

    def keep_priorities(self):
        self._confirm_cleanup(
            "Manter somente prioritárias",
            "Excluir tudo, exceto links afiliados, categorias e imagens pendentes?",
            manter_tipos=["link_afiliado", "categoria", "imagem"],
        )

    def clean_all(self):
        self._confirm_cleanup(
            "Limpar todas as pendências",
            "ATENÇÃO: excluir todas as pendências de revisão?\n\n"
            "Os produtos continuarão cadastrados, mas a lista ficará vazia.",
            tipos=list(self.TYPE_LABELS),
        )
