import threading
from tkinter import messagebox

import customtkinter as ctk

from src.core.notifier import Notifier


class OffersPage(ctk.CTkFrame):

    CATEGORY_LABELS = {
        "Automatico": "",
        "Mamae e Bebe": "mamae_bebe",
        "Casa e Enxoval": "casa_enxoval",
        "Eletrodomesticos": "eletrodomesticos",
        "Smartphones e Tecnologia": "smartphones_tecnologia",
        "Beleza e Perfumaria": "beleza_perfumaria",
        "Limpeza e Utilidades": "limpeza_utilidades",
    }

    def __init__(self, master, database):
        super().__init__(master)

        self.database = database
        self.notifier = Notifier(database)
        self.ofertas = []
        self.selection_vars = {}
        self.offer_by_id = {}
        self.sending = False
        self.selected_category_label = "Automatico"
        self.category_buttons = {}

        self.criar_interface()
        self.carregar()

    def criar_interface(self):

        ctk.CTkLabel(
            self,
            text="Vitrine de Ofertas",
            font=("Arial", 30, "bold"),
        ).pack(pady=(18, 5))

        ctk.CTkLabel(
            self,
            text=(
                "Escolha ofertas acessiveis e envie manualmente para os grupos. "
                "Somente itens com imagem e link afiliado aparecem."
            ),
            font=("Arial", 13),
        ).pack(pady=(0, 12))

        filters = ctk.CTkFrame(self)
        filters.pack(fill="x", padx=18)

        ctk.CTkLabel(filters, text="Preco maximo R$").pack(
            side="left", padx=(10, 5), pady=10
        )
        self.max_price = ctk.CTkEntry(filters, width=85)
        self.max_price.insert(0, "200")
        self.max_price.pack(side="left", padx=(0, 12), pady=10)

        ctk.CTkLabel(filters, text="Desconto minimo %").pack(
            side="left", padx=(0, 5), pady=10
        )
        self.min_discount = ctk.CTkEntry(filters, width=70)
        self.min_discount.insert(0, "10")
        self.min_discount.pack(side="left", padx=(0, 12), pady=10)

        ctk.CTkButton(
            filters,
            text="Atualizar lista",
            width=120,
            command=self.carregar,
        ).pack(side="left", padx=5, pady=10)

        self.status = ctk.CTkLabel(filters, text="", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=10)

        actions = ctk.CTkFrame(self)
        actions.pack(fill="x", padx=18, pady=(8, 0))

        ctk.CTkButton(
            actions,
            text="Selecionar todas",
            width=120,
            command=lambda: self.marcar_todas(True),
        ).pack(side="left", padx=(10, 5), pady=9)

        ctk.CTkButton(
            actions,
            text="Limpar selecao",
            width=115,
            command=lambda: self.marcar_todas(False),
        ).pack(side="left", padx=5, pady=9)

        self.send_button = ctk.CTkButton(
            actions,
            text="Enviar selecionados",
            width=155,
            fg_color="#15803d",
            hover_color="#166534",
            command=self.enviar_selecionados,
        )
        self.send_button.pack(side="right", padx=10, pady=9)

        group_panel = ctk.CTkFrame(self)
        group_panel.pack(fill="x", padx=18, pady=(8, 0))
        ctk.CTkLabel(
            group_panel,
            text="Enviar para qual grupo?",
            font=("Arial", 13, "bold"),
        ).grid(row=0, column=0, columnspan=4, padx=10, pady=(8, 4), sticky="w")

        for index, label in enumerate(self.CATEGORY_LABELS):
            row = 1 + (index // 4)
            column = index % 4
            group_panel.grid_columnconfigure(column, weight=1)
            button = ctk.CTkButton(
                group_panel,
                text=label,
                height=34,
                command=lambda selected=label: self.selecionar_grupo(selected),
            )
            button.grid(
                row=row,
                column=column,
                padx=6,
                pady=(3, 8 if row == 2 else 3),
                sticky="ew",
            )
            self.category_buttons[label] = button

        self.selecionar_grupo("Automatico")

        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.pack(fill="both", expand=True, padx=18, pady=(8, 16))
        self.list_frame.grid_columnconfigure(1, weight=1)

    def selecionar_grupo(self, label):

        if label not in self.CATEGORY_LABELS:
            label = "Automatico"
        self.selected_category_label = label

        for button_label, button in self.category_buttons.items():
            selected = button_label == label
            button.configure(
                fg_color="#15803d" if selected else ("#3b8ed0", "#1f6aa5"),
                hover_color="#166534" if selected else ("#36719f", "#144870"),
                border_width=2 if selected else 0,
                border_color="#86efac" if selected else ("#3b8ed0", "#1f6aa5"),
            )

    @staticmethod
    def parse_filter(value, default):

        text = str(value or "").strip()
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            return max(float(text), 0)
        except ValueError:
            return float(default)

    @classmethod
    def filter_and_rank(cls, offers, max_price, min_discount):

        ranked = []

        for product in offers:
            current = float(product["preco_valor"] or 0)
            highest = float(product["maior_preco"] or 0)
            if current <= 0 or highest <= current:
                continue
            discount = ((highest - current) / highest) * 100
            if current > max_price or discount < min_discount:
                continue
            ranked.append((discount, product))

        ranked.sort(key=lambda item: (
            -item[0],
            -int(item[1]["coletas"] or 0),
            float(item[1]["preco_valor"] or 0),
        ))
        return ranked

    def carregar(self):

        max_price = self.parse_filter(self.max_price.get(), 200)
        min_discount = self.parse_filter(self.min_discount.get(), 10)
        ignored = self.database.listar_links_ofertas_ignoradas()
        ranked = self.filter_and_rank(
            self.database.ofertas_com_variacao(400),
            max_price,
            min_discount,
        )

        self.ofertas = []
        for discount, product in ranked:
            link = str(product["link"] or "").strip()
            image = str(product["imagem"] or "").strip()
            if link in ignored or not image.startswith("http"):
                continue
            if self.database.produto_ja_notificado(
                link,
                product["loja"],
                product["titulo"],
            ):
                continue
            ready, _blocked = self.notifier.partition_affiliate_ready([product])
            if not ready:
                continue
            self.ofertas.append((discount, product))
            if len(self.ofertas) >= 60:
                break

        self.renderizar()

    def renderizar(self):

        for widget in self.list_frame.winfo_children():
            widget.destroy()

        self.selection_vars = {}
        self.offer_by_id = {}
        self.status.configure(
            text=f"{len(self.ofertas)} oferta(s) pronta(s) para escolher"
        )

        if not self.ofertas:
            ctk.CTkLabel(
                self.list_frame,
                text=(
                    "Nenhuma oferta pronta com esses filtros.\n"
                    "Aumente o preco maximo, reduza o desconto minimo ou "
                    "cadastre os links afiliados pendentes."
                ),
                justify="center",
            ).grid(row=0, column=0, columnspan=2, padx=20, pady=35)
            return

        for row, (discount, product) in enumerate(self.ofertas):
            product_id = int(product["id"])
            selected = ctk.BooleanVar(value=False)
            self.selection_vars[product_id] = selected
            self.offer_by_id[product_id] = product

            checkbox = ctk.CTkCheckBox(
                self.list_frame,
                text="",
                width=28,
                variable=selected,
            )
            checkbox.grid(row=row, column=0, padx=(8, 2), pady=7, sticky="n")

            category = self.notifier.whatsapp_category(product)
            category_text = category.replace("_", " ").title() if category else "Escolher grupo"
            highest = float(product["maior_preco"] or product["preco_valor"])
            details = (
                f"{product['titulo']}\n"
                f"{product['loja']}  |  R$ {float(product['preco_valor']):.2f}  |  "
                f"antes R$ {highest:.2f}  |  {discount:.1f}% OFF  |  "
                f"{int(product['coletas'] or 0)} coletas  |  {category_text}"
            ).replace(".", ",")

            label = ctk.CTkLabel(
                self.list_frame,
                text=details,
                anchor="w",
                justify="left",
                wraplength=850,
            )
            label.grid(row=row, column=1, padx=(4, 10), pady=7, sticky="ew")

    def marcar_todas(self, selected):

        for variable in self.selection_vars.values():
            variable.set(bool(selected))

    def selected_products(self):

        return [
            dict(self.offer_by_id[product_id])
            for product_id, selected in self.selection_vars.items()
            if selected.get()
        ]

    def enviar_selecionados(self):

        if self.sending:
            return

        products = self.selected_products()
        if not products:
            messagebox.showwarning(
                "Selecionar ofertas",
                "Marque pelo menos uma oferta antes de enviar.",
            )
            return

        category_key = self.CATEGORY_LABELS.get(
            self.selected_category_label,
            "",
        )
        unrouted = []
        for product in products:
            if category_key:
                product["categoria_manual"] = category_key
            if not self.notifier.whatsapp_recipients_for_alert(product):
                unrouted.append(product["titulo"])

        if unrouted:
            messagebox.showwarning(
                "Escolha o grupo",
                "Alguns produtos nao possuem categoria automatica.\n\n"
                "Escolha um grupo de destino antes de enviar.",
            )
            return

        summary = "\n".join(
            f"- {product['titulo'][:75]} | R$ {float(product['preco_valor']):.2f}"
            for product in products[:10]
        ).replace(".", ",")
        if not messagebox.askyesno(
            "Confirmar envio",
            f"Enviar {len(products)} oferta(s) pelo WhatsApp?\n\n{summary}",
        ):
            return

        self.sending = True
        self.send_button.configure(state="disabled", text="Enviando...")
        worker = threading.Thread(
            target=self._send_worker,
            args=(products, category_key),
            daemon=True,
        )
        worker.start()

    def _send_worker(self, products, category_key):

        sent = []
        errors = []

        for product in products:
            try:
                if category_key:
                    product["categoria_manual"] = category_key
                if self.database.produto_ja_notificado(
                    product["link"],
                    product["loja"],
                    product["titulo"],
                ):
                    errors.append(f"{product['titulo'][:45]}: ja enviado")
                    continue
                if not self.notifier.send_whatsapp_alerts([product]):
                    errors.append(f"{product['titulo'][:45]}: envio bloqueado")
                    continue
                self.notifier.record_deliveries(
                    self.database,
                    [product],
                    ["WhatsApp"],
                )
                self.database.marcar_notificacao_manual(
                    product["link"],
                    product["loja"],
                    product["titulo"],
                )
                sent.append(product["titulo"])
            except Exception as error:
                errors.append(f"{product['titulo'][:45]}: {error}")

        self.after(0, lambda: self._finish_send(sent, errors))

    def _finish_send(self, sent, errors):

        self.sending = False
        self.send_button.configure(state="normal", text="Enviar selecionados")

        if sent:
            messagebox.showinfo(
                "Envio concluido",
                f"{len(sent)} oferta(s) enviada(s) com sucesso.",
            )
        if errors:
            messagebox.showwarning(
                "Itens nao enviados",
                "\n".join(errors[:8]),
            )

        self.carregar()
