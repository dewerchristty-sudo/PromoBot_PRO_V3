import threading
from datetime import datetime, timedelta
from tkinter import messagebox

import customtkinter as ctk

from src.core.notifier import Notifier
from src.scraper import Parser


class DailyDealsPage(ctk.CTkFrame):
    """Vitrine viva de ofertas recentes e promocoes detectadas."""

    REFRESH_SECONDS = 60
    CATEGORY_LABELS = {
        "Todas as categorias": "",
        "Mamae e Bebe": "mamae_bebe",
        "Casa e Enxoval": "casa_enxoval",
        "Eletrodomesticos": "eletrodomesticos",
        "Smartphones e Tecnologia": "smartphones_tecnologia",
        "Beleza e Perfumaria": "beleza_perfumaria",
        "Limpeza e Utilidades": "limpeza_utilidades",
    }

    def __init__(self, master, database, monitor_runner):
        super().__init__(master)
        self.database = database
        self.monitor_runner = monitor_runner
        self.notifier = Notifier(database)
        self.selected_category = ""
        self.selection_vars = {"daily": {}, "promotions": {}}
        self.products_by_id = {}
        self.rechecking = False
        self.seconds_to_refresh = self.REFRESH_SECONDS
        self.create_interface()
        self.refresh()
        self.after(1000, self.tick)

    def create_interface(self):
        ctk.CTkLabel(
            self, text="Ofertas do Dia", font=("Arial", 30, "bold")
        ).pack(pady=(16, 5))
        ctk.CTkLabel(
            self,
            text=(
                "Vitrine atualizada automaticamente. Ofertas vencidas deixam "
                "de aparecer quando nao sao confirmadas pelas novas coletas."
            ),
            font=("Arial", 13),
        ).pack(pady=(0, 10))

        toolbar = ctk.CTkFrame(self)
        toolbar.pack(fill="x", padx=18)
        self.category_menu = ctk.CTkOptionMenu(
            toolbar,
            values=list(self.CATEGORY_LABELS),
            command=self.change_category,
            width=230,
        )
        self.category_menu.pack(side="left", padx=(10, 6), pady=9)
        self.category_menu.set("Todas as categorias")
        ctk.CTkButton(
            toolbar, text="Atualizar tela", width=115, command=self.refresh
        ).pack(side="left", padx=6, pady=9)
        self.recheck_button = ctk.CTkButton(
            toolbar,
            text="Reconsultar lojas",
            width=140,
            command=self.recheck_stores,
        )
        self.recheck_button.pack(side="left", padx=6, pady=9)
        self.status = ctk.CTkLabel(toolbar, text="", anchor="e")
        self.status.pack(side="right", fill="x", expand=True, padx=10)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(8, 16))
        self.frames = {}
        self.count_labels = {}
        for mode, title in (
            ("daily", "Ofertas do Dia"),
            ("promotions", "Promocoes"),
        ):
            tab = self.tabs.add(title)
            actions = ctk.CTkFrame(tab)
            actions.pack(fill="x", padx=8, pady=(8, 0))
            self.count_labels[mode] = ctk.CTkLabel(actions, text="", anchor="w")
            self.count_labels[mode].pack(
                side="left", fill="x", expand=True, padx=8, pady=7
            )
            ctk.CTkButton(
                actions,
                text="Selecionar todas",
                width=120,
                command=lambda selected_mode=mode: self.select_all(
                    selected_mode, True
                ),
            ).pack(side="left", padx=4, pady=7)
            ctk.CTkButton(
                actions,
                text="Limpar",
                width=85,
                command=lambda selected_mode=mode: self.select_all(
                    selected_mode, False
                ),
            ).pack(side="left", padx=4, pady=7)
            ctk.CTkButton(
                actions,
                text="Enviar selecionadas",
                width=145,
                fg_color="#15803d",
                hover_color="#166534",
                command=lambda selected_mode=mode: self.send_selected(
                    selected_mode
                ),
            ).pack(side="right", padx=8, pady=7)

            frame = ctk.CTkScrollableFrame(tab)
            frame.pack(fill="both", expand=True, padx=8, pady=8)
            frame.grid_columnconfigure(1, weight=1)
            self.frames[mode] = frame

    @staticmethod
    def parse_datetime(value):
        try:
            return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def is_recent(cls, product, now, max_age_hours):
        collected = cls.parse_datetime(product.get("data"))
        if not collected:
            return False
        return collected >= now - timedelta(hours=max(max_age_hours, 1))

    @staticmethod
    def discount_percent(product):
        current = float(product.get("preco_valor") or 0)
        highest = float(product.get("maior_preco") or 0)
        if current <= 0 or highest <= current:
            return 0.0
        return ((highest - current) / highest) * 100

    def eligible_products(self, mode):
        now = datetime.utcnow()
        max_age = max(
            self.notifier.float_env("MAX_OFFER_AGE_HOURS"),
            1,
        )
        products = []
        ignored = self.database.listar_links_ofertas_ignoradas()

        for row in self.database.listar_produtos_marketplace(
            somente_promocoes=(mode == "promotions")
        ):
            product = dict(row)
            category = self.notifier.whatsapp_category(product)
            if self.selected_category and category != self.selected_category:
                continue
            if not category:
                continue
            product["categoria_manual"] = category
            if not self.is_recent(product, now, max_age):
                continue
            if str(product.get("link") or "") in ignored:
                continue
            if not str(product.get("imagem") or "").startswith("http"):
                continue
            ready, _blocked = self.notifier.partition_affiliate_ready([product])
            if not ready:
                continue
            discount = self.discount_percent(product)
            if mode == "daily" and discount <= 0:
                continue
            if mode == "promotions" and not int(product.get("promocao") or 0):
                continue
            if self.database.produto_ja_notificado(
                product["link"], product["loja"], product["titulo"]
            ):
                continue
            products.append((discount, product))

        products.sort(
            key=lambda item: (
                -item[0],
                -self.parse_datetime(item[1].get("data")).timestamp(),
                float(item[1].get("preco_valor") or 0),
            )
        )
        return products[:100]

    def change_category(self, label):
        self.selected_category = self.CATEGORY_LABELS.get(label, "")
        self.refresh()

    def refresh(self):
        self.seconds_to_refresh = self.REFRESH_SECONDS
        self.products_by_id = {}
        for mode in self.frames:
            products = self.eligible_products(mode)
            self.render_mode(mode, products)
        self.update_status()

    def render_mode(self, mode, products):
        frame = self.frames[mode]
        for widget in frame.winfo_children():
            widget.destroy()
        self.selection_vars[mode] = {}
        self.count_labels[mode].configure(
            text=f"{len(products)} oferta(s) ativa(s)"
        )
        if not products:
            ctk.CTkLabel(
                frame,
                text=(
                    "Nenhuma oferta ativa e pronta nesta categoria.\n"
                    "Execute uma nova coleta ou valide os links afiliados pendentes."
                ),
                justify="center",
            ).grid(row=0, column=0, columnspan=2, padx=20, pady=35)
            return

        for row_index, (discount, product) in enumerate(products):
            product_id = int(product["id"])
            self.products_by_id[product_id] = product
            selected = ctk.BooleanVar(value=False)
            self.selection_vars[mode][product_id] = selected
            ctk.CTkCheckBox(
                frame, text="", width=28, variable=selected
            ).grid(row=row_index, column=0, padx=(8, 2), pady=7, sticky="n")
            category = self.notifier.whatsapp_category(product)
            category_label = next(
                (
                    label
                    for label, key in self.CATEGORY_LABELS.items()
                    if key == category
                ),
                "Sem categoria",
            )
            highest = float(
                product.get("maior_preco") or product.get("preco_valor") or 0
            )
            collected = self.parse_datetime(product.get("data"))
            time_text = collected.strftime("%d/%m %H:%M") if collected else "-"
            text = (
                f"{product['titulo']}\n"
                f"{product['loja']} | "
                f"{Parser.format_brl(product['preco_valor'], True)} "
                f"| antes {Parser.format_brl(highest, True)} "
                f"| {discount:.1f}% OFF\n"
                f"{category_label} | confirmada em {time_text} | ATIVA"
            ).replace(".", ",")
            ctk.CTkLabel(
                frame,
                text=text,
                anchor="w",
                justify="left",
                wraplength=900,
            ).grid(
                row=row_index,
                column=1,
                padx=(4, 10),
                pady=7,
                sticky="ew",
            )

    def select_all(self, mode, selected):
        for variable in self.selection_vars[mode].values():
            variable.set(bool(selected))

    def selected_products(self, mode):
        return [
            dict(self.products_by_id[product_id])
            for product_id, variable in self.selection_vars[mode].items()
            if variable.get()
        ]

    def send_selected(self, mode):
        products = self.selected_products(mode)
        if not products:
            messagebox.showwarning(
                "Ofertas do Dia", "Selecione pelo menos uma oferta."
            )
            return
        unrouted = [
            product["titulo"]
            for product in products
            if not self.notifier.whatsapp_recipients_for_alert(product)
        ]
        if unrouted:
            messagebox.showwarning(
                "Grupo nao configurado",
                "Uma ou mais ofertas nao possuem grupo de destino configurado.",
            )
            return
        if not messagebox.askyesno(
            "Confirmar envio",
            f"Enviar {len(products)} oferta(s) para os grupos correspondentes?",
        ):
            return
        threading.Thread(
            target=self._send_worker,
            args=(products,),
            daemon=True,
        ).start()

    def _send_worker(self, products):
        sent = 0
        errors = []
        for product in products:
            try:
                if self.notifier.send_whatsapp_alerts([product]):
                    self.notifier.record_deliveries(
                        self.database, [product], ["WhatsApp"]
                    )
                    self.database.marcar_notificacao_manual(
                        product["link"], product["loja"], product["titulo"]
                    )
                    sent += 1
                else:
                    errors.append(product["titulo"][:55])
            except Exception as error:
                errors.append(f"{product['titulo'][:40]}: {error}")
        self.after(0, lambda: self._finish_send(sent, errors))

    def _finish_send(self, sent, errors):
        if sent:
            messagebox.showinfo(
                "Envio concluido", f"{sent} oferta(s) enviada(s) com sucesso."
            )
        if errors:
            messagebox.showwarning(
                "Itens nao enviados", "\n".join(errors[:8])
            )
        self.refresh()

    def recheck_stores(self):
        if self.rechecking:
            return
        active = self.database.listar_monitoramentos(somente_ativos=True)
        if not active:
            messagebox.showinfo(
                "Reconsultar lojas",
                "Cadastre e ative monitoramentos antes de reconsultar as lojas.",
            )
            return
        self.rechecking = True
        self.recheck_button.configure(state="disabled", text="Consultando...")
        threading.Thread(target=self._recheck_worker, daemon=True).start()

    def _recheck_worker(self):
        try:
            total = self.monitor_runner.run_once()
            result = f"Coleta concluida: {total} produto(s) encontrados."
        except Exception as error:
            result = f"Falha na coleta: {error}"
        self.after(0, lambda: self._finish_recheck(result))

    def _finish_recheck(self, result):
        self.rechecking = False
        self.recheck_button.configure(state="normal", text="Reconsultar lojas")
        self.refresh()
        messagebox.showinfo("Reconsultar lojas", result)

    def tick(self):
        if not self.winfo_exists():
            return
        self.seconds_to_refresh -= 1
        if self.seconds_to_refresh <= 0:
            self.refresh()
        else:
            self.update_status()
        self.after(1000, self.tick)

    def update_status(self):
        state = "ativo" if self.monitor_runner.running else "parado"
        self.status.configure(
            text=(
                f"Monitor {state} | atualizacao da tela em "
                f"{self.seconds_to_refresh}s"
            )
        )
