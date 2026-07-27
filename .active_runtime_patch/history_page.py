import customtkinter as ctk
from src.scraper import Parser


class HistoryPage(ctk.CTkFrame):

    def __init__(self, master, database):
        super().__init__(master)

        self.database = database

        self.criar_interface()
        self.carregar()

    def criar_interface(self):

        ctk.CTkLabel(
            self,
            text="Historico",
            font=("Arial", 30, "bold")
        ).pack(pady=(20, 15))

        self.lista = ctk.CTkTextbox(self)
        self.lista.pack(fill="both", expand=True, padx=20, pady=20)

    def carregar(self):

        self.lista.delete("1.0", "end")

        resumo = self.database.resumo_por_loja()
        recentes = self.database.listar_recentes(20)
        ofertas = self.database.ofertas_com_variacao(10)

        self.lista.insert("end", "Resumo por loja\n")
        self.lista.insert("end", "==============================\n\n")

        if resumo:

            for item in resumo:
                self.lista.insert(
                    "end",
                    f"{item['loja']}: {item['total']} produto(s)"
                    f" | ultima busca: {item['ultima_data']}\n"
                )

        else:

            self.lista.insert("end", "Nenhum dado salvo ainda.\n")

        self.lista.insert("end", "\nProdutos recentes\n")
        self.lista.insert("end", "==============================\n\n")

        if not recentes:
            self.lista.insert("end", "Nenhum produto recente.\n")
            return

        for produto in recentes:
            self.lista.insert(
                "end",
                f"{produto['data']} | [{produto['loja']}] "
                f"{produto['titulo']}\n"
            )

        self.lista.insert("end", "\nEvolucao de preco\n")
        self.lista.insert("end", "==============================\n\n")

        if not ofertas:
            self.lista.insert("end", "Sem historico de preco suficiente.\n")
            return

        for produto in ofertas:

            maior = produto["maior_preco"] or produto["preco_valor"]
            desconto = 0

            if maior and maior > produto["preco_valor"]:
                desconto = ((maior - produto["preco_valor"]) / maior) * 100

            self.lista.insert(
                "end",
                f"[{produto['loja']}] "
                f"{Parser.format_brl(produto['preco'], True)} "
                f"| queda {desconto:.1f}% | {produto['titulo']}\n"
            )
