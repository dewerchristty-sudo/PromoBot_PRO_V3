import customtkinter as ctk

from src.core.notifier import Notifier


class SettingsPage(ctk.CTkFrame):

    def __init__(self, master, database):
        super().__init__(master)

        self.database = database
        self.notifier = Notifier()

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

        info = ctk.CTkTextbox(self, height=220)
        info.pack(fill="x", padx=20, pady=20)
        canais = self.notifier.configured_channels()
        canais_texto = ", ".join(canais) if canais else "nenhum canal configurado"

        info.insert(
            "end",
            "Lojas ativas:\n"
            "- Mercado Livre\n"
            "- Amazon\n"
            "- Kabum\n"
            "- Terabyte\n"
            "- Pichau\n"
            "- Magalu\n"
            "- Casas Bahia\n"
            "- Americanas\n"
            "- Shopee (pode bloquear automacao em alguns ambientes)\n\n"
            "Banco de dados:\n"
            "- promobot.db\n\n"
            "Notificacoes:\n"
            f"- {canais_texto}\n"
            "- Configure .env usando .env.example como modelo\n\n"
            "Os produtos duplicados sao atualizados pelo link."
        )
        info.configure(state="disabled")

    def alterar_tema(self, tema):

        ctk.set_appearance_mode(tema.lower())
