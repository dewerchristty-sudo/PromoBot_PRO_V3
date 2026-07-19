import customtkinter as ctk
from tkinter import messagebox

from src.core.notifier import Notifier


class GroupsPage(ctk.CTkFrame):

    LABELS = {
        "mamae_bebe": "Mamãe e Bebê",
        "casa_enxoval": "Casa e Enxoval",
        "eletrodomesticos": "Eletrodomésticos",
        "smartphones_tecnologia": "Smartphones e Tecnologia",
        "beleza_perfumaria": "Beleza e Perfumaria",
        "limpeza_utilidades": "Limpeza e Utilidades",
    }

    def __init__(self, master, database):
        super().__init__(master)
        self.database = database
        self.notifier = Notifier(database)
        self.products_by_label = {}
        self.create_interface()
        self.load_all()

    def create_interface(self):
        ctk.CTkLabel(
            self, text="Grupos & Categorias", font=("Arial", 30, "bold")
        ).pack(pady=(16, 8))

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        for name in ("Sem categoria", "Palavras-chave", "Testar oferta", "Relatórios"):
            tabs.add(name)

        queue = tabs.tab("Sem categoria")
        self.queue_status = ctk.CTkLabel(queue, text="", anchor="w")
        self.queue_status.pack(fill="x", padx=12, pady=(12, 5))
        self.queue_text = ctk.CTkTextbox(queue)
        self.queue_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        keywords = tabs.tab("Palavras-chave")
        self.category_menu = ctk.CTkOptionMenu(
            keywords, values=list(self.LABELS.values()), command=self.load_keywords
        )
        self.category_menu.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(
            keywords,
            text="Separe as palavras e expressões por vírgula.",
            anchor="w",
        ).pack(fill="x", padx=14)
        self.keywords_text = ctk.CTkTextbox(keywords, height=300)
        self.keywords_text.pack(fill="both", expand=True, padx=14, pady=8)
        ctk.CTkButton(
            keywords, text="Salvar palavras-chave", command=self.save_keywords
        ).pack(pady=(0, 14))

        testing = tabs.tab("Testar oferta")
        self.product_menu = ctk.CTkOptionMenu(testing, values=["Carregando..."])
        self.product_menu.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkButton(
            testing, text="Validar oferta antes de publicar", command=self.test_offer
        ).pack(pady=8)
        ctk.CTkButton(
            testing,
            text="Enviar teste controlado para o grupo",
            fg_color="#9a6700",
            hover_color="#7a5200",
            command=self.send_controlled_test,
        ).pack(pady=(0, 8))
        self.test_result = ctk.CTkTextbox(testing)
        self.test_result.pack(fill="both", expand=True, padx=14, pady=(8, 14))

        report = tabs.tab("Relatórios")
        metrics = ctk.CTkFrame(report, fg_color="transparent")
        metrics.pack(fill="x", padx=12, pady=(12, 4))
        self.metrics_group = ctk.CTkOptionMenu(metrics, values=list(self.LABELS.values()))
        self.metrics_group.pack(side="left", padx=(0, 6))
        self.clicks_entry = ctk.CTkEntry(metrics, width=90, placeholder_text="Cliques")
        self.clicks_entry.pack(side="left", padx=3)
        self.sales_entry = ctk.CTkEntry(metrics, width=90, placeholder_text="Vendas")
        self.sales_entry.pack(side="left", padx=3)
        self.commission_entry = ctk.CTkEntry(metrics, width=110, placeholder_text="Comissão R$")
        self.commission_entry.pack(side="left", padx=3)
        ctk.CTkButton(metrics, text="Registrar", width=100, command=self.save_metrics).pack(side="left", padx=6)
        ctk.CTkButton(
            report, text="Atualizar relatório", command=self.load_report
        ).pack(pady=5)
        self.report_text = ctk.CTkTextbox(report)
        self.report_text.pack(fill="both", expand=True, padx=12, pady=(5, 12))

    def category_key(self):
        selected = self.category_menu.get()
        return next(key for key, label in self.LABELS.items() if label == selected)

    def load_all(self):
        self.load_queue()
        self.load_keywords()
        self.load_products()
        self.load_report()

    def load_queue(self):
        products = self.database.listar_produtos()[:500]
        pending = [p for p in products if not self.notifier.whatsapp_category(p)]
        self.queue_status.configure(
            text=f"Produtos recentes sem categoria segura: {len(pending)}"
        )
        self.queue_text.delete("1.0", "end")
        if not pending:
            self.queue_text.insert("end", "Nenhum produto sem categoria.")
            return
        for product in pending:
            self.queue_text.insert(
                "end",
                f"#{product['id']} | {product['loja']} | R$ {product['preco']}\n"
                f"{product['titulo']}\n{product['link']}\n"
                "------------------------------------------------------------\n",
            )

    def current_keywords(self, category):
        custom = self.database.listar_palavras_categorias().get(category)
        return custom or list(self.notifier.WHATSAPP_CATEGORY_KEYWORDS[category])

    def load_keywords(self, _value=None):
        category = self.category_key()
        self.keywords_text.delete("1.0", "end")
        self.keywords_text.insert("end", ", ".join(self.current_keywords(category)))

    def save_keywords(self):
        category = self.category_key()
        words = [w.strip() for w in self.keywords_text.get("1.0", "end").split(",") if w.strip()]
        if not words:
            messagebox.showerror("Categorias", "Informe pelo menos uma palavra-chave.")
            return
        self.database.salvar_palavras_categoria(category, ", ".join(dict.fromkeys(words)))
        self.load_queue()
        messagebox.showinfo("Categorias", "Palavras-chave salvas e classificação atualizada.")

    def load_products(self):
        products = self.database.listar_produtos()[:300]
        self.products_by_label = {
            f"#{p['id']} | {p['loja']} | {p['titulo'][:90]}": p for p in products
        }
        labels = list(self.products_by_label) or ["Nenhum produto disponível"]
        self.product_menu.configure(values=labels)
        self.product_menu.set(labels[0])

    def test_offer(self):
        product = self.products_by_label.get(self.product_menu.get())
        if not product:
            return
        category = self.notifier.whatsapp_category(product)
        groups = self.notifier.whatsapp_recipients_for_alert(product)
        quality, stale, low = self.notifier.partition_offer_quality([product])
        affiliate, blocked = self.notifier.partition_affiliate_ready(quality)
        image_ok = str(product["imagem"] or "").startswith("http")
        duplicate = self.database.produto_ja_notificado(
            product["link"], product["loja"], product["titulo"]
        )
        checks = [
            ("Categoria", self.LABELS.get(category, "NÃO IDENTIFICADA"), bool(category)),
            ("Grupo de destino", groups[0] if groups else "NÃO CONFIGURADO", bool(groups)),
            ("Imagem", "válida" if image_ok else "inválida", image_ok),
            ("Validade", "válida" if not stale else "vencida", not stale),
            ("Desconto", "aprovado" if not low else "insuficiente", not low),
            ("Link afiliado", "validado" if affiliate else "pendente", not blocked),
            ("Repetição", "já notificado" if duplicate else "novo", not duplicate),
        ]
        approved = all(item[2] for item in checks)
        self.test_result.delete("1.0", "end")
        self.test_result.insert("end", "APROVADA PARA ENVIO\n\n" if approved else "ENVIO BLOQUEADO\n\n")
        for label, value, ok in checks:
            self.test_result.insert("end", f"{'OK' if ok else 'ATENÇÃO'} | {label}: {value}\n")
        self.test_result.insert("end", "\nPrévia:\n\n" + self.notifier.format_alert(product))

    def send_controlled_test(self):
        product = self.products_by_label.get(self.product_menu.get())
        if not product:
            messagebox.showerror("Teste controlado", "Selecione um produto.")
            return

        category = self.notifier.whatsapp_category(product)
        group = self.notifier.whatsapp_recipients_for_alert(product)
        label = self.LABELS.get(category, "categoria nao identificada")
        if len(group) != 1:
            messagebox.showerror(
                "Teste controlado",
                "O produto nao possui um unico grupo de destino configurado.",
            )
            return

        confirmed = messagebox.askyesno(
            "Confirmar teste controlado",
            f"Enviar 1 mensagem marcada como TESTE para o grupo {label}?",
        )
        if not confirmed:
            return

        result = self.notifier.send_test_alert(product)
        if result.startswith("Teste enviado"):
            messagebox.showinfo("Teste controlado", result)
            self.load_report()
        else:
            messagebox.showerror("Teste controlado", result)

    def load_report(self):
        self.report_text.delete("1.0", "end")
        rows = self.database.relatorio_envios_por_destino(30)
        metrics = self.database.relatorio_metricas_grupos(30)
        reverse = {group: self.LABELS[key] for key, group in self.notifier.whatsapp_category_groups().items()}
        self.report_text.insert("end", "Desempenho dos últimos 30 dias\n\n")
        if not rows:
            self.report_text.insert("end", "Nenhum envio registrado por grupo ainda.")
        for row in rows:
            name = reverse.get(row["destino"], row["destino"])
            performance = metrics.get(row["destino"])
            clicks = performance["cliques"] if performance else 0
            sales = performance["vendas"] if performance else 0
            commission = performance["comissao"] if performance else 0
            self.report_text.insert(
                "end", f"{name}\nEnvios: {row['total']} | Produtos: {row['produtos']} | "
                f"Cliques: {clicks} | Vendas: {sales} | Comissão: R$ {commission:.2f}\n"
                f"Último envio: {row['ultimo_envio']}\n{'-' * 60}\n"
            )
        self.report_text.insert("end", "\nHistórico recente por grupo\n\n")
        for delivery in self.database.listar_historico_envios(50):
            name = reverse.get(delivery["destino"], delivery["destino"])
            self.report_text.insert(
                "end", f"{delivery['data']} | {name} | {delivery['loja']}\n"
                f"{delivery['titulo']}\n{'-' * 60}\n"
            )

    def save_metrics(self):
        try:
            label = self.metrics_group.get()
            category = next(key for key, value in self.LABELS.items() if value == label)
            destination = self.notifier.whatsapp_category_groups()[category]
            clicks = int(self.clicks_entry.get() or 0)
            sales = int(self.sales_entry.get() or 0)
            commission = float((self.commission_entry.get() or "0").replace(",", "."))
            if min(clicks, sales, commission) < 0:
                raise ValueError
            self.database.registrar_metricas_grupo(destination, clicks, sales, commission)
        except (ValueError, KeyError):
            messagebox.showerror("Relatórios", "Informe números válidos e não negativos.")
            return
        for entry in (self.clicks_entry, self.sales_entry, self.commission_entry):
            entry.delete(0, "end")
        self.load_report()
        messagebox.showinfo("Relatórios", "Resultados registrados.")
