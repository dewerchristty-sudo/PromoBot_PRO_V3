import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

from src.core.notifier import Notifier
from src.core.startup import configure_startup, startup_enabled


class SettingsPage(ctk.CTkFrame):

    def __init__(self, master, database):
        super().__init__(master)

        self.database = database
        self.notifier = Notifier(database)
        self.start_with_windows = tk.BooleanVar(value=startup_enabled())

        self.criar_interface()

    def criar_interface(self):

        ctk.CTkLabel(
            self,
            text="Configuracoes",
            font=("Arial", 30, "bold")
        ).pack(pady=(20, 15))

        painel = ctk.CTkFrame(self)
        painel.pack(fill="x", padx=20, pady=10)

        self.aparencia = ctk.CTkOptionMenu(
            painel,
            values=["Dark", "Light", "System"],
            command=self.alterar_tema
        )
        self.aparencia.set("Dark")

        ctk.CTkLabel(
            painel,
            text="Tema da interface",
            font=("Arial", 16, "bold")
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 6))

        self.aparencia.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 16))

        ctk.CTkSwitch(
            painel,
            text="Iniciar o PromoBot automaticamente com o Windows",
            variable=self.start_with_windows,
            command=self.toggle_startup,
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(0, 16))

        info = ctk.CTkTextbox(self, height=220)
        info.pack(fill="x", padx=20, pady=20)
        canais = self.notifier.configured_channels()
        canais_texto = ", ".join(canais) if canais else "nenhum canal configurado"
        grupos = self.notifier.whatsapp_category_groups()
        integridade = self.database.verificar_integridade()

        info.insert(
            "end",
            "Diagnostico local:\n"
            f"- Banco: {integridade}\n"
            f"- Produtos: {self.database.total_produtos()}\n"
            f"- Links afiliados: {self.database.total_links_afiliados()}\n"
            f"- Fila de recuperacao: {self.database.total_fila_notificacoes()}\n"
            f"- Grupos por categoria: {len(grupos)}/6\n\n"
            "Lojas principais:\n"
            "- Mercado Livre\n"
            "- Shopee (pode bloquear automacao em alguns ambientes)\n\n"
            "Lojas experimentais:\n"
            "- Amazon, Kabum, Terabyte, Pichau, Magalu, Casas Bahia e Americanas\n\n"
            "Banco de dados:\n"
            "- promobot.db\n\n"
            "Notificacoes:\n"
            f"- {canais_texto}\n"
            "- Envios automaticos respeitam o horario definido no .env\n"
            "- Testes controlados exigem confirmacao manual\n"
            "- Configure .env usando .env.example como modelo\n\n"
            "Backups futuros do .env ocultam credenciais automaticamente."
        )
        info.configure(state="disabled")

    def alterar_tema(self, tema):

        ctk.set_appearance_mode(tema.lower())

    def toggle_startup(self):
        try:
            enabled = configure_startup(self.start_with_windows.get())
            self.start_with_windows.set(enabled)
        except Exception as error:
            self.start_with_windows.set(startup_enabled())
            messagebox.showerror("Inicialização automática", str(error))
