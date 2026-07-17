import customtkinter as ctk


class OffersPage(ctk.CTkFrame):

    def __init__(self, master, database):
        super().__init__(master)

        self.database = database
        self.ofertas = []

        self.criar_interface()
        self.carregar()

    def criar_interface(self):

        ctk.CTkLabel(
            self,
            text="Ofertas",
            font=("Arial", 30, "bold")
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            self,
            text="Produtos com menor preco e variacao historica.",
            font=("Arial", 14)
        ).pack(pady=(0, 18))

        toolbar = ctk.CTkFrame(self)
        toolbar.pack(fill="x", padx=20)

        ctk.CTkButton(
            toolbar,
            text="Atualizar",
            width=110,
            command=self.carregar
        ).pack(side="left", padx=10, pady=10)

        self.status = ctk.CTkLabel(
            toolbar,
            text="",
            anchor="w"
        )
        self.status.pack(side="left", fill="x", expand=True, padx=10)

        self.lista = ctk.CTkTextbox(self)
        self.lista.pack(fill="both", expand=True, padx=20, pady=20)

    def carregar(self):

        self.ofertas = self.database.ofertas_com_variacao(40)
        self.renderizar()

    def renderizar(self):

        self.lista.delete("1.0", "end")

        total_coletas = self.database.total_coletas_preco()
        self.status.configure(
            text=f"{len(self.ofertas)} oferta(s) | {total_coletas} coleta(s) de preco"
        )

        if not self.ofertas:

            self.lista.insert(
                "end",
                "Nenhuma oferta com preco valido ainda.\n"
                "Faca uma busca em Buscar Produtos para alimentar o historico."
            )
            return

        for indice, produto in enumerate(self.ofertas, start=1):

            maior = produto["maior_preco"] or produto["preco_valor"]
            desconto = 0

            if maior and maior > produto["preco_valor"]:
                desconto = ((maior - produto["preco_valor"]) / maior) * 100

            marcador = "OFERTA" if desconto >= 5 else "PRECO"

            self.lista.insert(
                "end",
                f"{indice}. [{marcador}] {produto['loja']}\n"
                f"{produto['titulo']}\n"
                f"Preco atual....: R$ {produto['preco']}\n"
                f"Maior historico: R$ {maior:.2f}\n"
                f"Queda estimada.: {desconto:.1f}%\n"
                f"Coletas........: {produto['coletas']}\n"
                f"Link...........: {produto['link']}\n"
                "============================================================\n\n"
            )
