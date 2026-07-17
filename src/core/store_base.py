from abc import ABC, abstractmethod


class StoreBase(ABC):
    """
    Classe base para todas as lojas.
    Toda loja deverá herdar desta classe.
    """

    def __init__(self, browser_manager):
        self.browser_manager = browser_manager

    @property
    @abstractmethod
    def name(self):
        """Nome da loja"""
        pass

    @abstractmethod
    def search(self, product: str):
        """
        Deve retornar uma lista de produtos.

        Exemplo:
        [
            {
                "titulo": "...",
                "preco": "...",
                "link": "...",
                "imagem": "..."
            }
        ]
        """
        pass