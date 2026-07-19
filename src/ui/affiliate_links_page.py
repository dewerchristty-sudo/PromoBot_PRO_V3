import tkinter as tk
import webbrowser
from tkinter import messagebox
from urllib.parse import urlparse

import customtkinter as ctk

from src.core.notifier import Notifier


class AffiliateLinksPage(ctk.CTkFrame):

    VALID_DOMAINS = {
        "mercado livre": {"meli.la"},
        "shopee": {
            "s.shopee.com.br",
            "shope.ee",
            "collshp.com",
        },
    }

    def __init__(self, master, database):
        super().__init__(master)

        self.database = database
        self.notifier = Notifier(database)
        self.pending_by_label = {}
        self.only_offers = tk.BooleanVar(value=True)
        self.tested_affiliate_link = ""

        self.create_interface()
        self.load_pending()

    def create_interface(self):

        ctk.CTkLabel(
            self,
            text="Links de Afiliado Pendentes",
            font=("Arial", 30, "bold"),
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            self,
            text=(
                "Shopee e Mercado Livre so serao notificados depois que "
                "o link oficial for salvo."
            ),
            font=("Arial", 14),
        ).pack(pady=(0, 18))

        self.status = ctk.CTkLabel(self, text="", anchor="w")
        self.status.pack(fill="x", padx=30, pady=(0, 8))

        ctk.CTkCheckBox(
            self,
            text="Mostrar somente ofertas",
            variable=self.only_offers,
            command=self.load_pending,
        ).pack(anchor="w", padx=30, pady=(0, 10))

        form = ctk.CTkFrame(self)
        form.pack(fill="both", expand=True, padx=30, pady=(0, 25))
        form.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(form, text="Produto pendente", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=18, pady=(18, 5)
        )

        self.product_menu = ctk.CTkOptionMenu(
            form,
            values=["Carregando..."],
            command=lambda _value: self.show_selected(),
        )
        self.product_menu.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))

        ctk.CTkLabel(form, text="Link original", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=18, pady=(0, 5)
        )

        original_row = ctk.CTkFrame(form, fg_color="transparent")
        original_row.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 12))
        original_row.grid_columnconfigure(0, weight=1)

        self.original_link = ctk.CTkEntry(original_row)
        self.original_link.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            original_row,
            text="Copiar link",
            width=120,
            command=self.copy_original,
        ).grid(row=0, column=1)

        ctk.CTkLabel(form, text="Link afiliado oficial", anchor="w").grid(
            row=4, column=0, sticky="ew", padx=18, pady=(0, 5)
        )

        affiliate_row = ctk.CTkFrame(form, fg_color="transparent")
        affiliate_row.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 16))
        affiliate_row.grid_columnconfigure(0, weight=1)

        self.affiliate_link = ctk.CTkEntry(
            affiliate_row,
            placeholder_text="Cole aqui o link meli.la ou o link oficial da Shopee...",
        )
        self.affiliate_link.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            affiliate_row,
            text="Testar link",
            width=120,
            command=self.test_affiliate_link,
        ).grid(row=0, column=1)

        ctk.CTkLabel(form, text="Etiqueta de acompanhamento", anchor="w").grid(
            row=6, column=0, sticky="ew", padx=18, pady=(0, 5)
        )

        self.tracking_label = ctk.CTkEntry(form)
        self.tracking_label.grid(row=7, column=0, sticky="ew", padx=18, pady=(0, 16))
        self.tracking_label.insert(0, "promobotwhatsapp")

        buttons = ctk.CTkFrame(form, fg_color="transparent")
        buttons.grid(row=8, column=0, sticky="ew", padx=18, pady=(0, 12))

        ctk.CTkButton(
            buttons,
            text="Salvar e validar",
            width=160,
            command=self.save_link,
        ).pack(side="left")

        ctk.CTkButton(
            buttons,
            text="Salvar e notificar agora",
            width=190,
            fg_color="#17813f",
            hover_color="#116530",
            command=self.save_and_notify,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            buttons,
            text="Atualizar lista",
            width=130,
            command=self.load_pending,
        ).pack(side="left", padx=8)

        ctk.CTkLabel(form, text="Ultimos envios", anchor="w").grid(
            row=9, column=0, sticky="ew", padx=18, pady=(0, 5)
        )

        self.history = ctk.CTkTextbox(form, height=150)
        self.history.grid(row=10, column=0, sticky="nsew", padx=18, pady=(0, 18))
        form.grid_rowconfigure(10, weight=1)

    def load_pending(self):

        products = self.database.listar_produtos_marketplace(
            somente_promocoes=self.only_offers.get()
        )
        eligible, stale, low_discount = self.notifier.partition_offer_quality(
            products
        )
        prioritized, without_image = self.notifier.prioritize_affiliate_queue(
            eligible
        )
        pending = [
            product
            for product in prioritized
            if not self.notifier.has_affiliate_link(product)
        ]

        self.pending_by_label = {
            f"#{product['id']} | {product['loja']} | {product['titulo'][:85]}": product
            for product in pending
        }
        labels = list(self.pending_by_label) or ["Nenhum produto pendente"]
        self.product_menu.configure(values=labels)
        self.product_menu.set(labels[0])

        configured = len(prioritized) - len(pending)
        self.status.configure(
            text=(
                f"Pendentes: {len(pending)} | Configurados: {configured} | "
                f"Vencidos: {len(stale)} | Desconto insuficiente: "
                f"{len(low_discount)} | Sem imagem: {len(without_image)} | "
                f"Vinculos salvos no banco: {self.database.total_links_afiliados()}"
            )
        )
        self.show_selected()
        self.load_history()

    def selected_product(self):

        return self.pending_by_label.get(self.product_menu.get())

    def show_selected(self):

        product = self.selected_product()
        self.original_link.delete(0, "end")

        if product:
            self.original_link.insert(0, product["link"])

        self.affiliate_link.delete(0, "end")
        self.tested_affiliate_link = ""

    def copy_original(self):

        product = self.selected_product()

        if not product:
            messagebox.showinfo("Links de afiliado", "Nao ha produto pendente.")
            return

        self.clipboard_clear()
        self.clipboard_append(product["link"])
        self.update()
        messagebox.showinfo("Links de afiliado", "Link original copiado.")

    def save_link(self):

        if self.save_selected_link():
            messagebox.showinfo(
                "Link afiliado",
                "Link validado e produto liberado para notificacoes.",
            )
            self.load_pending()

    def save_selected_link(self):

        product = self.selected_product()

        if not product:
            messagebox.showinfo("Links de afiliado", "Nao ha produto pendente.")
            return None

        affiliate_link = self.affiliate_link.get().strip()

        try:
            self.validate_link(product, affiliate_link)
            self.database.salvar_link_afiliado(
                product["loja"],
                product["link"],
                affiliate_link,
                self.tracking_label.get().strip(),
            )
        except ValueError as error:
            messagebox.showerror("Link invalido", str(error))
            return None

        return product

    def save_and_notify(self):

        product = self.save_selected_link()

        if not product:
            return

        image = str(product["imagem"] or "").strip()

        if not image.startswith("http"):
            messagebox.showerror(
                "Notificacao bloqueada",
                "Este produto nao possui uma imagem valida para o WhatsApp.",
            )
            self.load_pending()
            return

        if self.database.produto_ja_notificado(
            product["link"],
            product["loja"],
            product["titulo"],
        ):
            messagebox.showwarning(
                "Notificacao duplicada",
                "Este produto ja foi notificado e nao sera enviado novamente.",
            )
            self.load_pending()
            return

        result = self.notifier.send_alerts([product])

        if result.startswith("Enviado por:"):
            self.database.marcar_notificacao_manual(
                product["link"],
                product["loja"],
                product["titulo"],
            )
            messagebox.showinfo("Notificacao", result)
        else:
            messagebox.showerror("Falha na notificacao", result)

        self.load_pending()

    def load_history(self):

        self.history.delete("1.0", "end")
        deliveries = self.database.listar_historico_envios(20)

        if not deliveries:
            self.history.insert("end", "Nenhum envio registrado ainda.")
            return

        for delivery in deliveries:
            self.history.insert(
                "end",
                f"{delivery['data']} | {delivery['status'].upper()} | "
                f"{delivery['canal']} | {delivery['loja']}\n"
                f"Produto: {delivery['titulo']}\n"
                f"Etiqueta: {delivery['etiqueta'] or 'nao informada'}\n"
                f"Link: {delivery['link_afiliado']}\n"
                "------------------------------------------------------------\n",
            )

    def validate_link(self, product, affiliate_link):

        self.validate_link_format(product, affiliate_link)

        if affiliate_link != self.tested_affiliate_link:
            raise ValueError(
                "Teste o link e confirme que ele abriu o produto correto antes de salvar."
            )

    def validate_link_format(self, product, affiliate_link):

        if not affiliate_link.startswith("https://"):
            raise ValueError("O link afiliado precisa comecar com https://.")

        store = self.store_key(product)
        domain = (urlparse(affiliate_link).hostname or "").lower()
        valid_domains = self.VALID_DOMAINS.get(store, set())

        if domain not in valid_domains:
            expected = ", ".join(sorted(valid_domains))
            raise ValueError(f"Dominio invalido para {store}: use {expected}.")

        if affiliate_link == product["link"]:
            raise ValueError("O link afiliado nao pode ser igual ao link original.")

    def test_affiliate_link(self):

        product = self.selected_product()

        if not product:
            messagebox.showinfo("Links de afiliado", "Nao ha produto pendente.")
            return

        affiliate_link = self.affiliate_link.get().strip()

        try:
            self.validate_link_format(product, affiliate_link)
        except ValueError as error:
            messagebox.showerror("Link invalido", str(error))
            return

        webbrowser.open_new_tab(affiliate_link)
        confirmed = messagebox.askyesno(
            "Confirmar produto",
            "O link abriu o produto correto na loja?",
        )

        self.tested_affiliate_link = affiliate_link if confirmed else ""

        if confirmed:
            messagebox.showinfo(
                "Link confirmado",
                "Link testado. Agora voce pode salvar ou notificar.",
            )

    def store_key(self, product):

        store = str(product["loja"] or "").strip().lower()
        link = str(product["link"] or "").lower()

        if store == "shopee" or "shopee.com.br" in link:
            return "shopee"

        return "mercado livre"
