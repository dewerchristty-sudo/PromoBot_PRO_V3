import customtkinter as ctk


class Dashboard(ctk.CTkFrame):

    def __init__(self, master, database):
        super().__init__(master)

        self.database = database

        self.criar_interface()

    def criar_interface(self):

        ctk.CTkLabel(
            self,
            text="Dashboard",
            font=("Arial", 30, "bold")
        ).pack(pady=(20, 30))

        self.cards = ctk.CTkFrame(self)
        self.cards.pack(fill="x", padx=20)

        self.lbl_produtos = self.criar_card("Produtos", "0", 0)
        self.lbl_lojas = self.criar_card("Lojas", "0", 1)
        self.lbl_promocoes = self.criar_card("Ofertas", "0", 2)
        self.lbl_menor = self.criar_card("Menor preco", "-", 3)

        self.console = ctk.CTkTextbox(self, height=350)
        self.console.pack(fill="both", expand=True, padx=20, pady=20)

        self.atualizar()

    def criar_card(self, titulo, valor, coluna):

        frame = ctk.CTkFrame(self.cards, width=190, height=110)
        frame.grid(row=0, column=coluna, padx=10, pady=10, sticky="ew")
        frame.grid_propagate(False)

        ctk.CTkLabel(
            frame,
            text=titulo,
            font=("Arial", 18, "bold")
        ).pack(pady=(15, 5))

        valor_label = ctk.CTkLabel(
            frame,
            text=valor,
            font=("Arial", 30)
        )
        valor_label.pack()

        return valor_label

    def atualizar(self):

        produtos = self.database.total_produtos()
        lojas = self.database.total_lojas()
        promocoes = self.database.total_promocoes()
        coletas = self.database.total_coletas_preco()
        menor_preco = self.database.menor_preco()
        recentes = self.database.listar_recentes(5)

        self.lbl_produtos.configure(text=str(produtos))
        self.lbl_lojas.configure(text=str(lojas))
        self.lbl_promocoes.configure(text=str(promocoes))

        if menor_preco:
            self.lbl_menor.configure(text=f"R$ {menor_preco['preco']}")
        else:
            self.lbl_menor.configure(text="-")

        self.console.delete("1.0", "end")
        self.log("PromoBot_PRO V3 iniciado.")
        self.log("Banco de dados conectado.")
        self.log(f"Produtos salvos: {produtos}")
        self.log(f"Lojas com resultados: {lojas}")
        self.log(f"Ofertas com preco valido: {promocoes}")
        self.log(f"Coletas de preco: {coletas}")

        if menor_preco:
            self.log(
                f"Menor preco atual: R$ {menor_preco['preco']} "
                f"em {menor_preco['loja']}"
            )

        if recentes:
            self.log("")
            self.log("Ultimos produtos salvos:")

            for produto in recentes:
                self.log(f"- [{produto['loja']}] {produto['titulo']}")
        else:
            self.log("")
            self.log("Nenhum produto salvo ainda.")

    def log(self, mensagem):

        self.console.insert("end", mensagem + "\n")
        self.console.see("end")
