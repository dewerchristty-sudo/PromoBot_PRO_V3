import csv
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox

import customtkinter as ctk


class ProductsPage(ctk.CTkFrame):

    def __init__(self, master, database):
        super().__init__(master)

        self.database = database
        self.produtos = []
        self.somente_promocoes = tk.BooleanVar(value=False)

        self.criar_interface()
        self.carregar()

    # =====================================

    def criar_interface(self):

        ctk.CTkLabel(
            self,
            text="Produtos Encontrados",
            font=("Arial", 30, "bold")
        ).pack(pady=(20, 15))

        toolbar = ctk.CTkFrame(self)
        toolbar.pack(fill="x", padx=20)

        self.filtro = ctk.CTkEntry(
            toolbar,
            placeholder_text="Filtrar por loja, titulo ou preco...",
            height=38
        )
        self.filtro.grid(row=0, column=0, sticky="ew", padx=(10, 8), pady=10)
        self.filtro.bind("<Return>", lambda _event: self.carregar())

        self.preco_min = ctk.CTkEntry(
            toolbar,
            placeholder_text="Preco min.",
            width=95,
            height=38
        )
        self.preco_min.grid(row=0, column=1, padx=(0, 8), pady=10)

        self.preco_max = ctk.CTkEntry(
            toolbar,
            placeholder_text="Preco max.",
            width=95,
            height=38
        )
        self.preco_max.grid(row=0, column=2, padx=(0, 8), pady=10)

        self.ordenar = ctk.CTkOptionMenu(
            toolbar,
            values=["recentes", "menor_preco", "maior_preco", "loja"],
            width=130,
            command=lambda _valor: self.carregar()
        )
        self.ordenar.set("recentes")
        self.ordenar.grid(row=0, column=3, padx=(0, 8), pady=10)

        self.chk_promocoes = ctk.CTkCheckBox(
            toolbar,
            text="Ofertas",
            variable=self.somente_promocoes,
            command=self.carregar
        )
        self.chk_promocoes.grid(row=0, column=4, padx=(0, 8), pady=10)

        ctk.CTkButton(
            toolbar,
            text="Filtrar",
            width=90,
            command=self.carregar
        ).grid(row=0, column=5, padx=(0, 8), pady=10)

        ctk.CTkButton(
            toolbar,
            text="Atualizar",
            width=95,
            command=self.carregar_todos
        ).grid(row=0, column=6, padx=(0, 8), pady=10)

        ctk.CTkButton(
            toolbar,
            text="Exportar CSV",
            width=120,
            command=self.exportar_csv
        ).grid(row=0, column=7, padx=(0, 8), pady=10)

        ctk.CTkButton(
            toolbar,
            text="Limpar",
            width=90,
            fg_color="#8a1f1f",
            hover_color="#6f1717",
            command=self.limpar_banco
        ).grid(row=0, column=8, padx=(0, 10), pady=10)

        toolbar.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(self, text="", anchor="w")
        self.status.pack(fill="x", padx=20, pady=(10, 0))

        self.lista = ctk.CTkTextbox(self)
        self.lista.pack(fill="both", expand=True, padx=20, pady=20)

    # =====================================

    def carregar_todos(self):

        self.filtro.delete(0, "end")
        self.preco_min.delete(0, "end")
        self.preco_max.delete(0, "end")
        self.somente_promocoes.set(False)
        self.ordenar.set("recentes")
        self.carregar()

    # =====================================

    def carregar(self):

        termo = self.filtro.get().strip()

        try:

            self.produtos = self.database.buscar_produtos(
                termo=termo,
                preco_min=self.preco_min.get().strip(),
                preco_max=self.preco_max.get().strip(),
                somente_promocoes=self.somente_promocoes.get(),
                ordenar=self.ordenar.get()
            )

        except ValueError:

            messagebox.showerror(
                "Filtro invalido",
                "Use apenas numeros nos campos de preco."
            )
            return

        self.renderizar()

    # =====================================

    def renderizar(self):

        self.lista.delete("1.0", "end")

        menor = ""

        produtos_com_preco = [
            produto for produto in self.produtos
            if produto["preco_valor"] > 0
        ]

        if produtos_com_preco:
            melhor = min(produtos_com_preco, key=lambda item: item["preco_valor"])
            menor = f" | menor preco: R$ {melhor['preco']} ({melhor['loja']})"

        self.status.configure(text=f"{len(self.produtos)} produto(s){menor}")

        if not self.produtos:

            self.lista.insert("end", "Nenhum produto encontrado.")
            return

        for produto in self.produtos:

            self.lista.insert(
                "end",
                f"Loja........: {produto['loja']}\n"
                f"Produto.....: {produto['titulo']}\n"
                f"Preco.......: {produto['preco'] or 'Nao informado'}\n"
                f"Preco num...: {produto['preco_valor']:.2f}\n"
                f"Oferta......: {'Sim' if produto['promocao'] else 'Nao'}\n"
                f"Link........: {produto['link']}\n"
                f"Data........: {produto['data']}\n"
                "============================================================\n\n"
            )

    # =====================================

    def exportar_csv(self):

        if not self.produtos:

            messagebox.showinfo(
                "Exportar CSV",
                "Nao ha produtos para exportar."
            )
            return

        caminho = filedialog.asksaveasfilename(
            title="Salvar produtos",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")]
        )

        if not caminho:
            return

        with open(caminho, "w", newline="", encoding="utf-8-sig") as arquivo:

            writer = csv.writer(arquivo, delimiter=";")
            writer.writerow([
                "loja",
                "titulo",
                "preco",
                "preco_valor",
                "promocao",
                "link",
                "imagem",
                "data",
            ])

            for produto in self.produtos:
                writer.writerow([
                    produto["loja"],
                    produto["titulo"],
                    produto["preco"],
                    produto["preco_valor"],
                    produto["promocao"],
                    produto["link"],
                    produto["imagem"],
                    produto["data"],
                ])

        messagebox.showinfo(
            "Exportar CSV",
            f"Arquivo salvo em:\n{caminho}"
        )

    # =====================================

    def limpar_banco(self):

        confirmado = messagebox.askyesno(
            "Limpar produtos",
            "Deseja apagar todos os produtos salvos?"
        )

        if not confirmado:
            return

        self.database.limpar()
        self.carregar()
