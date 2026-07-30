from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from src.affiliates.validation import safe_absolute_url


@runtime_checkable
class ProductUrlClient(Protocol):
    def product_from_url(self, url: str) -> dict[str, Any]:
        ...

    def close(self, page: Any = None) -> None:
        ...


class ProductUrlCollectionError(RuntimeError):
    pass


class ProductUrlCollectionAdapter:
    def __init__(
        self,
        scraper: ProductUrlClient | None = None,
        scraper_factory: Callable[[], ProductUrlClient] | None = None,
        allowed_domains: tuple[str, ...] = (),
    ) -> None:
        if scraper is not None and scraper_factory is not None:
            raise ValueError("Informe scraper ou scraper_factory, não ambos")
        self.scraper = scraper
        self.scraper_factory = scraper_factory
        self.allowed_domains = allowed_domains
        self._owns_scraper = scraper is None

    @staticmethod
    def sanitize_error(error: Exception) -> str:
        message = " ".join(str(error).split())
        message = re.sub(
            r"(?i)\b(authorization|cookie|token|api[-_ ]?key)\s*[:=]\s*\S+",
            r"\1=<removido>",
            message,
        )
        message = re.sub(
            r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@",
            r"\1<credenciais-removidas>@",
            message,
        )
        message = re.sub(
            r"(?i)\b[A-Z]:\\(?:[^\\\s]+\\)+[^\\\s]*",
            "<caminho-removido>",
            message,
        )
        return message[:300] or "Falha técnica sem detalhes disponíveis"

    def validate_url(self, url: str) -> bool:
        if not url:
            return False

        url_str = str(url).strip()
        if not url_str:
            return False

        # Rejeitar credenciais embutidas
        if "@" in url_str and "://" in url_str:
            from urllib.parse import urlparse
            parsed = urlparse(url_str)
            if parsed.username or parsed.password:
                return False

        # Usar a função oficial de validação do projeto
        if self.allowed_domains:
            return safe_absolute_url(url_str, self.allowed_domains)
        return False

    def collect(self, url: str) -> dict[str, Any]:
        url_str = str(url or "").strip()
        if not url_str:
            raise ValueError("URL não pode ser vazia")

        if not self.validate_url(url_str):
            raise ProductUrlCollectionError(
                f"URL inválida ou domínio não permitido: {url_str[:100]}"
            )

        scraper = self.scraper or (self.scraper_factory() if self.scraper_factory else None)
        if scraper is None:
            raise ProductUrlCollectionError(
                "Nenhum scraper disponível para coleta por URL"
            )

        if not callable(getattr(scraper, "product_from_url", None)):
            raise ProductUrlCollectionError(
                "A store não possui o método product_from_url()"
            )

        try:
            product = scraper.product_from_url(url_str)
            if product is None:
                raise ProductUrlCollectionError(
                    "product_from_url() retornou None"
                )
            if not isinstance(product, Mapping):
                raise ProductUrlCollectionError(
                    "product_from_url() retornou tipo inválido"
                )
            return dict(product)
        except Exception as error:
            if isinstance(error, ProductUrlCollectionError):
                raise
            raise ProductUrlCollectionError(
                self.sanitize_error(error)
            ) from error
        finally:
            if self._owns_scraper:
                closer = getattr(scraper, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:
                        pass