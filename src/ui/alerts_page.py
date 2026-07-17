from tkinter import messagebox

import customtkinter as ctk

from src.core.notifier import Notifier


class AlertsPage(ctk.CTkFrame):

    def __init__(self, master, database):
        super().__init__(master)

        self.database = database
        self.alertas = []
        self.notifier = Notifier()

        self.criar_interface()
        self.carregar()

    def criar_interface(self):

        ctk.CTkLabel(
            self,
            text="Alertas de Preco",
            font=("Arial", 30, "bold")
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            self,
            text="Use preco em branco para receber somente promocoes encontradas nas lojas.",
            font=("Arial", 14)
        ).pack(pady=(0, 18))

        form = ctk.CTkFrame(self)
        form.pack(fill="x", padx=20)
        form.grid_columnconfigure(0, weight=1)

        self.termo = ctk.CTkEntry(
            form,
            placeholder_text="Produto ou palavra-chave (opcional)...",
            height=38
        )
        self.termo.grid(row=0, column=0, sticky="ew", padx=(10, 8), pady=10)

        self.preco = ctk.CTkEntry(
            form,
            placeholder_text="Preco alvo ou vazio",
            width=120,
            height=38
        )
        self.preco.grid(row=0, column=1, padx=(0, 8), pady=10)

        ctk.CTkButton(
            form,
            text="Criar alerta",
            width=120,
            command=self.criar_alerta
        ).grid(row=0, column=2, padx=(0, 8), pady=10)

        ctk.CTkButton(
            form,
            text="Atualizar",
            width=100,
            command=self.carregar
        ).grid(row=0, column=3, padx=(0, 10), pady=10)

        self.status = ctk.CTkLabel(self, text="", anchor="w")
        self.status.pack(fill="x", padx=20, pady=(10, 0))

        self.lista = ctk.CTkTextbox(self)
        self.lista.pack(fill="both", expand=True, padx=20, pady=20)

        botoes = ctk.CTkFrame(self)
        botoes.pack(fill="x", padx=20, pady=(0, 20))

        self.id_entry = ctk.CTkEntry(
            botoes,
            placeholder_text="ID do alerta",
            width=110,
            height=36
        )
        self.id_entry.pack(side="left", padx=(10, 8), pady=10)

        ctk.CTkButton(
            botoes,
            text="Ativar/pausar",
            width=120,
            command=self.alternar_alerta
        ).pack(side="left", padx=(0, 8), pady=10)

        ctk.CTkButton(
            botoes,
            text="Remover",
            width=100,
            fg_color="#8a1f1f",
            hover_color="#6f1717",
            command=self.remover_alerta
        ).pack(side="left", padx=(0, 8), pady=10)

        ctk.CTkButton(
            botoes,
            text="Notificar agora",
            width=130,
            command=self.notificar_agora
        ).pack(side="left", padx=(0, 8), pady=10)

    def criar_alerta(self):

        try:

            self.database.criar_alerta(
                self.termo.get(),
                self.preco.get()
            )

        except ValueError:

            messagebox.showerror(
                "Alerta invalido",
                "Informe um preco valido ou deixe em branco para promocoes."
            )
            return

        self.termo.delete(0, "end")
        self.preco.delete(0, "end")
        self.carregar()

    def carregar(self):

        self.alertas = self.database.listar_alertas()
        disparos = self.database.alertas_disparados()

        self.status.configure(
            text=f"{len(self.alertas)} alerta(s) cadastrado(s) | {len(disparos)} disparo(s)"
        )

        self.lista.delete("1.0", "end")
        self.lista.insert("end", "Alertas cadastrados\n")
        self.lista.insert("end", "==============================\n\n")

        if not self.alertas:
            self.lista.insert("end", "Nenhum alerta cadastrado.\n")

        for alerta in self.alertas:
            status = "ativo" if alerta["ativo"] else "pausado"
            termo = alerta["termo"] or "todas as promocoes"
            alvo = (
                f"ate R$ {alerta['preco_alvo']:.2f}"
                if alerta["preco_alvo"] is not None
                else "somente promocoes"
            )
            self.lista.insert(
                "end",
                f"ID {alerta['id']} | {status} | {termo} | {alvo}\n"
            )

        self.lista.insert("end", "\nProdutos que bateram alerta\n")
        self.lista.insert("end", "==============================\n\n")

        if not disparos:
            self.lista.insert("end", "Nenhum produto bateu alerta ainda.\n")
            return

        for item in disparos:
            termo = item["termo"] or "promocoes"
            alvo = (
                f"alvo R$ {item['preco_alvo']:.2f}"
                if item["preco_alvo"] is not None
                else "promocao"
            )
            self.lista.insert(
                "end",
                f"[{termo}] {alvo}\n"
                f"{item['loja']} | R$ {item['preco']} | {item['titulo']}\n"
                f"{item['link']}\n"
                "------------------------------------------------------------\n"
            )

    def alerta_id(self):

        try:
            return int(self.id_entry.get().strip())
        except ValueError:
            messagebox.showerror("ID invalido", "Informe o ID numerico do alerta.")
            return None

    def alternar_alerta(self):

        alerta_id = self.alerta_id()

        if alerta_id is None:
            return

        self.database.alternar_alerta(alerta_id)
        self.carregar()

    def remover_alerta(self):

        alerta_id = self.alerta_id()

        if alerta_id is None:
            return

        confirmado = messagebox.askyesno(
            "Remover alerta",
            f"Deseja remover o alerta ID {alerta_id}?"
        )

        if not confirmado:
            return

        self.database.remover_alerta(alerta_id)
        self.carregar()

    def notificar_agora(self):

        disparos = self.database.alertas_disparados()
        resultado = self.notifier.send_alerts(disparos)

        messagebox.showinfo("Notificacoes", resultado)
