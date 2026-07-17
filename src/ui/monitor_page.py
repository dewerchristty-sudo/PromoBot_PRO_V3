import threading
from tkinter import messagebox

import customtkinter as ctk

from src.core.monitor import MonitorRunner
from src.core.store_manager import StoreManager


class MonitorPage(ctk.CTkFrame):

    def __init__(self, master, database, runner=None):
        super().__init__(master)

        self.database = database
        self.runner = runner or MonitorRunner(database)
        self.previous_progress_callback = self.runner.progress_callback
        self.runner.set_progress_callback(self.log_threadsafe)

        self.criar_interface()
        self.carregar()

    def criar_interface(self):

        ctk.CTkLabel(
            self,
            text="Monitoramento",
            font=("Arial", 30, "bold")
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            self,
            text="Agende buscas automaticas nas lojas confiaveis.",
            font=("Arial", 14)
        ).pack(pady=(0, 18))

        form = ctk.CTkFrame(self)
        form.pack(fill="x", padx=20)
        form.grid_columnconfigure(0, weight=1)

        self.termo = ctk.CTkEntry(
            form,
            placeholder_text="Produto para monitorar...",
            height=38
        )
        self.termo.grid(row=0, column=0, sticky="ew", padx=(10, 8), pady=10)

        self.intervalo = ctk.CTkEntry(
            form,
            placeholder_text="Minutos",
            width=100,
            height=38
        )
        self.intervalo.insert(0, "30")
        self.intervalo.grid(row=0, column=1, padx=(0, 8), pady=10)

        ctk.CTkButton(
            form,
            text="Adicionar",
            width=110,
            command=self.adicionar
        ).grid(row=0, column=2, padx=(0, 10), pady=10)

        botoes = ctk.CTkFrame(self)
        botoes.pack(fill="x", padx=20, pady=(10, 0))

        ctk.CTkButton(
            botoes,
            text="Iniciar",
            width=95,
            command=self.iniciar
        ).pack(side="left", padx=(10, 8), pady=10)

        ctk.CTkButton(
            botoes,
            text="Parar",
            width=95,
            command=self.parar
        ).pack(side="left", padx=(0, 8), pady=10)

        ctk.CTkButton(
            botoes,
            text="Executar agora",
            width=130,
            command=self.executar_agora
        ).pack(side="left", padx=(0, 8), pady=10)

        ctk.CTkButton(
            botoes,
            text="Categorias padrao",
            width=140,
            command=self.adicionar_padrao
        ).pack(side="left", padx=(0, 8), pady=10)

        self.id_entry = ctk.CTkEntry(
            botoes,
            placeholder_text="ID",
            width=70,
            height=36
        )
        self.id_entry.pack(side="left", padx=(14, 8), pady=10)

        ctk.CTkButton(
            botoes,
            text="Ativar/pausar",
            width=120,
            command=self.alternar
        ).pack(side="left", padx=(0, 8), pady=10)

        ctk.CTkButton(
            botoes,
            text="Remover",
            width=100,
            fg_color="#8a1f1f",
            hover_color="#6f1717",
            command=self.remover
        ).pack(side="left", padx=(0, 8), pady=10)

        self.status = ctk.CTkLabel(self, text="", anchor="w")
        self.status.pack(fill="x", padx=20, pady=(10, 0))

        self.lista = ctk.CTkTextbox(self)
        self.lista.pack(fill="both", expand=True, padx=20, pady=20)

    def adicionar(self):

        try:
            self.database.criar_monitoramento(
                self.termo.get(),
                self.intervalo.get(),
                ",".join(StoreManager.stable_store_names())
            )
        except ValueError:
            messagebox.showerror(
                "Intervalo invalido",
                "Informe um intervalo em minutos. Exemplo: 30"
            )
            return

        self.termo.delete(0, "end")
        self.carregar()

    def iniciar(self):

        self.runner.start()
        self.carregar()

    def parar(self):

        self.runner.stop()
        self.carregar()

    def executar_agora(self):

        self.status.configure(text="Executando monitoramento agora...")

        threading.Thread(
            target=self._executar_agora_thread,
            daemon=True
        ).start()

    def adicionar_padrao(self):

        try:
            criados = self.database.criar_monitoramentos_padrao(
                self.intervalo.get(),
                ",".join(StoreManager.stable_store_names())
            )
        except ValueError:
            messagebox.showerror(
                "Intervalo invalido",
                "Informe um intervalo em minutos. Exemplo: 60"
            )
            return

        messagebox.showinfo(
            "Categorias padrao",
            f"{criados} novo(s) monitoramento(s) criado(s)."
        )
        self.carregar()

    def _executar_agora_thread(self):

        total = self.runner.run_once()

        self.after(
            0,
            lambda: self.status.configure(
                text=f"Execucao manual concluida: {total} produto(s)."
            )
        )
        self.after(0, self.carregar)

    def carregar(self):

        monitoramentos = self.database.listar_monitoramentos()
        ativos = [item for item in monitoramentos if item["ativo"]]

        estado = "rodando" if self.runner.running else "parado"
        self.status.configure(
            text=f"Monitor {estado} | {len(ativos)} ativo(s)"
        )

        self.lista.delete("1.0", "end")

        if not monitoramentos:
            self.lista.insert(
                "end",
                "Nenhum monitoramento cadastrado.\n"
                "Adicione um termo para pesquisar automaticamente."
            )
            return

        for item in monitoramentos:

            status = "ativo" if item["ativo"] else "pausado"

            self.lista.insert(
                "end",
                f"ID {item['id']} | {status} | {item['termo']}\n"
                f"Intervalo.....: {item['intervalo_minutos']} minuto(s)\n"
                f"Lojas.........: {item['lojas']}\n"
                f"Ultima exec...: {item['ultima_execucao'] or 'nunca'}\n"
                f"Ultimo total..: {item['ultimo_total']}\n"
                "============================================================\n\n"
            )

    def monitoramento_id(self):

        try:
            return int(self.id_entry.get().strip())
        except ValueError:
            messagebox.showerror("ID invalido", "Informe o ID numerico.")
            return None

    def alternar(self):

        monitoramento_id = self.monitoramento_id()

        if monitoramento_id is None:
            return

        self.database.alternar_monitoramento(monitoramento_id)
        self.carregar()

    def remover(self):

        monitoramento_id = self.monitoramento_id()

        if monitoramento_id is None:
            return

        confirmado = messagebox.askyesno(
            "Remover monitoramento",
            f"Deseja remover o monitoramento ID {monitoramento_id}?"
        )

        if not confirmado:
            return

        self.database.remover_monitoramento(monitoramento_id)
        self.carregar()

    def log_threadsafe(self, texto):

        self.after(
            0,
            lambda: self.lista.insert("end", texto + "\n")
        )

    def destroy(self):

        if self.runner.progress_callback == self.log_threadsafe:
            self.runner.set_progress_callback(self.previous_progress_callback)

        super().destroy()
