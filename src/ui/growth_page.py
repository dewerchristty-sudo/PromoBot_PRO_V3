import csv
import threading
import unicodedata
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from src.core.notifier import Notifier


class GrowthPage(ctk.CTkFrame):

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
        self.offers_by_label = {}
        self.create_interface()
        self.load_invite()
        self.load_offers_async()
        self.load_calendar()
        self.load_results()

    def create_interface(self):
        ctk.CTkLabel(self, text="Crescimento", font=("Arial", 30, "bold")).pack(
            pady=(16, 4)
        )
        ctk.CTkLabel(
            self,
            text="Construa audiência com poucas ofertas boas, conteúdo útil e resultados medidos.",
        ).pack(pady=(0, 8))
        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=20, pady=(0, 18))
        for name in ("Hoje", "Calendário", "Resultados"):
            tabs.add(name)

        today = tabs.tab("Hoje")
        invite = ctk.CTkFrame(today)
        invite.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(invite, text="Link de convite do seu grupo", anchor="w").pack(
            fill="x", padx=12, pady=(10, 4)
        )
        row = ctk.CTkFrame(invite, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 10))
        self.invite_entry = ctk.CTkEntry(
            row, placeholder_text="Cole o link de convite autorizado do WhatsApp"
        )
        self.invite_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(row, text="Salvar", width=90, command=self.save_invite).pack(
            side="left"
        )

        offer = ctk.CTkFrame(today)
        offer.pack(fill="both", expand=True, padx=12, pady=6)
        ctk.CTkLabel(
            offer, text="Oferta do dia", font=("Arial", 16, "bold"), anchor="w"
        ).pack(fill="x", padx=12, pady=(10, 5))
        self.offer_status = ctk.CTkLabel(offer, text="Selecionando ofertas...", anchor="w")
        self.offer_status.pack(fill="x", padx=12, pady=(0, 5))
        self.offer_menu = ctk.CTkOptionMenu(
            offer, values=["Carregando..."], command=lambda _value: self.generate_content()
        )
        self.offer_menu.pack(fill="x", padx=12, pady=(0, 8))
        actions = ctk.CTkFrame(offer, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkButton(
            actions, text="Texto para Status", command=lambda: self.generate_content("status")
        ).pack(side="left", padx=(0, 5))
        ctk.CTkButton(
            actions, text="Legenda social", command=lambda: self.generate_content("social")
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            actions, text="Convite do grupo", command=lambda: self.generate_content("convite")
        ).pack(side="left", padx=5)
        ctk.CTkButton(actions, text="Copiar texto", command=self.copy_content).pack(
            side="right", padx=(5, 0)
        )
        self.content_text = ctk.CTkTextbox(offer, height=180)
        self.content_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        calendar = tabs.tab("Calendário")
        beginner = ctk.CTkFrame(calendar)
        beginner.pack(fill="x", padx=12, pady=(12, 6))
        self.beginner_mode = ctk.CTkCheckBox(
            beginner,
            text="Modo iniciante: no máximo 2 ou 3 ofertas boas por dia",
            command=self.save_beginner_mode,
        )
        self.beginner_mode.pack(anchor="w", padx=12, pady=12)
        self.calendar_text = ctk.CTkTextbox(calendar)
        self.calendar_text.pack(fill="both", expand=True, padx=12, pady=(6, 12))

        results = tabs.tab("Resultados")
        controls = ctk.CTkFrame(results, fg_color="transparent")
        controls.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkButton(controls, text="Atualizar painel", command=self.load_results).pack(
            side="left", padx=(0, 5)
        )
        ctk.CTkButton(controls, text="Baixar modelo CSV", command=self.export_template).pack(
            side="left", padx=5
        )
        ctk.CTkButton(controls, text="Importar CSV/Excel", command=self.import_report).pack(
            side="left", padx=5
        )
        self.results_text = ctk.CTkTextbox(results)
        self.results_text.pack(fill="both", expand=True, padx=12, pady=(6, 12))

    def load_invite(self):
        value = self.database.obter_configuracao_app("growth_invite_link", "")
        self.invite_entry.delete(0, "end")
        self.invite_entry.insert(0, value)
        enabled = self.database.obter_configuracao_app("growth_beginner_mode", "1") != "0"
        if enabled:
            self.beginner_mode.select()
        else:
            self.beginner_mode.deselect()

    def save_invite(self):
        link = self.invite_entry.get().strip()
        if link and not link.startswith(("https://chat.whatsapp.com/", "http://", "https://")):
            messagebox.showerror("Convite", "Informe um link de convite válido.")
            return
        self.database.salvar_configuracao_app("growth_invite_link", link)
        messagebox.showinfo("Convite", "Link de convite salvo.")

    def save_beginner_mode(self):
        self.database.salvar_configuracao_app(
            "growth_beginner_mode", "1" if self.beginner_mode.get() else "0"
        )
        self.load_calendar()

    def load_offers_async(self):
        self.offer_menu.configure(state="disabled")

        def worker():
            try:
                products = self.database.listar_produtos_marketplace(True)
                quality, _stale, _low = self.notifier.partition_offer_quality(products)
                ranked, _without_image = self.notifier.prioritize_affiliate_queue(quality)
                ready = [
                    product for product in ranked
                    if self.notifier.has_affiliate_link(product)
                    and str(product["imagem"] or "").startswith("http")
                    and self.notifier.whatsapp_category(product)
                ][:20]
                self.after(0, lambda: self._offers_loaded(ready))
            except Exception as error:
                message = str(error)
                self.after(0, lambda: self.offer_status.configure(text=f"Falha: {message}"))

        threading.Thread(target=worker, daemon=True).start()

    def _offers_loaded(self, offers):
        self.offers_by_label = {
            f"{p['loja']} | {p['titulo'][:85]} | R$ {p['preco']}": p for p in offers
        }
        labels = list(self.offers_by_label) or ["Nenhuma oferta pronta no momento"]
        self.offer_menu.configure(values=labels, state="normal")
        self.offer_menu.set(labels[0])
        self.offer_status.configure(
            text=f"{len(offers)} oferta(s) recente(s), vantajosa(s) e pronta(s)."
        )
        self.generate_content("status")

    def selected_offer(self):
        return self.offers_by_label.get(self.offer_menu.get())

    def generate_content(self, kind="status"):
        product = self.selected_offer()
        invite = self.invite_entry.get().strip()
        if kind == "convite":
            text = (
                "Criei um grupo gratuito para compartilhar ofertas realmente boas, "
                "com preços conferidos e sem spam. Entre pelo link:\n" + (invite or "[SALVE O LINK DO GRUPO AQUI]")
            )
        elif not product:
            text = "Nenhuma oferta pronta. Corrija os links prioritários e tente novamente."
        else:
            title = str(product["titulo"] or "Produto em oferta")
            price = str(product["preco"] or "")
            link = self.notifier.affiliate_link(product)
            if kind == "social":
                text = (
                    f"Vale a pena conferir: {title}\n\n"
                    f"Oferta por R$ {price}. Preço sujeito a alteração pela loja.\n\n"
                    f"Confira aqui: {link}\n\n#ofertas #promoção #achadinhos\n"
                    "Link de afiliado: posso receber comissão sem custo adicional para você."
                )
            else:
                text = (
                    f"OFERTA DO DIA\n\n{title}\n\nPor R$ {price}\n\n"
                    f"Confira antes que o preço mude:\n{link}\n\n"
                    "Link de afiliado. A oferta pode terminar a qualquer momento."
                )
        self.content_text.delete("1.0", "end")
        self.content_text.insert("1.0", text)

    def copy_content(self):
        text = self.content_text.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Conteúdo", "Texto copiado.")

    def load_calendar(self):
        limit = "2 ou 3" if self.beginner_mode.get() else "até 5"
        plan = f"""PLANO SEMANAL PARA COMEÇAR

Todos os dias
- Publique no máximo {limit} ofertas realmente boas.
- Responda dúvidas e não adicione pessoas sem autorização.
- Informe que os links são de afiliado.

Segunda-feira — dica útil + oferta de casa/cozinha
Terça-feira — comparação de preços + oferta de tecnologia
Quarta-feira — produto que resolve um problema + limpeza/utilidades
Quinta-feira — demonstração curta + beleza ou cuidado pessoal
Sexta-feira — melhor desconto da semana
Sábado — enquete: qual produto as pessoas querem encontrar?
Domingo — resumo das melhores ofertas + convite para o grupo

Meta inicial: 20 participantes interessados, depois 50 e 100.
Não compre seguidores e não faça disparos para desconhecidos.
"""
        self.calendar_text.delete("1.0", "end")
        self.calendar_text.insert("1.0", plan)

    def load_results(self):
        rows = self.database.relatorio_envios_por_destino(30)
        metrics = self.database.relatorio_metricas_grupos(30)
        total_sends = sum(int(row["total"] or 0) for row in rows)
        clicks = sum(int(row["cliques"] or 0) for row in metrics.values())
        sales = sum(int(row["vendas"] or 0) for row in metrics.values())
        commission = sum(float(row["comissao"] or 0) for row in metrics.values())
        conversion = (sales / clicks * 100) if clicks else 0
        self.results_text.delete("1.0", "end")
        self.results_text.insert(
            "end",
            "RESULTADOS DOS ÚLTIMOS 30 DIAS\n\n"
            f"Envios: {total_sends}\nCliques registrados: {clicks}\n"
            f"Vendas: {sales}\nComissão: R$ {commission:.2f}\n"
            f"Conversão: {conversion:.2f}%\n\n",
        )
        if not metrics:
            self.results_text.insert(
                "end",
                "Ainda não existem resultados importados. Use o modelo CSV ou registre "
                "manualmente em Grupos & Categorias > Relatórios.\n\n"
                "Rastreamento automático de cliques exige um endereço público de redirecionamento; "
                "um link local não mede acessos feitos por outras pessoas.",
            )

    def export_template(self):
        path = filedialog.asksaveasfilename(
            title="Salvar modelo de resultados",
            defaultextension=".csv",
            filetypes=[("Arquivo CSV", "*.csv")],
            initialfile="resultados_afiliados.csv",
        )
        if not path:
            return
        with Path(path).open("w", newline="", encoding="utf-8-sig") as output:
            writer = csv.writer(output, delimiter=";")
            writer.writerow(["categoria", "cliques", "vendas", "comissao"])
            for label in self.LABELS.values():
                writer.writerow([label, 0, 0, "0,00"])
        messagebox.showinfo("Modelo", "Modelo CSV criado.")

    @staticmethod
    def _normalized(value):
        text = unicodedata.normalize("NFKD", str(value or ""))
        return "".join(char for char in text if not unicodedata.combining(char)).lower().strip()

    def import_report(self):
        path = filedialog.askopenfilename(
            title="Importar resultados",
            filetypes=[("CSV ou Excel", "*.csv *.xlsx *.xls")],
        )
        if not path:
            return
        try:
            if Path(path).suffix.lower() == ".csv":
                import pandas as pd
                frame = pd.read_csv(path, sep=None, engine="python")
            else:
                import pandas as pd
                frame = pd.read_excel(path)
            columns = {self._normalized(name): name for name in frame.columns}
            required = {"categoria", "cliques", "vendas", "comissao"}
            if not required <= set(columns):
                raise ValueError(
                    "O arquivo precisa das colunas: categoria, cliques, vendas e comissao. "
                    "Use o botão Baixar modelo CSV."
                )
            groups = self.notifier.whatsapp_category_groups()
            imported = 0
            label_keys = {self._normalized(label): key for key, label in self.LABELS.items()}
            for _, row in frame.iterrows():
                key = label_keys.get(self._normalized(row[columns["categoria"]]))
                destination = groups.get(key) if key else None
                if not destination:
                    continue
                clicks = int(float(row[columns["cliques"]] or 0))
                sales = int(float(row[columns["vendas"]] or 0))
                raw_commission = str(row[columns["comissao"]] or "0").replace("R$", "").strip()
                if "," in raw_commission and "." in raw_commission:
                    raw_commission = raw_commission.replace(".", "").replace(",", ".")
                else:
                    raw_commission = raw_commission.replace(",", ".")
                commission = float(raw_commission)
                if min(clicks, sales, commission) < 0:
                    raise ValueError("O relatório contém valores negativos.")
                if clicks or sales or commission:
                    self.database.registrar_metricas_grupo(destination, clicks, sales, commission)
                    imported += 1
            self.load_results()
            messagebox.showinfo("Importação", f"{imported} resultado(s) registrado(s).")
        except Exception as error:
            messagebox.showerror("Importar resultados", str(error))
