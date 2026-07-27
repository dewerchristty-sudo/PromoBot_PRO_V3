import threading
import webbrowser
from tkinter import messagebox
from urllib.parse import urlparse

import customtkinter as ctk

from src.core.notifier import Notifier
from src.scraper import Parser
from src.ui.affiliate_links_page import AffiliateLinksPage
from src.ui.search_page import SearchPage


class CategoryHubPage(ctk.CTkFrame):
    """Fluxo completo de pesquisa, revisao, afiliacao e envio por categoria."""

    CATEGORIES = {
        "Mamae e Bebe": "mamae_bebe",
        "Casa e Enxoval": "casa_enxoval",
        "Eletrodomesticos": "eletrodomesticos",
        "Smartphones e Tecnologia": "smartphones_tecnologia",
        "Beleza e Perfumaria": "beleza_perfumaria",
        "Limpeza e Utilidades": "limpeza_utilidades",
    }

    SEARCH_TERMS = {
        "mamae_bebe": "ofertas mamae bebe",
        "casa_enxoval": "ofertas casa enxoval",
        "eletrodomesticos": "ofertas eletrodomesticos",
        "smartphones_tecnologia": "ofertas smartphones tecnologia",
        "beleza_perfumaria": "ofertas beleza perfumaria",
        "limpeza_utilidades": "ofertas limpeza utilidades",
    }

    def __init__(self, master, database):
        super().__init__(master)
        self.database = database
        self.notifier = Notifier(database)
        self.category_label = next(iter(self.CATEGORIES))
        self.category = self.CATEGORIES[self.category_label]
        self.review_products_by_label = {}
        self.send_products_by_label = {}
        self.tested_affiliate_link = ""
        self.sending = False
        self.create_interface()
        self.load_products()

    def create_interface(self):
        ctk.CTkLabel(
            self,
            text="Central de Categorias",
            font=("Arial", 30, "bold"),
        ).pack(pady=(16, 5))
        ctk.CTkLabel(
            self,
            text=(
                "Pesquise, revise, valide o link afiliado e envie ao grupo "
                "sem sair da categoria."
            ),
            font=("Arial", 13),
        ).pack(pady=(0, 10))

        self.category_selector = ctk.CTkOptionMenu(
            self,
            values=list(self.CATEGORIES),
            command=self.change_category,
            height=38,
        )
        self.category_selector.pack(fill="x", padx=24, pady=(0, 10))
        self.category_selector.set(self.category_label)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        for name in ("Pesquisar", "Revisar e link", "Enviar"):
            self.tabs.add(name)

        self.search_page = SearchPage(
            self.tabs.tab("Pesquisar"),
            self.database,
            initial_query=self.SEARCH_TERMS[self.category],
            category=self.category,
            result_callback=self.search_completed,
        )
        self.search_page.pack(fill="both", expand=True)

        self.create_review_tab(self.tabs.tab("Revisar e link"))
        self.create_send_tab(self.tabs.tab("Enviar"))

    def create_review_tab(self, parent):
        toolbar = ctk.CTkFrame(parent)
        toolbar.pack(fill="x", padx=12, pady=(12, 6))
        self.review_product_menu = ctk.CTkOptionMenu(
            toolbar,
            values=["Nenhum produto"],
            command=lambda _value: self.show_product(),
        )
        self.review_product_menu.pack(
            side="left", fill="x", expand=True, padx=(8, 6), pady=8
        )
        ctk.CTkButton(
            toolbar,
            text="Atualizar produtos",
            width=140,
            command=self.load_products,
        ).pack(side="left", padx=(6, 8), pady=8)

        self.review_result = ctk.CTkTextbox(parent, height=165)
        self.review_result.pack(fill="x", padx=12, pady=6)

        link_frame = ctk.CTkFrame(parent)
        link_frame.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        link_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            link_frame, text="Link original do produto", anchor="w"
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        self.original_link = ctk.CTkEntry(link_frame)
        self.original_link.grid(row=1, column=0, sticky="ew", padx=12)
        ctk.CTkButton(
            link_frame,
            text="Copiar",
            width=100,
            command=self.copy_original,
        ).grid(row=1, column=1, padx=(0, 12))

        ctk.CTkLabel(
            link_frame, text="Link oficial de afiliado", anchor="w"
        ).grid(row=2, column=0, sticky="ew", padx=12, pady=(12, 4))
        self.affiliate_link = ctk.CTkEntry(
            link_frame,
            placeholder_text="Cole o link gerado no programa de afiliados...",
        )
        self.affiliate_link.grid(row=3, column=0, sticky="ew", padx=12)
        affiliate_actions = ctk.CTkFrame(link_frame, fg_color="transparent")
        affiliate_actions.grid(row=3, column=1, padx=(0, 12))
        ctk.CTkButton(
            affiliate_actions,
            text="Colar link",
            width=95,
            command=self.paste_affiliate_link,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            affiliate_actions,
            text="Testar link",
            width=100,
            command=self.test_link,
        ).pack(side="left")

        self.link_status = ctk.CTkLabel(link_frame, text="", anchor="w")
        self.link_status.grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 4)
        )
        ctk.CTkButton(
            link_frame,
            text="Salvar link validado",
            fg_color="#15803d",
            hover_color="#166534",
            command=self.save_link,
        ).grid(row=5, column=0, columnspan=2, pady=(4, 12))

    def create_send_tab(self, parent):
        toolbar = ctk.CTkFrame(parent)
        toolbar.pack(fill="x", padx=12, pady=(12, 6))
        self.send_product_menu = ctk.CTkOptionMenu(
            toolbar,
            values=["Nenhum produto"],
            command=lambda _value: self.show_preview(),
        )
        self.send_product_menu.pack(
            side="left", fill="x", expand=True, padx=(8, 6), pady=8
        )
        ctk.CTkButton(
            toolbar,
            text="Atualizar",
            width=110,
            command=self.load_products,
        ).pack(side="left", padx=(6, 8), pady=8)

        self.destination_status = ctk.CTkLabel(parent, text="", anchor="w")
        self.destination_status.pack(fill="x", padx=16, pady=(5, 3))
        self.preview = ctk.CTkTextbox(parent)
        self.preview.pack(fill="both", expand=True, padx=12, pady=6)

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(4, 12))
        ctk.CTkButton(
            actions,
            text="Validar oferta",
            command=self.validate_selected_for_send,
        ).pack(side="left", padx=(0, 8))
        self.send_button = ctk.CTkButton(
            actions,
            text="Enviar para o grupo da categoria",
            fg_color="#15803d",
            hover_color="#166534",
            command=self.send_selected,
        )
        self.send_button.pack(side="right")
        self.review_send_button = ctk.CTkButton(
            actions,
            text="Enviar para Revisão",
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            command=self.send_selected_to_review,
        )
        self.review_send_button.pack(side="right", padx=(0, 8))

    def change_category(self, label):
        self.category_label = label
        self.category = self.CATEGORIES[label]
        self.search_page.set_query(self.SEARCH_TERMS[self.category])
        self.search_page.set_category(self.category)
        self.tested_affiliate_link = ""
        self.load_products()

    def category_products(self):
        products = []
        for row in self.database.listar_produtos_marketplace():
            product = dict(row)
            detected = self.notifier.whatsapp_category(product)
            if detected == self.category:
                products.append(product)
        return products

    def search_completed(self, results):
        first_link = str(results[0].get("link") or "") if results else ""
        self.load_products(select_link=first_link)

    def load_products(self, select_link=""):
        products = self.category_products()
        self.review_products_by_label = {
            (
                f"{'[LINK OK]' if self.notifier.has_affiliate_link(product) else '[LINK PENDENTE]'} "
                f"#{product['id']} | {product['loja']} | "
                f"{Parser.format_brl(product['preco_valor'], True)} | "
                f"{product['titulo'][:75]}"
            ): product
            for product in products[:300]
        }
        self.send_products_by_label = {
            (
                f"[LINK OK] #{product['id']} | {product['loja']} | "
                f"{Parser.format_brl(product['preco_valor'], True)} | "
                f"{product['titulo'][:75]}"
            ): product
            for product in products[:300]
            if self.notifier.has_affiliate_link(product)
        }
        review_labels = list(self.review_products_by_label) or [
            "Nenhum produto encontrado nesta categoria"
        ]
        send_labels = list(self.send_products_by_label) or [
            "Nenhum produto com link afiliado validado"
        ]
        self.review_product_menu.configure(values=review_labels)
        selected_label = next(
            (
                label for label, product in self.review_products_by_label.items()
                if str(product.get("link") or "") == select_link
            ),
            review_labels[0],
        )
        self.review_product_menu.set(selected_label)
        self.send_product_menu.configure(values=send_labels)
        self.send_product_menu.set(send_labels[0])
        self.show_product()
        self.show_preview()

    def selected_product(self, menu):
        source = (
            self.send_products_by_label
            if menu is self.send_product_menu
            else self.review_products_by_label
        )
        product = source.get(menu.get())
        return dict(product) if product else None

    def product_checks(self, product):
        ready, stale, low = self.notifier.partition_offer_quality([product])
        recipients = self.notifier.whatsapp_recipients_for_alert(product)
        return [
            ("Categoria", self.category_label, True),
            ("Imagem", "valida" if str(product.get("imagem") or "").startswith("http")
             else "ausente", str(product.get("imagem") or "").startswith("http")),
            ("Oferta", "atual" if not stale else "vencida", not stale),
            ("Desconto", "aprovado" if not low else "abaixo do minimo", not low),
            ("Link afiliado", "validado" if self.notifier.has_affiliate_link(product)
             else "pendente", self.notifier.has_affiliate_link(product)),
            ("Grupo", recipients[0] if recipients else "nao configurado", bool(recipients)),
            (
                "Repeticao",
                "ja enviada" if self.database.produto_ja_notificado(
                    product["link"], product["loja"], product["titulo"]
                ) else "nova",
                not self.database.produto_ja_notificado(
                    product["link"], product["loja"], product["titulo"]
                ),
            ),
        ]

    def show_product(self):
        product = self.selected_product(self.review_product_menu)
        self.review_result.delete("1.0", "end")
        self.original_link.configure(state="normal")
        self.original_link.delete(0, "end")
        self.affiliate_link.configure(state="normal")
        self.affiliate_link.delete(0, "end")
        self.tested_affiliate_link = ""
        if not product:
            self.review_result.insert(
                "end",
                "Pesquise produtos nesta categoria e clique em Atualizar produtos.",
            )
            self.original_link.configure(state="disabled")
            return
        self.review_result.insert(
            "end",
            f"{product['titulo']}\n{product['loja']} | "
            f"{Parser.format_brl(product['preco_valor'], True)}\n\n",
        )
        for label, value, ok in self.product_checks(product):
            self.review_result.insert(
                "end", f"{'OK' if ok else 'ATENCAO'} | {label}: {value}\n"
            )
        self.original_link.insert(0, str(product.get("link") or ""))
        # O link original pertence ao anúncio selecionado. Mantê-lo bloqueado
        # evita misturar, por exemplo, um produto Shopee com um link Amazon.
        self.original_link.configure(state="disabled")
        saved = self.database.buscar_link_afiliado(product["link"])
        if saved:
            self.affiliate_link.insert(0, saved)
            self.link_status.configure(text="Este produto ja possui link afiliado salvo.")
        else:
            self.link_status.configure(text="Link afiliado pendente.")

    def copy_original(self):
        link = self.original_link.get().strip()
        if not link:
            return
        self.clipboard_clear()
        self.clipboard_append(link)
        self.update()
        messagebox.showinfo("Central de Categorias", "Link original copiado.")

    def paste_affiliate_link(self):
        try:
            link = self.clipboard_get().strip()
        except Exception:
            messagebox.showwarning(
                "Central de Categorias",
                "Nao encontrei um link copiado. Copie o link afiliado e tente novamente.",
            )
            return
        self.affiliate_link.configure(state="normal")
        self.affiliate_link.delete(0, "end")
        self.affiliate_link.insert(0, link)
        self.affiliate_link.focus_set()
        self.tested_affiliate_link = ""
        self.link_status.configure(
            text="Link colado. Clique em Testar link para confirmar."
        )

    @staticmethod
    def store_key(product):
        store = str(product.get("loja") or "").strip().lower()
        if store in AffiliateLinksPage.VALID_DOMAINS:
            return store
        return AffiliateLinksPage.identify_store_by_link(product.get("link", ""))

    def validate_link_format(self, product, affiliate_link):
        if not affiliate_link.startswith("https://"):
            raise ValueError("O link afiliado precisa comecar com https://.")
        if affiliate_link.lower().count("https://") != 1:
            raise ValueError("Cole somente um link afiliado por vez.")
        store = self.store_key(product)
        if not store:
            raise ValueError("A loja do produto nao foi identificada.")
        domain = (urlparse(affiliate_link).hostname or "").lower()
        valid = AffiliateLinksPage.VALID_DOMAINS.get(store, set())
        if (
            domain not in valid
            and AffiliateLinksPage.identify_store_by_link(affiliate_link) != store
        ):
            affiliate_store = AffiliateLinksPage.identify_store_by_link(
                affiliate_link
            )
            if affiliate_store:
                raise ValueError(
                    f"O produto selecionado e da loja "
                    f"{AffiliateLinksPage.store_display_name(store)}, mas o "
                    f"link colado e da "
                    f"{AffiliateLinksPage.store_display_name(affiliate_store)}. "
                    "Selecione na lista azul o anuncio da mesma loja e do "
                    "mesmo produto."
                )
            raise ValueError(
                f"Dominio invalido para {store}. Use: {', '.join(sorted(valid))}."
            )
        if affiliate_link.rstrip("/") == str(product["link"]).rstrip("/"):
            raise ValueError("O link afiliado nao pode ser igual ao link original.")

    def test_link(self):
        product = self.selected_product(self.review_product_menu)
        if not product:
            messagebox.showwarning("Central de Categorias", "Selecione um produto.")
            return
        link = self.affiliate_link.get().strip()
        try:
            self.validate_link_format(product, link)
        except ValueError as error:
            messagebox.showerror("Link invalido", str(error))
            return
        webbrowser.open_new_tab(link)
        confirmed = messagebox.askyesno(
            "Confirmar link",
            "O link abriu exatamente o produto selecionado?",
        )
        self.tested_affiliate_link = link if confirmed else ""
        self.link_status.configure(
            text="Link testado e confirmado." if confirmed else "Teste nao confirmado."
        )

    def save_link(self):
        product = self.selected_product(self.review_product_menu)
        if not product:
            return
        link = self.affiliate_link.get().strip()
        try:
            self.validate_link_format(product, link)
            if link != self.tested_affiliate_link:
                raise ValueError("Teste e confirme o link antes de salvar.")
            self.database.salvar_link_afiliado(
                product["loja"],
                product["link"],
                link,
                self.category,
            )
        except ValueError as error:
            messagebox.showerror("Link invalido", str(error))
            return
        self.link_status.configure(text="Link afiliado salvo e validado.")
        messagebox.showinfo(
            "Central de Categorias",
            "Link salvo. O produto esta liberado para a etapa de envio.",
        )
        self.load_products()

    def show_preview(self):
        product = self.selected_product(self.send_product_menu)
        self.preview.delete("1.0", "end")
        if not product:
            self.destination_status.configure(
                text=f"{self.category_label}: nenhum produto disponivel."
            )
            return
        recipients = self.notifier.whatsapp_recipients_for_alert(product)
        destination = recipients[0] if recipients else "grupo nao configurado"
        self.destination_status.configure(
            text=f"Destino: {self.category_label} | {destination}"
        )
        self.preview.insert("end", self.notifier.format_alert(product))

    def validate_selected_for_send(self, confirm_override=False):
        product = self.selected_product(self.send_product_menu)
        if not product:
            messagebox.showwarning("Validar oferta", "Selecione um produto.")
            return False
        checks = self.product_checks(product)
        hard_labels = {"Categoria", "Imagem", "Link afiliado", "Grupo", "Repeticao"}
        hard_failed = [
            f"{label}: {value}"
            for label, value, ok in checks
            if not ok and label in hard_labels
        ]
        overridable = [
            f"{label}: {value}"
            for label, value, ok in checks
            if not ok and label not in hard_labels
        ]
        if hard_failed:
            messagebox.showwarning(
                "Oferta bloqueada",
                "Corrija estes itens antes de enviar:\n\n"
                + "\n".join(hard_failed)
                + (
                    "\n\nAvisos adicionais:\n" + "\n".join(overridable)
                    if overridable
                    else ""
                ),
            )
            return False
        if overridable:
            warning = (
                "A oferta nao passou nos filtros automaticos:\n\n"
                + "\n".join(overridable)
                + "\n\nO link, a imagem e o grupo estao validados."
            )
            if not confirm_override:
                messagebox.showwarning(
                    "Envio manual disponivel",
                    warning
                    + "\n\nUse o botao de envio para confirmar a publicacao manual.",
                )
                return True
            return messagebox.askyesno(
                "Confirmar envio manual",
                warning + "\n\nDeseja publicar mesmo assim?",
            )
        messagebox.showinfo("Validar oferta", "Oferta aprovada para envio.")
        return True

    def send_selected(self):
        if self.sending:
            return
        product = self.selected_product(self.send_product_menu)
        if not product or not self.validate_selected_for_send(
            confirm_override=True
        ):
            return
        if not messagebox.askyesno(
            "Confirmar envio",
            f"Enviar esta oferta para o grupo {self.category_label}?",
        ):
            return
        self.sending = True
        self.send_button.configure(state="disabled", text="Enviando...")
        threading.Thread(
            target=self._send_worker,
            args=(product,),
            daemon=True,
        ).start()

    def _send_worker(self, product):
        try:
            sent = self.notifier.send_whatsapp_alerts([product])
            if sent:
                self.notifier.record_deliveries(
                    self.database,
                    [product],
                    ["WhatsApp"],
                )
                result = "Oferta enviada com sucesso pelo WhatsApp."
            else:
                result = "O envio foi bloqueado. Verifique a conexao e o grupo."
        except Exception as error:
            result = f"Falha no envio: {error}"
        self.after(0, lambda: self._finish_send(product, result))

    def send_selected_to_review(self):
        if self.sending:
            return
        product = self.selected_product(self.send_product_menu)
        if not product:
            messagebox.showwarning("Enviar para Revisão", "Selecione um produto.")
            return
        if not messagebox.askyesno(
            "Confirmar envio",
            "Enviar esta oferta somente para o grupo Revisão PromoBot?",
        ):
            return
        self.sending = True
        self.send_button.configure(state="disabled")
        self.review_send_button.configure(state="disabled", text="Enviando...")
        threading.Thread(
            target=self._review_send_worker,
            args=(product,),
            daemon=True,
        ).start()

    def _review_send_worker(self, product):
        result = self.notifier.send_review_alert(product)
        self.after(0, lambda: self._finish_review_send(result))

    def _finish_review_send(self, result):
        self.sending = False
        self.send_button.configure(state="normal")
        self.review_send_button.configure(
            state="normal", text="Enviar para Revisão"
        )
        if result.startswith("Oferta enviada"):
            messagebox.showinfo("Envio concluído", result)
        else:
            messagebox.showerror("Falha no envio", result)

    def _finish_send(self, product, result):
        self.sending = False
        self.send_button.configure(
            state="normal", text="Enviar para o grupo da categoria"
        )
        self.review_send_button.configure(state="normal")
        if result.startswith("Oferta enviada"):
            self.database.marcar_notificacao_manual(
                product["link"], product["loja"], product["titulo"]
            )
            messagebox.showinfo("Envio concluido", result)
            self.load_products()
        else:
            messagebox.showerror("Falha no envio", result)
