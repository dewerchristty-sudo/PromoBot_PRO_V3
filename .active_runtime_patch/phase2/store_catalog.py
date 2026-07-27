from dataclasses import dataclass
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class StoreDescriptor:
    key: str
    display_name: str
    enabled: bool = False
    adapter_path: str = ""


class StoreCatalog:
    """Catálogo extensível; registrar uma loja não a ativa no StoreManager."""

    def __init__(self, stores: Iterable[StoreDescriptor] = ()) -> None:
        self._stores: Dict[str, StoreDescriptor] = {}
        for store in stores:
            self.register(store)

    def register(self, store: StoreDescriptor) -> None:
        if store.key in self._stores:
            raise ValueError(f"Loja já cadastrada: {store.key}")
        self._stores[store.key] = store

    def get(self, key: str) -> Optional[StoreDescriptor]:
        return self._stores.get(key)

    def all(self) -> tuple:
        return tuple(self._stores.values())

    @classmethod
    def future_stores(cls) -> "StoreCatalog":
        return cls(
            StoreDescriptor(key, name)
            for key, name in (
                ("magalu", "Magalu"),
                ("kabum", "Kabum"),
                ("pichau", "Pichau"),
                ("terabyte", "Terabyte"),
                ("aliexpress", "AliExpress"),
            )
        )
