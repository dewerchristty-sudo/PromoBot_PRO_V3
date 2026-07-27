import tkinter as tk
import threading
import webbrowser
import logging
import sys
from tkinter import messagebox
from pathlib import Path
from urllib.parse import urlparse

import customtkinter as ctk

from src.core.notifier import Notifier
from src.config import ConfigValidator
from src.scraper import Parser
from src.stores.amazon import Amazon
from src.stores.mercado_livre import MercadoLivre
from src.stores.shopee import Shopee


class AffiliateLinksPage(ctk.CTkFrame):

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

    @staticmethod
    def manual_product_diagnostic_logger():

        runtime_root = (
            Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]
        )
        log_dir = runtime_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        diagnostic_logger = logging.getLogger(
            "promobot.manual_product_diagnostic"
        )
        diagnostic_logger.setLevel(logging.WARNING)
        diagnostic_logger.propagate = False
        log_path = (log_dir / "manual_product_diagnostic.log").resolve()
        has_target_handler = any(
            isinstance(handler, logging.FileHandler)
            and Path(handler.baseFilename).resolve() == log_path
            for handler in diagnostic_logger.handlers
        )
        if not has_target_handler:
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s"
            ))
            diagnostic_logger.addHandler(handler)
        return diagnostic_logger

    def trace_manual_product(self, stage, product):

        fields = (
            "id",
            "link",
            "preco",
            "preco_valor",
            "preco_antigo",
            "maior_preco",
            "imagem_manual",
            "loja",
        )
        snapshot = {
            field: self.value_from_product(product, field)
            for field in fields
        }
        self.manual_product_diagnostic_logger().warning(
            "Cadastro Manual diagnostico temporario: etapa=%s product=%r",
            stage,
            snapshot,
        )

    @staticmethod
    def value_from_product(product, field):

        if isinstance(product, dict):
            return product.get(field)
        try:
            return product[field]
        except (KeyError, IndexError, TypeError):
            return getattr(product, field, None)

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
        self.manual_only = bool(manual_only)
        self.shopee_manual_link = ""
        self.manual_fallback_store = ""
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

        form = ctk.CTkScrollableFrame(self)
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

        ctk.CTkLabel(self.manual_details, text="Preco atual", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=(0, 6), pady=(0, 5)
        )
        ctk.CTkLabel(self.manual_details, text="Preco anterior", anchor="w").grid(
            row=2, column=1, sticky="ew", padx=(6, 0), pady=(0, 5)
        )
        self.manual_price = ctk.CTkEntry(
            self.manual_details, placeholder_text="Ex.: 149,90"
        )
        self.manual_price.grid(row=3, column=0, sticky="ew", padx=(0, 6), pady=(0, 10))
        self.manual_old_price = ctk.CTkEntry(
            self.manual_details, placeholder_text="Opcional. Ex.: 199,90"
        )
        self.manual_old_price.grid(
            row=3, column=1, sticky="ew", padx=(6, 0), pady=(0, 10)
        )

        ctk.CTkLabel(self.manual_details, text="Categoria", anchor="w").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(0, 5)
        )
        self.manual_category = ctk.CTkOptionMenu(
            self.manual_details,
            values=list(self.MANUAL_CATEGORIES),
        )
        self.manual_category.grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(0, 10)
        )
        self.manual_category.set("Selecione a categoria")

        ctk.CTkLabel(self.manual_details, text="URL da imagem", anchor="w").grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(0, 5)
        )
        self.manual_image = ctk.CTkEntry(
            self.manual_details,
            placeholder_text="Clique com o botao direito na imagem e copie o endereco",
        )
        self.manual_image.grid(row=7, column=0, columnspan=2, sticky="ew")

        ctk.CTkLabel(form, text="Etiqueta de acompanhamento", anchor="w").grid(
            row=7, column=0, sticky="ew", padx=18, pady=(0, 5)
        )

        self.tracking_label = ctk.CTkEntry(form)
        self.tracking_label.grid(row=8, column=0, sticky="ew", padx=18, pady=(0, 16))
        self.tracking_label.insert(0, "promobotwhatsapp")

        buttons = ctk.CTkFrame(form, fg_color="transparent")
        buttons.grid(row=9, column=0, sticky="ew", padx=18, pady=(0, 12))

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

        self.preview_button = ctk.CTkButton(
            buttons,
            text="Visualizar mensagem",
            width=165,
            command=self.preview_selected_message,
        )
        self.preview_button.pack(side="left", padx=(8, 0))

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
            row=10, column=0, sticky="ew", padx=18, pady=(0, 5)
        )

        self.history = ctk.CTkTextbox(form, height=150)
        self.history.grid(row=11, column=0, sticky="nsew", padx=18, pady=(0, 18))
        form.grid_rowconfigure(11, weight=1)

    def manual_product_data(self, link):

        shopee_manual = (
            getattr(self, "entry_mode", "") == "Cadastro manual"
            and link == getattr(self, "shopee_manual_link", "")
        )

        if not self.manual_only and not shopee_manual:
            return None

        title = self.manual_title.get().strip()
        price = self.manual_price.get().strip()
        old_price_field = getattr(self, "manual_old_price", None)
        old_price = old_price_field.get().strip() if old_price_field else ""
        image = self.manual_image.get().strip()
        category = self.MANUAL_CATEGORIES.get(self.manual_category.get(), "")
        current_value = Parser.price_to_float(price)
        old_value = Parser.price_to_float(old_price)

        if not any((title, price, old_price, image, category)) and not shopee_manual:
            return None

        missing = []
        if not title:
            missing.append("nome")
        if current_value <= 0:
            missing.append("preco")
        if old_price and old_value <= 0:
            raise ValueError("Informe um preco anterior valido.")
        if old_price and old_value <= current_value:
            raise ValueError(
                "O preco anterior deve ser maior que o preco atual."
            )
        if not image.startswith(("http://", "https://")):
            missing.append("link da imagem")
        if not category:
            missing.append("categoria")
        if missing:
            raise ValueError("Complete os dados manuais: " + ", ".join(missing) + ".")

        fallback_store = (
            getattr(self, "manual_fallback_store", "")
            if shopee_manual
            else ""
        )
        return {
            "loja": fallback_store or ("Shopee" if shopee_manual else "Amazon"),
            "titulo": title,
            "preco": price,
            "preco_valor": current_value,
            "preco_antigo": old_price,
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

        original_link = str(link or "").strip()
        store = self.identify_store_by_link(original_link)
        reference = self.database.referencia_produto_link(original_link)
        clean_link = Parser.remove_tracking(original_link).rstrip("/")

        if not store:
            return clean_link

        if not reference:
            raise ValueError(
                "O link original precisa abrir diretamente a pagina do produto. "
                "Nao use pagina do carrinho, linkId ou trecho de endereço."
            )

        if store == "amazon":
            return f"https://www.amazon.com.br/dp/{reference}"

        if store == "mercado livre":
            number = reference.removeprefix("MLB")
            return f"https://produto.mercadolivre.com.br/MLB-{number}"

        return clean_link

    def change_entry_mode(self, mode):

        self.entry_mode = mode
        manual = mode == "Cadastro manual"
        if manual:
            self.product_label.grid_remove()
            self.product_menu.grid_remove()
        else:
            self.product_label.grid()
            self.product_menu.grid()
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

    def save_and_notify(self):

        shopee_manual_active = False
        manual_product = None
        manual_expected_price = None
        manual_expected_old_price = ""
        product = self.save_selected_link()

        if not product:
            return

        if self.store_key(product) == "mercado livre":
            try:
                recovered = self.ensure_mercado_livre_product_record(product)
            except (ValueError, RuntimeError) as error:
                messagebox.showerror(
                    "Produto não encontrado",
                    "Não foi possível recuperar ou criar automaticamente o "
                    f"produto do Mercado Livre.\n\n{error}",
                )
                return
            if recovered:
                product = dict(recovered)

        if self.entry_mode == "Cadastro manual":
            prepared_manual_image = None
            manual_shopee_image = False
            manual_product = None
            store_key = self.store_key(product)
            shopee_manual_active = (
                store_key == "shopee"
                and product["link"]
                == getattr(self, "shopee_manual_link", "")
            )
            saved_product = self.database.buscar_produto_por_link(product["link"])
            mercado_livre_category_enrichment = bool(
                store_key == "mercado livre"
                and saved_product
                and not str(
                    self.value_from_product(
                        saved_product, "categoria_manual"
                    ) or ""
                ).strip()
                and not str(
                    self.value_from_product(saved_product, "breadcrumb") or ""
                ).strip()
                and not str(
                    self.value_from_product(
                        saved_product, "categoria_original"
                    ) or ""
                ).strip()
            )
            if shopee_manual_active:
                self.trace_manual_product(
                    "apos_busca_inicial_banco",
                    saved_product or {},
                )

            if (
                not saved_product
                or shopee_manual_active
                or mercado_livre_category_enrichment
            ):
                importer = {
                    "amazon": Amazon,
                    "shopee": Shopee,
                    "mercado livre": MercadoLivre,
                }.get(store_key)

                if not importer:
                    messagebox.showerror(
                        "Loja nao suportada",
                        "No momento, apenas Amazon, Shopee e Mercado Livre "
                        "podem ser importados automaticamente pelo "
                        "Cadastro manual.",
                    )
                    return

                try:
                    self.status.configure(
                        text=f"Importando o produto diretamente da loja..."
                    )
                    self.update_idletasks()

                    shopee_blocked = False
                    mercado_livre_blocked = False
                    if shopee_manual_active:
                        manual_product = self.manual_product_data(product["link"])
                        self.trace_manual_product(
                            "apos_manual_product_data",
                            manual_product,
                        )
                        manual_expected_price = manual_product["preco_valor"]
                        manual_expected_old_price = manual_product["preco_antigo"]
                        imported = {
                            **dict(saved_product or {}),
                            **manual_product,
                        }
                        self.trace_manual_product(
                            "apos_merge_banco_com_manual_antes_salvar",
                            imported,
                        )
                        try:
                            prepared_manual_image = (
                                self.notifier.prepare_whatsapp_image(
                                    imported["imagem"]
                                )
                            )
                        except ValueError as error:
                            messagebox.showerror(
                                "Imagem invalida",
                                f"{error}\n\nEscolha outra URL de imagem.",
                            )
                            return
                        manual_shopee_image = True
                    else:
                        imported = self.manual_product_data(product["link"])
                        try:
                            if imported is None:
                                imported = importer().product_from_url(
                                    product["link"]
                                )
                        except ValueError as direct_error:
                            shopee_blocked = (
                                store_key == "shopee"
                                and "bloqueou o acesso com pagina de verificacao"
                                in str(direct_error).casefold()
                            )
                            mercado_livre_blocked = store_key == "mercado livre"
                            affiliate_url = self.affiliate_link.get().strip()
                            try:
                                self.status.configure(
                                    text="Pagina direta indisponivel; tentando o link afiliado..."
                                )
                                self.update_idletasks()
                                imported = importer().product_from_url(
                                    affiliate_url
                                )
                            except Exception as affiliate_error:
                                shopee_blocked = shopee_blocked or (
                                    store_key == "shopee"
                                    and "bloqueou o acesso com pagina de verificacao"
                                    in str(affiliate_error).casefold()
                                )
                                mercado_livre_blocked = (
                                    mercado_livre_blocked
                                    or store_key == "mercado livre"
                                )
                                imported = None

                    if imported is None:
                        if shopee_blocked or mercado_livre_blocked:
                            self.shopee_manual_link = product["link"]
                            self.manual_fallback_store = (
                                "Mercado Livre"
                                if mercado_livre_blocked
                                else "Shopee"
                            )
                            self.manual_details.grid(
                                row=6,
                                column=0,
                                sticky="ew",
                                padx=18,
                                pady=(0, 14),
                            )
                            self.manual_title.focus_set()
                            self.status.configure(
                                text=(
                                    f"O {self.manual_fallback_store} bloqueou "
                                    "a coleta automatica. "
                                    "Preencha os dados abaixo e clique novamente "
                                    "em Salvar e notificar agora."
                                )
                            )
                            self.update_idletasks()
                            raise ValueError(
                                f"O {self.manual_fallback_store} bloqueou a "
                                "coleta automatica deste produto.\n\n"
                                "Preencha manualmente:\n"
                                "- nome do produto;\n"
                                "- preco;\n"
                                "- categoria;\n"
                                "- link da imagem.\n\n"
                                "O link original e o link de afiliado informados "
                                "foram preservados."
                            )
                        self.status.configure(
                            text="Nao foi possivel importar o produto automaticamente."
                        )
                        self.update_idletasks()
                        raise ValueError(
                            "Nao foi possivel obter os dados do produto. "
                            "Verifique o link e tente novamente."
                        )

                    # Usa sempre a URL canonica informada pelo usuario para que
                    # produto e vinculo afiliado tenham exatamente a mesma chave.
                    imported["link"] = product["link"]
                    self.database.salvar_produto(imported)
                    saved_product = self.database.buscar_produto_por_link(
                        product["link"]
                    )
                    if shopee_manual_active:
                        self.trace_manual_product(
                            "apos_salvar_produto_e_recarregar_banco",
                            saved_product or {},
                        )
                except (ValueError, RuntimeError) as error:
                    messagebox.showerror(
                        "Falha ao importar produto",
                        str(error)
                        + ("\n\nPreencha nome, preco, categoria e link da imagem "
                           "para cadastrar sem depender da coleta automatica."
                           if self.manual_only else ""),
                    )
                    return
                except Exception as error:
                    messagebox.showerror(
                        "Falha ao importar produto",
                        f"Nao foi possivel consultar a pagina: {error}",
                    )
                    return

                if not saved_product:
                    messagebox.showerror(
                        "Falha ao importar produto",
                        "O produto foi consultado, mas nao pôde ser salvo no banco.",
                    )
                    return

            product = (
                {
                    **dict(saved_product or {}),
                    **manual_product,
                }
                if shopee_manual_active and manual_product is not None
                else dict(saved_product)
            )
            if manual_product is not None:
                self.trace_manual_product(
                    "apos_merge_final_banco_com_manual",
                    product,
                )
            manual_shopee_image = (
                self.store_key(product) == "shopee"
                and product["link"]
                == getattr(self, "shopee_manual_link", "")
            )
            if manual_shopee_image and not prepared_manual_image:
                manual_image_url = self.manual_image.get().strip()
                try:
                    prepared_manual_image = (
                        self.notifier.prepare_whatsapp_image(
                            manual_image_url
                        )
                    )
                except ValueError as error:
                    messagebox.showerror(
                        "Imagem invalida",
                        f"{error}\n\nEscolha outra URL de imagem.",
                    )
                    return
                product["imagem"] = manual_image_url
            if manual_shopee_image:
                product["imagem_manual"] = True
                product["imagem_whatsapp"] = prepared_manual_image
                self.trace_manual_product(
                    "apos_update_campos_tecnicos_manuais",
                    product,
                )
            if self.entry_mode == "Cadastro manual":
                category = self.MANUAL_CATEGORIES.get(
                    self.manual_category.get(), ""
                )
                current_category = str(
                    product.get("categoria_manual") or ""
                ).strip()
                if category and category != current_category:
                    approved = messagebox.askyesno(
                        "Aprovar categoria para envio",
                        "Esta categoria será associada explicitamente ao "
                        "produto:\n\n"
                        f"Produto: {product.get('titulo') or 'Produto'}\n"
                        f"Loja: {product.get('loja') or 'Não informada'}\n"
                        f"Categoria canônica: {category}\n\n"
                        "Deseja salvar esta aprovação e continuar?",
                    )
                    if not approved:
                        messagebox.showwarning(
                            "Categoria não aprovada",
                            self.notifier.category_block_message(product),
                        )
                        return
                    product["categoria_manual"] = category
                    self.database.salvar_produto(product)
                    logging.getLogger(__name__).info(
                        "category_approved_manually: store=%s category=%s",
                        product.get("loja", ""),
                        category,
                    )
            self.database.salvar_link_afiliado(
                product["loja"],
                product["link"],
                self.affiliate_link.get().strip(),
                self.tracking_label.get().strip(),
            )

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

        manual_override = False
        if self.entry_mode == "Cadastro manual":
            _ready, stale, low_discount = self.notifier.partition_offer_quality(
                [product]
            )
            reasons = []
            if stale:
                reasons.append("a oferta pode estar vencida")
            if low_discount:
                reasons.append("o desconto esta abaixo do minimo automatico")

            if reasons:
                manual_override = messagebox.askyesno(
                    "Confirmar envio manual",
                    "Este produto nao passou no filtro automatico porque "
                    + " e ".join(reasons)
                    + ".\n\nDeseja enviar mesmo assim?",
                )
                if not manual_override:
                    return

        ignore_notification_hours = (
            self.entry_mode == "Cadastro manual"
            and ConfigValidator.dev_mode_enabled()
        )
        if shopee_manual_active:
            current_price = Parser.price_to_float(product.get("preco", ""))
            if (
                manual_expected_price is None
                or abs(current_price - manual_expected_price) > 0.0001
            ):
                messagebox.showerror(
                    "Cadastro manual inconsistente",
                    "O preco atual foi alterado durante o processamento. "
                    "O envio foi bloqueado.",
                )
                return
            if (
                manual_expected_old_price
                and product.get("preco_antigo", "")
                != manual_expected_old_price
            ):
                messagebox.showerror(
                    "Cadastro manual inconsistente",
                    "O preco anterior foi perdido durante o processamento. "
                    "O envio foi bloqueado.",
                )
                return
            self.trace_manual_product(
                "imediatamente_antes_do_notifier",
                product,
            )
        result = (
            self.notifier.send_manual_alerts(
                [product],
                ignore_notification_hours=ignore_notification_hours,
            )
            if manual_override
            else self.notifier.send_alerts(
                [product],
                ignore_notification_hours=ignore_notification_hours,
            )
        )

        if result.startswith("Enviado por:"):
            self.database.marcar_notificacao_manual(
                product["link"],
                product["loja"],
                product["titulo"],
            )
            messagebox.showinfo("Notificacao", result)
        else:
            route = self.notifier.category_routing_diagnostic(product)
            detail = (
                "\n\n" + self.notifier.category_block_message(product)
                if route["reason"].startswith("CATEGORY_")
                else ""
            )
            messagebox.showerror("Falha na notificacao", result + detail)

        self.load_pending()

    def build_message_preview(self, product):
        route = self.notifier.category_routing_diagnostic(product)
        destination = (
            "configurado"
            if route["destination_configured"]
            else "não configurado"
        )
        return "\n".join((
            self.notifier.format_alert(product),
            "",
            "------------------------------",
            f"Categoria: {route['canonical_category'] or 'não detectada'}",
            f"Origem da categoria: {route['source']}",
            f"Destino previsto: {destination}",
            f"Status do roteamento: {route['reason']}",
            "PREVIEW — nenhuma mensagem foi enviada.",
        ))

    def preview_selected_message(self):
        try:
            selected = self.selected_product()
        except ValueError as error:
            messagebox.showerror("Visualizar mensagem", str(error))
            return
        if not selected:
            messagebox.showinfo(
                "Visualizar mensagem", "Selecione um produto."
            )
            return
        product = self.database.buscar_produto_por_link(selected["link"])
        if not product:
            try:
                product = self.manual_product_data(selected["link"])
            except ValueError as error:
                messagebox.showerror("Visualizar mensagem", str(error))
                return
        if not product:
            messagebox.showinfo(
                "Visualizar mensagem",
                "Salve ou importe o produto antes de visualizar a mensagem.",
            )
            return
        messagebox.showinfo(
            "Visualizar mensagem — sem envio",
            self.build_message_preview(dict(product)),
        )

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
                        "mercado livre product identity: stage=link_confirmed "
                        "result=deferred reason=%s",
                        error,
                    )
            messagebox.showinfo(
                "Link confirmado",
                "Link testado. Agora voce pode salvar ou notificar.",
            )

    def ensure_mercado_livre_product_record(self, product):
        """Localiza ou cria o registro ML sem depender da tela Buscar."""

        supplied_url = str(
            self.value_from_product(product, "link") or ""
        ).strip()
        product_id = self.database.referencia_produto_link(supplied_url)
        diagnostic_logger = logging.getLogger(__name__)
        if not product_id:
            diagnostic_logger.warning(
                "mercado livre product identity: stage=lookup result=failed "
                "reason=PRODUCT_ID_NOT_EXTRACTED original_url=%s",
                supplied_url,
            )
            raise ValueError(
                "O identificador MLB não foi encontrado na URL original."
            )
        original_url = self.normalize_manual_product_link(supplied_url)
        diagnostic_logger.info(
            "mercado livre product identity: stage=lookup "
            "identifier_type=MERCADO_LIVRE_PRODUCT_ID identifier=%s "
            "original_url=%s",
            product_id or "NOT_AVAILABLE",
            original_url,
        )
        saved = self.database.buscar_produto_por_link(original_url)
        if saved:
            diagnostic_logger.info(
                "mercado livre product identity: stage=lookup result=found "
                "identifier=%s strategy=URL_OR_PRODUCT_ID",
                product_id,
            )
            return saved
        candidate = dict(product) if isinstance(product, dict) else {
            key: self.value_from_product(product, key)
            for key in (
                "loja", "titulo", "preco", "preco_valor", "link",
                "imagem", "categoria_manual", "breadcrumb",
                "categoria_original",
            )
        }
        candidate["loja"] = "Mercado Livre"
        candidate["link"] = original_url
        title = str(candidate.get("titulo") or "").strip()
        price = str(candidate.get("preco") or "").strip()
        image = str(candidate.get("imagem") or "").strip()
        can_create_from_loaded = bool(
            title
            and title != "Cadastro manual"
            and Parser.price_to_float(price) > 0
            and image.startswith(("http://", "https://"))
        )
        strategy = "LOADED_OFFER_PAYLOAD"
        if not can_create_from_loaded:
            strategy = "MERCADO_LIVRE_PRODUCT_PAGE"
            diagnostic_logger.info(
                "mercado livre product identity: stage=create "
                "identifier=%s loaded_payload_incomplete=True "
                "fallback=%s",
                product_id,
                strategy,
            )
            candidate = MercadoLivre().product_from_url(original_url)
            candidate["link"] = original_url
        self.database.salvar_produto(candidate)
        saved = self.database.buscar_produto_por_link(original_url)
        if not saved:
            diagnostic_logger.error(
                "mercado livre product identity: stage=create result=failed "
                "identifier=%s strategy=%s reason=RECORD_NOT_RECOVERED",
                product_id,
                strategy,
            )
            raise RuntimeError(
                "O produto foi importado, mas o registro não pôde ser "
                "recuperado pelo identificador MLB."
            )
        diagnostic_logger.info(
            "mercado livre product identity: stage=create result=created "
            "identifier=%s strategy=%s",
            product_id,
            strategy,
        )
        return saved

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
