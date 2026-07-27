import tkinter as tk
import threading
import webbrowser
import logging
import os
from pathlib import Path
import sys
from tkinter import messagebox
from urllib.parse import urlparse

import customtkinter as ctk

from src.core.notifier import Notifier
from src.scraper import Parser
from src.stores.amazon import Amazon
from src.stores.mercado_livre import MercadoLivre
from src.stores.shopee import Shopee


class AffiliateLinksPage(ctk.CTkFrame):

    MANUAL_DESTINATIONS = {
        "review": ("Revisão PromoBot", "WHATSAPP_REVIEW_GROUP"),
        "house": ("Casa & Ofertas", "WHATSAPP_GROUP_CASA_ENXOVAL"),
    }
    DESTINATION_SELECTED_COLOR = "#17813f"
    DESTINATION_DEFAULT_COLOR = "#1f6aa5"

    MANUAL_CATEGORIES = {
        "Selecione a categoria": "",
        "Mamae e Bebe": "mamae_bebe",
        "Casa e Enxoval": "casa_enxoval",
        "Eletrodomesticos": "eletrodomesticos",
        "Smartphones e Tecnologia": "smartphones_tecnologia",
        "Beleza e Perfumaria": "beleza_perfumaria",
        "Limpeza e Utilidades": "limpeza_utilidades",
    }

    VALID_DOMAINS = {
        "mercado livre": {"meli.la"},
        "shopee": {
            "s.shopee.com.br",
            "shope.ee",
            "collshp.com",
        },
        "amazon": {
            "amzn.to",
            "link.amazon",
            "amazon.com.br",
            "www.amazon.com.br",
        },
    }

    def __init__(
        self,
        master,
        database,
        initial_mode="Oferta pendente",
        manual_only=False,
    ):
        super().__init__(master)

        self.database = database
        self.notifier = Notifier(database)
        self.pending_by_label = {}
        self.only_offers = tk.BooleanVar(value=True)
        self.tested_affiliate_link = ""
        self.selected_destination = tk.StringVar(value="")
        self.manual_only = bool(manual_only)
        self.load_generation = 0
        self.loading_pending = False
        self.entry_mode = (
            "Cadastro manual"
            if self.manual_only or initial_mode == "Cadastro manual"
            else "Oferta pendente"
        )

        self.create_interface()
        self.load_pending()
        if self.entry_mode == "Cadastro manual":
            self.change_entry_mode("Cadastro manual")
        if self.manual_only:
            self.status.configure(
                text=(
                    "Cole o link original do produto e o link oficial de afiliado. "
                    "O produto sera importado antes do envio."
                )
            )

    def create_interface(self):

        ctk.CTkLabel(
            self,
            text=("Produto Manual" if self.manual_only else "Links de Afiliado Pendentes"),
            font=("Arial", 30, "bold"),
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            self,
            text=(
                "Cadastre produtos que nao foram encontrados pela coleta automatica."
                if self.manual_only
                else "Amazon, Shopee e Mercado Livre so serao notificados depois "
                "que o link oficial for salvo."
            ),
            font=("Arial", 14),
        ).pack(pady=(0, 18))

        self.status = ctk.CTkLabel(self, text="", anchor="w")
        self.status.pack(fill="x", padx=30, pady=(0, 8))

        self.mode_selector = ctk.CTkSegmentedButton(
            self,
            values=["Oferta pendente", "Cadastro manual"],
            command=self.change_entry_mode,
        )
        if not self.manual_only:
            self.mode_selector.pack(anchor="w", padx=30, pady=(0, 10))
        self.mode_selector.set(self.entry_mode)

        self.only_offers_checkbox = ctk.CTkCheckBox(
            self,
            text="Mostrar somente ofertas",
            variable=self.only_offers,
            command=self.load_pending,
        )
        if not self.manual_only:
            self.only_offers_checkbox.pack(anchor="w", padx=30, pady=(0, 10))

        form = ctk.CTkFrame(self)
        form.pack(fill="both", expand=True, padx=30, pady=(0, 25))
        form.grid_columnconfigure(0, weight=1)

        self.product_label = ctk.CTkLabel(
            form, text="Produto pendente", anchor="w"
        )
        self.product_label.grid(
            row=0, column=0, sticky="ew", padx=18, pady=(18, 5)
        )

        self.product_menu = ctk.CTkOptionMenu(
            form,
            values=["Carregando..."],
            command=lambda _value: self.show_selected(),
        )
        self.product_menu.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        if self.manual_only:
            self.product_label.grid_remove()
            self.product_menu.grid_remove()

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
            placeholder_text="Cole aqui o link oficial de afiliado da loja...",
        )
        self.affiliate_link.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            affiliate_row,
            text="Testar link",
            width=120,
            command=self.test_affiliate_link,
        ).grid(row=0, column=1)

        self.manual_details = ctk.CTkFrame(form, fg_color="transparent")
        if self.manual_only:
            self.manual_details.grid(row=6, column=0, sticky="ew", padx=18, pady=(0, 14))
        self.manual_details.grid_columnconfigure(0, weight=1)
        self.manual_details.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.manual_details, text="Nome do produto", anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5)
        )
        self.manual_title = ctk.CTkEntry(
            self.manual_details,
            placeholder_text="Preencha somente se a importacao automatica falhar",
        )
        self.manual_title.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        ctk.CTkLabel(self.manual_details, text="Preco", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=(0, 6), pady=(0, 5)
        )
        ctk.CTkLabel(self.manual_details, text="Categoria", anchor="w").grid(
            row=2, column=1, sticky="ew", padx=(6, 0), pady=(0, 5)
        )
        self.manual_price = ctk.CTkEntry(
            self.manual_details, placeholder_text="Ex.: 149,90"
        )
        self.manual_price.grid(row=3, column=0, sticky="ew", padx=(0, 6), pady=(0, 10))
        self.manual_category = ctk.CTkOptionMenu(
            self.manual_details,
            values=list(self.MANUAL_CATEGORIES),
        )
        self.manual_category.grid(row=3, column=1, sticky="ew", padx=(6, 0), pady=(0, 10))
        self.manual_category.set("Selecione a categoria")

        ctk.CTkLabel(self.manual_details, text="Link da imagem do produto", anchor="w").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(0, 5)
        )
        self.manual_image = ctk.CTkEntry(
            self.manual_details,
            placeholder_text="Clique com o botao direito na imagem e copie o endereco",
        )
        self.manual_image.grid(row=5, column=0, columnspan=2, sticky="ew")

        ctk.CTkLabel(form, text="Etiqueta de acompanhamento", anchor="w").grid(
            row=7, column=0, sticky="ew", padx=18, pady=(0, 5)
        )

        self.tracking_label = ctk.CTkEntry(form)
        self.tracking_label.grid(row=8, column=0, sticky="ew", padx=18, pady=(0, 16))
        self.tracking_label.insert(0, "promobotwhatsapp")

        destination_row = ctk.CTkFrame(form, fg_color="transparent")
        destination_row.grid(
            row=9, column=0, sticky="w", padx=18, pady=(0, 10)
        )
        self.review_destination_button = ctk.CTkButton(
            destination_row,
            text="Revisão PromoBot",
            width=180,
            command=lambda: self.select_manual_destination("review"),
        )
        self.review_destination_button.pack(side="left", padx=(0, 8))
        self.house_destination_button = ctk.CTkButton(
            destination_row,
            text="Casa & Ofertas",
            width=180,
            command=lambda: self.select_manual_destination("house"),
        )
        self.house_destination_button.pack(side="left")

        buttons = ctk.CTkFrame(form, fg_color="transparent")
        buttons.grid(row=10, column=0, sticky="ew", padx=18, pady=(0, 12))

        self.save_button = ctk.CTkButton(
            buttons,
            text="Salvar e validar",
            width=160,
            command=self.save_link,
        )
        self.save_button.pack(side="left")

        self.notify_button = ctk.CTkButton(
            buttons,
            text="Salvar e notificar agora",
            width=190,
            fg_color="#17813f",
            hover_color="#116530",
            command=self.save_and_notify,
        )
        self.notify_button.pack(side="left", padx=(8, 0))

        self.refresh_button = ctk.CTkButton(
            buttons,
            text="Atualizar lista",
            width=130,
            command=self.load_pending,
        )
        if not self.manual_only:
            self.refresh_button.pack(side="left", padx=8)

        self.ignore_button = ctk.CTkButton(
            buttons,
            text="Ignorar oferta",
            width=140,
            fg_color="#a82424",
            hover_color="#821c1c",
            command=self.ignore_selected,
        )
        self.ignore_button.pack(side="left")
        if self.manual_only:
            self.ignore_button.pack_forget()

        ctk.CTkLabel(form, text="Ultimos envios", anchor="w").grid(
            row=11, column=0, sticky="ew", padx=18, pady=(0, 5)
        )

        self.history = ctk.CTkTextbox(form, height=150)
        self.history.grid(row=12, column=0, sticky="nsew", padx=18, pady=(0, 18))
        form.grid_rowconfigure(12, weight=1)

    def select_manual_destination(self, destination):

        if destination not in self.MANUAL_DESTINATIONS:
            raise ValueError("Destino manual inválido.")
        self.selected_destination.set(destination)
        self.update_destination_buttons()

    def clear_manual_destination(self):

        self.selected_destination.set("")
        self.update_destination_buttons()

    def update_destination_buttons(self):

        selected = self.selected_destination.get()
        for key, button in (
            ("review", self.review_destination_button),
            ("house", self.house_destination_button),
        ):
            active = key == selected
            button.configure(
                fg_color=(
                    self.DESTINATION_SELECTED_COLOR
                    if active else self.DESTINATION_DEFAULT_COLOR
                ),
                border_width=2 if active else 0,
                border_color="#ffffff" if active else self.DESTINATION_DEFAULT_COLOR,
            )

    def selected_destination_config(self):

        selected = self.selected_destination.get()
        if selected not in self.MANUAL_DESTINATIONS:
            return "", "", ""
        label, env_name = self.MANUAL_DESTINATIONS[selected]
        return selected, label, os.getenv(env_name, "").strip()

    def manual_product_data(self, link):

        if not self.manual_only:
            return None

        title = self.manual_title.get().strip()
        price = self.manual_price.get().strip()
        image = self.manual_image.get().strip()
        category = self.MANUAL_CATEGORIES.get(self.manual_category.get(), "")

        if not any((title, price, image, category)):
            return None

        missing = []
        if not title:
            missing.append("nome")
        if Parser.price_to_float(price) <= 0:
            missing.append("preco")
        if not image.startswith(("http://", "https://")):
            missing.append("link da imagem")
        if not category:
            missing.append("categoria")
        if missing:
            raise ValueError("Complete os dados manuais: " + ", ".join(missing) + ".")

        return {
            "loja": "Amazon",
            "titulo": title,
            "preco": price,
            "link": link,
            "imagem": image,
            "categoria_manual": category,
        }

    def load_pending(self):

        if self.manual_only:
            return
        self.load_generation += 1
        generation = self.load_generation
        only_offers = bool(self.only_offers.get())
        self.loading_pending = True
        self.only_offers_checkbox.configure(state="disabled")
        self.product_menu.configure(state="disabled")
        self.status.configure(text="Carregando produtos, aguarde...")
        threading.Thread(
            target=self._load_pending_worker,
            args=(generation, only_offers),
            daemon=True,
        ).start()

    def _load_pending_worker(self, generation, only_offers):

        try:
            products = self.database.listar_produtos_marketplace(
                somente_promocoes=only_offers
            )

            if only_offers:
                eligible, stale, low_discount = self.notifier.partition_offer_quality(
                    products
                )
            else:
                eligible = list(products)
                stale = []
                low_discount = []

            prioritized, without_image = self.notifier.prioritize_affiliate_queue(
                eligible
            )
            ignored_links = self.database.listar_links_ofertas_ignoradas()
            pending = [
                product
                for product in prioritized
                if (
                    not self.notifier.has_affiliate_link(product)
                    and str(product["link"] or "").strip() not in ignored_links
                )
            ]
            configured = sum(
                1 for product in prioritized
                if self.notifier.has_affiliate_link(product)
            )
            result = {
                "pending": pending,
                "configured": configured,
                "stale": len(stale),
                "low_discount": len(low_discount),
                "without_image": len(without_image),
                "saved": self.database.total_links_afiliados(),
                "ignored": len(ignored_links),
            }
            self.after(0, lambda: self._finish_pending_load(generation, result))
        except Exception as error:
            try:
                self.after(0, lambda err=error: self._pending_load_error(generation, err))
            except RuntimeError:
                pass

    def _finish_pending_load(self, generation, result):

        if generation != self.load_generation or not self.winfo_exists():
            return
        pending = result["pending"]
        self.pending_by_label = {
            f"#{product['id']} | {product['loja']} | {product['titulo'][:85]}": product
            for product in pending
        }
        labels = list(self.pending_by_label) or ["Nenhum produto pendente"]
        self.product_menu.configure(values=labels)
        self.product_menu.set(labels[0])
        self.status.configure(
            text=(
                f"Pendentes: {len(pending)} | Configurados: {result['configured']} | "
                f"Vencidos: {result['stale']} | Desconto insuficiente: "
                f"{result['low_discount']} | Sem imagem: {result['without_image']} | "
                f"Vinculos salvos no banco: {result['saved']} | "
                f"Ignorados: {result['ignored']}"
            )
        )
        self.loading_pending = False
        self.only_offers_checkbox.configure(state="normal")
        self.product_menu.configure(
            state="disabled" if self.entry_mode == "Cadastro manual" else "normal"
        )
        self.show_selected()
        self.load_history()

    def _pending_load_error(self, generation, error):

        if generation != self.load_generation or not self.winfo_exists():
            return
        self.loading_pending = False
        self.only_offers_checkbox.configure(state="normal")
        self.product_menu.configure(state="normal")
        self.status.configure(text=f"Falha ao carregar produtos: {error}")

    def load_pending_sync_deprecated(self):

        products = self.database.listar_produtos_marketplace(
            somente_promocoes=self.only_offers.get()
        )

        if self.only_offers.get():
            eligible, stale, low_discount = self.notifier.partition_offer_quality(
                products
            )
        else:
            eligible = list(products)
            stale = []
            low_discount = []

        prioritized, without_image = self.notifier.prioritize_affiliate_queue(
            eligible
        )
        pending = [
            product
            for product in prioritized
            if (
                not self.notifier.has_affiliate_link(product)
                and not self.database.oferta_ignorada(product["link"])
            )
        ]

        self.pending_by_label = {
            f"#{product['id']} | {product['loja']} | {product['titulo'][:85]}": product
            for product in pending
        }
        labels = list(self.pending_by_label) or ["Nenhum produto pendente"]
        self.product_menu.configure(values=labels)
        self.product_menu.set(labels[0])

        configured = sum(
            1 for product in prioritized
            if self.notifier.has_affiliate_link(product)
        )
        self.status.configure(
            text=(
                f"Pendentes: {len(pending)} | Configurados: {configured} | "
                f"Vencidos: {len(stale)} | Desconto insuficiente: "
                f"{len(low_discount)} | Sem imagem: {len(without_image)} | "
                f"Vinculos salvos no banco: {self.database.total_links_afiliados()} | "
                f"Ignorados: {self.database.total_ofertas_ignoradas()}"
            )
        )
        self.show_selected()
        self.load_history()

    def selected_product(self):

        if self.entry_mode == "Cadastro manual":
            original_link = self.normalize_manual_product_link(
                self.original_link.get().strip()
            )
            store = self.identify_store_by_link(original_link)
            return {
                "loja": self.store_display_name(store),
                "link": original_link,
                "titulo": "Cadastro manual",
            }

        return self.pending_by_label.get(self.product_menu.get())

    def normalize_manual_product_link(self, link):

        clean_link = Parser.remove_tracking(str(link or "").strip()).rstrip("/")
        store = self.identify_store_by_link(clean_link)

        if not store:
            return clean_link

        reference = self.database.referencia_produto_link(clean_link)
        if not reference:
            if store == "shopee":
                return clean_link
            raise ValueError(
                "O link original precisa abrir diretamente a pagina do produto. "
                "Nao use pagina do carrinho, linkId ou trecho de endereço."
            )

        if store == "amazon":
            return f"https://www.amazon.com.br/dp/{reference}"

        return clean_link

    def change_entry_mode(self, mode):

        self.entry_mode = mode
        manual = mode == "Cadastro manual"
        self.product_menu.configure(state="disabled" if manual else "normal")
        self.product_label.configure(
            text=(
                "Cadastro direto (a loja sera identificada pelo link original)"
                if manual
                else "Produto pendente"
            )
        )
        self.save_button.configure(
            text="Salvar vinculo manual" if manual else "Salvar e validar"
        )
        self.notify_button.configure(state="normal")
        self.ignore_button.configure(state="disabled" if manual else "normal")
        self.show_selected()

    def show_selected(self):

        self.original_link.delete(0, "end")

        product = self.selected_product() if self.entry_mode != "Cadastro manual" else None
        if product:
            self.original_link.insert(0, product["link"])

        self.affiliate_link.delete(0, "end")
        self.tested_affiliate_link = ""

    def copy_original(self):

        original_link = self.original_link.get().strip()

        if not original_link:
            messagebox.showinfo("Links de afiliado", "Nao ha link original para copiar.")
            return

        self.clipboard_clear()
        self.clipboard_append(original_link)
        self.update()
        messagebox.showinfo("Links de afiliado", "Link original copiado.")

    def ignore_selected(self):

        product = self.selected_product()

        if not product:
            messagebox.showinfo("Links de afiliado", "Nao ha produto pendente.")
            return

        confirmed = messagebox.askyesno(
            "Ignorar oferta",
            "Deseja retirar esta oferta da fila de links pendentes?\n\n"
            "Ela nao sera publicada pelo fluxo de afiliados.",
        )

        if not confirmed:
            return

        try:
            self.database.ignorar_oferta(dict(product))
        except ValueError as error:
            messagebox.showerror("Ignorar oferta", str(error))
            return

        messagebox.showinfo("Ignorar oferta", "Oferta retirada da fila.")
        self.load_pending()

    def save_link(self):

        if self.save_selected_link():
            manual = self.entry_mode == "Cadastro manual"
            messagebox.showinfo(
                "Link afiliado",
                (
                    "Vinculo manual salvo. Ele sera usado quando este link de produto "
                    "aparecer nas ofertas."
                    if manual
                    else "Link validado e produto liberado para notificacoes."
                ),
            )
            if manual:
                self.show_selected()
                self.load_history()
            else:
                self.load_pending()

    def save_selected_link(self):

        try:
            product = self.selected_product()
        except ValueError as error:
            messagebox.showerror("Link original invalido", str(error))
            return None

        if not product or not product["link"]:
            messagebox.showinfo(
                "Links de afiliado",
                "Informe o link original do produto.",
            )
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

    @staticmethod
    def runtime_flow_logger():

        runtime_root = (
            Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]
        )
        log_path = runtime_root / "logs" / "runtime_send_flow.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        flow_logger = logging.getLogger("promobot.runtime_send_flow")
        flow_logger.setLevel(logging.INFO)
        flow_logger.propagate = False
        if not any(
            isinstance(handler, logging.FileHandler)
            and Path(handler.baseFilename).resolve() == log_path.resolve()
            for handler in flow_logger.handlers
        ):
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s"
            ))
            flow_logger.addHandler(handler)
        return flow_logger

    def trace_send_stage(
        self, stage, product=None, reason="", product_found=None,
        category_status="", discount_status="", whatsapp_status="",
    ):

        product = dict(product) if product is not None else {}
        url = str(product.get("link", "") or "")
        try:
            product_id = self.database.referencia_produto_link(url)
        except Exception:
            product_id = ""
        self.runtime_flow_logger().info(
            "function=save_and_notify stage=%s reason=%s store=%s "
            "product_id=%s url=%s product_found=%s category_status=%s "
            "discount_status=%s whatsapp_status=%s",
            stage,
            reason or "NONE",
            str(product.get("loja", "") or "NOT_AVAILABLE"),
            product_id or "NOT_AVAILABLE",
            url or "NOT_AVAILABLE",
            product_found if product_found is not None else "UNKNOWN",
            category_status or "NOT_CHECKED",
            discount_status or "NOT_CHECKED",
            whatsapp_status or "NOT_CHECKED",
        )

    def save_and_notify(self):

        self.trace_send_stage("START")
        try:
            result = self._save_and_notify_impl()
        except Exception as error:
            self.trace_send_stage(
                "UNHANDLED_EXCEPTION",
                getattr(self, "_runtime_product", None),
                reason=f"{type(error).__name__}: {error}",
                whatsapp_status="FAILED",
            )
            self.runtime_flow_logger().exception(
                "save_and_notify unhandled exception"
            )
            messagebox.showerror(
                "Falha ao salvar e notificar",
                "O fluxo foi interrompido por um erro interno:\n\n"
                f"{type(error).__name__}: {error}\n\n"
                "Consulte logs/runtime_send_flow.log.",
            )
            return None
        self.trace_send_stage(
            "END",
            getattr(self, "_runtime_product", None),
            reason="COMPLETED",
        )
        return result

    def _save_and_notify_impl(self):

        destination_key, destination_label, destination = (
            self.selected_destination_config()
        )
        if not destination_key:
            messagebox.showwarning(
                "Selecione o destino",
                "Selecione Revisão PromoBot ou Casa & Ofertas antes de enviar.",
            )
            return
        if not destination:
            messagebox.showerror(
                "Destino não configurado",
                f"O destino {destination_label} não está configurado no sistema.",
            )
            return

        self.trace_send_stage("BEFORE_SAVE_AFFILIATE_LINK")
        product = self.save_selected_link()
        self._runtime_product = product
        self.trace_send_stage(
            "AFTER_SAVE_AFFILIATE_LINK",
            product,
            reason="SAVED" if product else "NOT_SAVED",
        )

        if not product:
            self.trace_send_stage(
                "EARLY_RETURN", reason="AFFILIATE_LINK_OR_PRODUCT_MISSING"
            )
            messagebox.showerror(
                "Não foi possível continuar",
                "O vínculo ou o produto não foi confirmado. Verifique os "
                "campos e tente novamente.",
            )
            return

        store = self.store_key(product)
        product_id = self.database.referencia_produto_link(
            product.get("link", "")
        )
        self.trace_send_stage(
            "STORE_AND_PRODUCT_ID_IDENTIFIED",
            product,
            reason=f"store={store};product_id={product_id or 'missing'}",
        )
        if store == "mercado livre":
            self.trace_send_stage(
                "BEFORE_PRODUCT_LOOKUP_AND_CREATE", product
            )
            try:
                recovered = self.ensure_mercado_livre_product_record(product)
            except (ValueError, RuntimeError) as error:
                logging.getLogger(__name__).error(
                    "mercado livre product recovery: "
                    "function=save_and_notify identifier=%s url=%s "
                    "database_lookup_attempted=True "
                    "automatic_creation_attempted=True return_reason=%s",
                    self.database.referencia_produto_link(
                        product.get("link", "")
                    ) or "NOT_AVAILABLE",
                    product.get("link", ""),
                    error,
                )
                messagebox.showerror(
                    "Produto nao encontrado",
                    "Nao foi possivel recuperar ou criar automaticamente "
                    f"este produto do Mercado Livre.\n\n{error}",
                )
                return
            if recovered:
                product = dict(recovered)
                self._runtime_product = product
            self.trace_send_stage(
                "AFTER_PRODUCT_RECOVERY",
                product,
                reason="RECOVERED" if recovered else "NOT_RECOVERED",
                product_found=bool(recovered),
            )

        if self.entry_mode == "Cadastro manual":
            saved_product = self.database.buscar_produto_por_link(product["link"])

            if not saved_product:
                manual_store = self.store_key(product)
                if manual_store not in {"amazon", "shopee"}:
                    logging.getLogger(__name__).error(
                        "product recovery: function=save_and_notify "
                        "identifier=%s url=%s database_lookup_attempted=True "
                        "automatic_creation_attempted=%s "
                        "return_reason=PRODUCT_NOT_FOUND",
                        self.database.referencia_produto_link(
                            product.get("link", "")
                        ) or "NOT_AVAILABLE",
                        product.get("link", ""),
                        self.store_key(product) == "mercado livre",
                    )
                    messagebox.showerror(
                        "Produto nao encontrado",
                        "Este produto ainda nao esta na lista. Pesquise ou colete o "
                        "produto primeiro e tente novamente.",
                    )
                    return

                try:
                    store_label = (
                        "Shopee" if manual_store == "shopee" else "Amazon"
                    )
                    self.status.configure(
                        text=f"Importando o produto diretamente da {store_label}..."
                    )
                    self.update_idletasks()
                    if manual_store == "shopee":
                        imported = Shopee().product_from_url(product["link"])
                    else:
                        imported = self.manual_product_data(product["link"])
                        try:
                            if imported is None:
                                imported = Amazon().product_from_url(product["link"])
                        except ValueError as direct_error:
                            reference = self.database.referencia_produto_link(
                                product["link"]
                            )
                            affiliate_url = self.affiliate_link.get().strip()
                            try:
                                self.status.configure(
                                    text="Pagina direta indisponivel; tentando o link afiliado..."
                                )
                                self.update_idletasks()
                                imported = Amazon().product_from_url(affiliate_url)
                            except Exception:
                                imported = None

                        if imported is None:
                            self.status.configure(
                                text="Pagina direta indisponivel; pesquisando o codigo na Amazon..."
                            )
                            self.update_idletasks()
                            results = Amazon().search(reference)
                            imported = next(
                                (
                                    item
                                    for item in results
                                    if self.database.referencia_produto_link(
                                        item.get("link", "")
                                    ) == reference
                                ),
                                None,
                            )
                            if imported is None:
                                raise direct_error

                    # Usa sempre a URL canonica informada pelo usuario para que
                    # produto e vinculo afiliado tenham exatamente a mesma chave.
                    imported["link"] = product["link"]
                    self.database.salvar_produto(imported)
                    saved_product = self.database.buscar_produto_por_link(
                        product["link"]
                    )
                except (ValueError, RuntimeError) as error:
                    messagebox.showerror(
                        "Falha ao importar produto",
                        str(error)
                        + ("\n\nPreencha nome, preco, categoria e link da imagem "
                           "para cadastrar sem depender da coleta da Amazon."
                           if self.manual_only else ""),
                    )
                    return
                except Exception as error:
                    messagebox.showerror(
                        "Falha ao importar produto",
                        f"Nao foi possivel consultar a pagina da loja: {error}",
                    )
                    return

                if not saved_product:
                    messagebox.showerror(
                        "Falha ao importar produto",
                        "O produto foi consultado, mas nao pôde ser salvo no banco.",
                    )
                    return

            product = dict(saved_product)
            if self.manual_only:
                category = self.MANUAL_CATEGORIES.get(
                    self.manual_category.get(), ""
                )
                if category:
                    product["categoria_manual"] = category
            self.database.salvar_link_afiliado(
                product["loja"],
                product["link"],
                self.affiliate_link.get().strip(),
                self.tracking_label.get().strip(),
            )

        image = str(product["imagem"] or "").strip()
        current_price = Parser.price_to_float(
            product.get("preco", product.get("preco_valor", ""))
        )
        self.trace_send_stage(
            "PRICE_CHECK",
            product,
            reason="VALID" if current_price > 0 else "PRICE_MISSING",
            product_found=True,
        )
        if store == "mercado livre" and current_price <= 0:
            messagebox.showerror(
                "Preço ausente",
                "O produto foi recuperado, mas não possui preço atual válido.",
            )
            return

        self.trace_send_stage(
            "IMAGE_CHECK",
            product,
            reason="VALID" if image.startswith("http") else "IMAGE_INVALID",
            product_found=True,
        )
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

        manual_override = False
        discount_status = "NOT_REQUIRED"
        if self.entry_mode == "Cadastro manual":
            _ready, stale, low_discount = self.notifier.partition_offer_quality(
                [product]
            )
            reasons = []
            if stale:
                reasons.append("a oferta pode estar vencida")
            if low_discount:
                reasons.append("o desconto esta abaixo do minimo automatico")
            discount_status = (
                "STALE" if stale
                else "INSUFFICIENT" if low_discount
                else "APPROVED"
            )
            self.trace_send_stage(
                "DISCOUNT_CHECK",
                product,
                discount_status=discount_status,
            )

            if reasons:
                manual_override = messagebox.askyesno(
                    "Confirmar envio manual",
                    "Este produto nao passou no filtro automatico porque "
                    + " e ".join(reasons)
                    + ".\n\nDeseja enviar mesmo assim?",
                )
                if not manual_override:
                    self.trace_send_stage(
                        "EARLY_RETURN",
                        product,
                        reason="MANUAL_CONFIRMATION_CANCELLED",
                        discount_status=discount_status,
                    )
                    messagebox.showinfo(
                        "Envio cancelado",
                        "O envio manual foi cancelado pelo usuário.",
                    )
                    return

        self.trace_send_stage(
            "BEFORE_MESSAGE_GENERATION",
            product,
            category_status="MANUAL_DESTINATION",
            whatsapp_status="DESTINATION_FOUND",
        )
        try:
            preview_message = self.notifier.format_alert(product)
        except Exception as error:
            self.trace_send_stage(
                "MESSAGE_GENERATION_FAILED",
                product,
                reason=f"{type(error).__name__}: {error}",
                category_status="MANUAL_DESTINATION",
                whatsapp_status="NOT_STARTED",
            )
            messagebox.showerror(
                "Falha ao gerar mensagem",
                f"Não foi possível montar a mensagem:\n\n{error}",
            )
            return
        if not str(preview_message or "").strip():
            messagebox.showerror(
                "Falha ao gerar mensagem",
                "O formatador retornou uma mensagem vazia.",
            )
            return
        self.trace_send_stage(
            "MESSAGE_GENERATED",
            product,
            category_status="MANUAL_DESTINATION",
            whatsapp_status="READY_TO_SEND",
        )
        self.trace_send_stage(
            "BEFORE_WHATSAPP_SEND",
            product,
            category_status="MANUAL_DESTINATION",
            whatsapp_status="STARTING",
        )
        result = self.send_to_selected_destination(
            product,
            destination_label,
            destination,
        )
        self.trace_send_stage(
            "AFTER_WHATSAPP_SEND",
            product,
            reason=str(result or "EMPTY_RESULT"),
            category_status="MANUAL_DESTINATION",
            whatsapp_status=(
                "SENT" if str(result).startswith("Enviado por:")
                else "FAILED_OR_BLOCKED"
            ),
        )

        if result.startswith("Enviado por:"):
            self.trace_send_stage(
                "BEFORE_HISTORY_RECORD",
                product,
                whatsapp_status="SENT",
            )
            self.database.marcar_notificacao_manual(
                product["link"],
                product["loja"],
                product["titulo"],
            )
            self.trace_send_stage(
                "AFTER_HISTORY_RECORD",
                product,
                reason="RECORDED",
                whatsapp_status="SENT",
            )
        self.show_manual_destination_result(result)

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
        if not store:
            raise ValueError(
                "Loja nao identificada no link original. Use um link da Amazon, "
                "Shopee ou Mercado Livre."
            )
        domain = (urlparse(affiliate_link).hostname or "").lower()
        valid_domains = self.VALID_DOMAINS.get(store, set())

        if (
            domain not in valid_domains
            and self.identify_store_by_link(affiliate_link) != store
        ):
            expected = ", ".join(sorted(valid_domains))
            raise ValueError(f"Dominio invalido para {store}: use {expected}.")

        if affiliate_link == product["link"]:
            raise ValueError("O link afiliado nao pode ser igual ao link original.")

    def test_affiliate_link(self):

        try:
            product = self.selected_product()
        except ValueError as error:
            messagebox.showerror("Link original invalido", str(error))
            return

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
            if self.store_key(product) == "mercado livre":
                try:
                    self.ensure_mercado_livre_product_record(product)
                except Exception as error:
                    logging.getLogger(__name__).warning(
                        "mercado livre product recovery: "
                        "function=test_affiliate_link result=deferred "
                        "identifier=%s url=%s database_lookup_attempted=True "
                        "automatic_creation_attempted=True reason=%s",
                        self.database.referencia_produto_link(
                            product.get("link", "")
                        ) or "NOT_AVAILABLE",
                        product.get("link", ""),
                        error,
                    )
            messagebox.showinfo(
                "Link confirmado",
                "Link testado. Agora voce pode salvar ou notificar.",
            )

    def ensure_mercado_livre_product_record(self, product):

        original_url = str(product.get("link", "") or "").strip()
        product_id = self.database.referencia_produto_link(original_url)
        runtime_logger = logging.getLogger(__name__)
        runtime_logger.info(
            "mercado livre product recovery: function="
            "ensure_mercado_livre_product_record identifier=%s url=%s "
            "database_lookup_attempted=True automatic_creation_attempted=False",
            product_id or "NOT_AVAILABLE",
            original_url,
        )
        if not product_id:
            raise ValueError(
                "O identificador MLB nao foi encontrado na URL original."
            )
        saved = self.database.buscar_produto_por_link(original_url)
        if saved:
            saved_category = str(
                saved["categoria_original"]
                if "categoria_original" in saved.keys()
                else ""
            ).strip()
            saved_old_price = (
                float(saved["preco_antigo"] or 0)
                if "preco_antigo" in saved.keys()
                else 0
            )
            if not saved_category or saved_old_price <= 0:
                try:
                    refreshed = MercadoLivre().product_from_url(original_url)
                    refreshed["loja"] = "Mercado Livre"
                    refreshed["link"] = original_url
                    self.database.salvar_produto(refreshed)
                    saved = self.database.buscar_produto_por_link(original_url)
                    saved_category = str(
                        saved["categoria_original"]
                        if saved and "categoria_original" in saved.keys()
                        else ""
                    ).strip()
                    saved_old_price = (
                        float(saved["preco_antigo"] or 0)
                        if saved and "preco_antigo" in saved.keys()
                        else 0
                    )
                    runtime_logger.info(
                        "mercado livre product recovery: result=refreshed "
                        "identifier=%s category_original=%s "
                        "old_price_found=%s",
                        product_id,
                        saved_category or "NOT_AVAILABLE",
                        saved_old_price > 0,
                    )
                except Exception as error:
                    runtime_logger.warning(
                        "mercado livre product recovery: "
                        "category_refresh_failed identifier=%s reason=%s",
                        product_id,
                        error,
                    )
            runtime_logger.info(
                "mercado livre product recovery: result=found "
                "identifier=%s strategy=URL_OR_PRODUCT_ID",
                product_id,
            )
            return saved
        candidate = dict(product)
        title = str(candidate.get("titulo", "") or "").strip()
        price = str(candidate.get("preco", "") or "").strip()
        image = str(candidate.get("imagem", "") or "").strip()
        strategy = "LOADED_OFFER_PAYLOAD"
        if not (
            title
            and title != "Cadastro manual"
            and Parser.price_to_float(price) > 0
            and image.startswith(("http://", "https://"))
        ):
            strategy = "MERCADO_LIVRE_PRODUCT_PAGE"
            candidate = MercadoLivre().product_from_url(original_url)
        candidate["loja"] = "Mercado Livre"
        candidate["link"] = original_url
        runtime_logger.info(
            "mercado livre product recovery: identifier=%s url=%s "
            "database_lookup_attempted=True automatic_creation_attempted=True "
            "strategy=%s",
            product_id,
            original_url,
            strategy,
        )
        self.database.salvar_produto(candidate)
        saved = self.database.buscar_produto_por_link(original_url)
        if not saved:
            raise RuntimeError(
                "O registro foi criado, mas nao foi recuperado pelo "
                "identificador MLB."
            )
        return saved

    def route_unmapped_category_to_review(
        self,
        product,
        discount_status="NOT_CHECKED",
    ):

        review_product = dict(product)
        original_category = str(
            review_product.get("categoria_original")
            or review_product.get("breadcrumb")
            or "Não informada pelo Mercado Livre"
        ).strip()
        review_product["categoria_original"] = original_category
        reason = "Categoria original não mapeada: " + original_category
        self.database.registrar_pendencias_revisao(
            [review_product],
            "categoria",
            reason,
        )
        self.trace_send_stage(
            "CATEGORY_SENT_TO_REVIEW",
            review_product,
            reason=reason,
            category_status="PENDING_REVIEW",
            discount_status=discount_status,
            whatsapp_status="REVIEW_GROUP",
        )
        result = self.notifier.send_review_alert(review_product)
        if result.startswith("Oferta enviada"):
            messagebox.showinfo(
                "Enviado para revisão",
                result + "\n\nCategoria registrada: "
                + original_category
                + "\n\nApós mapear essa categoria, as próximas ofertas "
                "serão classificadas automaticamente.",
            )
            self.load_pending()
            return True
        messagebox.showerror(
            "Falha no grupo de revisão",
            result + "\n\nA oferta foi preservada em Pendências.",
        )
        return False

    def send_to_selected_destination(
        self,
        product,
        destination_label,
        destination,
    ):

        product = dict(product)
        send_logger = logging.getLogger("promobot.manual_destination")
        title = str(product.get("titulo", "") or "")
        store = str(product.get("loja", "") or "")
        result_status = "FAILED"
        try:
            if not destination:
                return f"Falha: destino {destination_label} não configurado."
            if not self.notifier.whatsapp_configured():
                return "Falha: WhatsApp não configurado."
            if not self.notifier.has_affiliate_link(product):
                return "Falha: link afiliado oficial não validado."
            image = self.notifier.verified_whatsapp_image(product)
            if not str(image or "").startswith("http"):
                return "Falha: imagem do produto não confirmada."

            self.notifier.send_whatsapp_message(
                self.notifier.format_alert(product),
                image,
                destination,
            )
            original_link = str(product.get("link", "") or "")
            self.database.registrar_envio(
                store,
                title,
                original_link,
                self.notifier.affiliate_link(product),
                self.database.etiqueta_link_afiliado(original_link),
                "WhatsApp Manual",
                destination,
            )
            result_status = "SENT"
            return f"Enviado por: WhatsApp — {destination_label}."
        except Exception as error:
            return f"Falha no envio para {destination_label}: {error}"
        finally:
            send_logger.info(
                "product=%s store=%s destination=%s result=%s",
                title,
                store,
                destination_label,
                result_status,
            )

    def show_manual_destination_result(self, result):

        if str(result or "").startswith("Enviado por:"):
            messagebox.showinfo("Notificacao", result)
            self.clear_manual_destination()
            return True
        messagebox.showerror("Falha na notificacao", result)
        return False

    def store_key(self, product):

        store = str(product["loja"] or "").strip().lower()
        link = str(product["link"] or "").lower()

        if store in {"shopee", "amazon", "mercado livre"}:
            return store

        return self.identify_store_by_link(link)

    @staticmethod
    def identify_store_by_link(link):

        domain = (urlparse(str(link or "").strip()).hostname or "").lower()

        if domain in {"shope.ee", "collshp.com", "shopee.com.br"} or domain.endswith(
            ".shopee.com.br"
        ):
            return "shopee"

        if domain in {"amzn.to", "link.amazon", "amazon.com.br"} or domain.endswith(
            ".amazon.com.br"
        ):
            return "amazon"

        if domain in {"meli.la", "mercadolivre.com.br"} or domain.endswith(
            ".mercadolivre.com.br"
        ):
            return "mercado livre"

        return ""

    @staticmethod
    def store_display_name(store):

        return {
            "amazon": "Amazon",
            "shopee": "Shopee",
            "mercado livre": "Mercado Livre",
        }.get(store, "")
