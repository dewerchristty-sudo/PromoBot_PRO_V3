import threading
import tkinter as tk
from queue import Empty, Queue

import customtkinter as ctk

from src.core.store_manager import StoreManager
from src.scraper import Parser


class SearchPage(ctk.CTkFrame):

    def __init__(
        self, master, database, initial_query="", category="", result_callback=None
    ):
        super().__init__(master)

        self.database = database
        self.worker = None
        self.window = self.winfo_toplevel()
        self.ui_queue = Queue()
        self.category = category
        self.result_callback = result_callback

        self.lojas = {}

        lojas_padrao = set(StoreManager.default_store_names())
        for nome in (
            StoreManager.stable_store_names()
            + StoreManager.experimental_store_names()
        ):
            self.lojas[nome] = tk.BooleanVar(value=nome in lojas_padrao)

        self.criar_interface()
        if initial_query:
            self.entry.insert(0, str(initial_query))
        self.after(50, self.process_ui_queue)

    def set_query(self, query):

        self.entry.delete(0, "end")
        self.entry.insert(0, str(query or ""))

    def set_category(self, category):

        self.category = str(category or "")

    def criar_interface(self):

        ctk.CTkLabel(
            self,
            text="Buscar Produtos",
            font=("Arial", 30, "bold")
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            self,
            text="Pesquise em marketplaces e lojas de hardware com foco em menor preco.",
            font=("Arial", 14)
        ).pack(pady=(0, 18))

        barra = ctk.CTkFrame(self)
        barra.pack(fill="x", padx=20)

        self.entry = ctk.CTkEntry(
            barra,
            placeholder_text="Digite o produto...",
            height=40
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.entry.bind("<Return>", lambda _event: self.iniciar_busca())

        self.botao = ctk.CTkButton(
            barra,
            text="Pesquisar",
            width=140,
            command=self.iniciar_busca
        )
        self.botao.pack(side="left")

        lojas_frame = ctk.CTkFrame(self)
        lojas_frame.pack(fill="x", padx=20, pady=(10, 0))

        ctk.CTkLabel(
            lojas_frame,
            text="Lojas:",
            font=("Arial", 14, "bold")
        ).pack(side="left", padx=(10, 12), pady=10)

        for nome, variavel in self.lojas.items():

            ctk.CTkCheckBox(
                lojas_frame,
                text=nome,
                variable=variavel,
                state=(
                    "disabled"
                    if nome in StoreManager.default_store_names()
                    else "normal"
                )
            ).pack(side="left", padx=(0, 12), pady=10)

        self.status = ctk.CTkLabel(
            self,
            text="Pronto para pesquisar.",
            anchor="w"
        )
        self.status.pack(fill="x", padx=20, pady=(12, 0))

        self.resultados = ctk.CTkTextbox(self)
        self.resultados.pack(fill="both", expand=True, padx=20, pady=20)

    # =======================================

    def escrever(self, texto):

        self.resultados.insert("end", texto + "\n")
        self.resultados.see("end")

    # =======================================

    def log_threadsafe(self, texto):

        self.dispatch_ui(lambda: self.escrever(texto))

    def dispatch_ui(self, callback):

        self.ui_queue.put(callback)

    def process_ui_queue(self):

        try:
            while True:
                self.ui_queue.get_nowait()()
        except Empty:
            pass

        if self.winfo_exists():
            self.after(50, self.process_ui_queue)

    # =======================================

    def limpar(self):

        self.resultados.delete("1.0", "end")

    # =======================================

    def iniciar_busca(self):

        if self.botao.cget("state") == "disabled":
            return

        produto = self.entry.get().strip()

        self.limpar()

        if not produto:

            self.escrever("Digite um produto para pesquisar.")
            self.status.configure(text="Informe um termo de busca.")
            return

        self.botao.configure(state="disabled", text="Pesquisando...")
        self.status.configure(text=f"Pesquisando por: {produto}")

        lojas_selecionadas = [
            nome for nome, variavel in self.lojas.items()
            if variavel.get()
        ]

        if not lojas_selecionadas:

            self.escrever("Selecione ao menos uma loja.")
            self.botao.configure(state="normal", text="Pesquisar")
            self.status.configure(text="Nenhuma loja selecionada.")
            return

        self.worker = threading.Thread(
            target=self.pesquisar,
            args=(produto, lojas_selecionadas),
            daemon=True
        )
        register = getattr(self.window, "register_background_worker", None)
        if register:
            register(self.worker)
        self.worker.start()

    # =======================================

    def pesquisar(self, produto, lojas_selecionadas):

        try:

            store_manager = StoreManager(
                progress_callback=self.log_threadsafe,
                enabled_stores=lojas_selecionadas
            )

            resultados = store_manager.search_all(produto)
            for resultado in resultados:
                resultado["categoria_manual"] = self.category
            self.database.salvar_lista(resultados)

            self.dispatch_ui(
                lambda: self.mostrar_resultados_e_notificar(resultados)
            )

        except Exception as erro:

            mensagem = f"Erro na busca: {erro}"
            self.dispatch_ui(
                lambda mensagem=mensagem: self.mostrar_erro(mensagem)
            )

        finally:

            unregister = getattr(self.window, "unregister_background_worker", None)
            if unregister:
                unregister(threading.current_thread())
            self.dispatch_ui(
                lambda: self.botao.configure(
                    state="normal",
                    text="Pesquisar"
                )
            )

    def mostrar_erro(self, mensagem):

        self.status.configure(text="A busca falhou.")
        self.escrever(mensagem)

    def mostrar_resultados_e_notificar(self, resultados):

        self.mostrar_resultados(resultados)
        if self.result_callback:
            self.result_callback(resultados)

    # =======================================

    def mostrar_resultados(self, resultados):

        self.status.configure(
            text=f"{len(resultados)} produtos encontrados e salvos."
        )

        self.escrever("")
        self.escrever(f"{len(resultados)} produtos encontrados.")
        self.escrever("")

        if not resultados:

            self.escrever(
                "Nenhum resultado retornou. Tente outro termo ou verifique sua conexao."
            )
            return

        resultados_ordenados = sorted(
            resultados,
            key=lambda item: Parser.price_to_float(item.get("preco", "")) or 999999999
        )

        melhor = resultados_ordenados[0]
        melhor_preco = Parser.price_to_float(melhor.get("preco", ""))

        if melhor_preco > 0:

            self.escrever(
                f"Menor preco: R$ {melhor['preco']} "
                f"em {melhor['loja']} - {melhor['titulo']}"
            )
            self.escrever("")

        for item in resultados_ordenados:

            self.escrever(
                f"[{item['loja']}]\n"
                f"{item['titulo']}\n"
                f"Preco: {item['preco'] or 'Nao informado'}\n"
                f"{item['link']}\n"
                "------------------------------------------------------------"
            )
