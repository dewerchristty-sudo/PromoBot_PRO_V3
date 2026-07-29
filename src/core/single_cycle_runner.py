from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
import tempfile
import time
from typing import Callable
from urllib.parse import urlsplit
from uuid import uuid4

from src.affiliates.amazon import (
    AmazonAffiliateProvider,
    validate_associate_tag,
)
from src.affiliates.config import StoreAffiliateConfig
from src.core.delivery_models import DeliveryStatus
from src.core.delivery_service import DeliveryService
from src.core.notifier import Notifier
from src.core.retry_policy import TransactionalRetryPolicy
from src.core.store_manager import StoreManager
from src.core.transactional_canary import (
    TransactionalCanaryConfig,
    normalize_canary_destination,
)
from src.database import Database
from src.database.delivery_repository import DeliveryRepository
from src.scraper import Parser


class SingleCycleMode(StrEnum):
    DRY_RUN = "dry-run"
    REAL = "real"


STORE_NAMES = {
    "mercado_livre": "Mercado Livre",
    "mercado livre": "Mercado Livre",
    "amazon": "Amazon",
    "shopee": "Shopee",
}


@dataclass(frozen=True, slots=True)
class SingleCycleConfig:
    term: str
    stores: tuple[str, ...]
    destination: str
    max_offers: int = 1
    transport: str = "evolution"
    database_path: str = "promobot.db"
    mode: SingleCycleMode = SingleCycleMode.DRY_RUN

    @classmethod
    def create(
        cls,
        *,
        term,
        stores,
        destination,
        max_offers=1,
        transport="evolution",
        database_path="promobot.db",
        real_send=False,
    ):
        term = str(term or "").strip()
        if not term:
            raise ValueError("O termo de pesquisa e obrigatorio.")
        raw_destination = str(destination or "").strip()
        if not raw_destination:
            raise ValueError("O destino autorizado e obrigatorio.")
        if "," in raw_destination:
            raise ValueError("Informe exatamente um destino, sem lista.")
        normalized_destination = normalize_canary_destination(raw_destination)
        if normalized_destination is None:
            raise ValueError("O destino autorizado e invalido.")
        normalized_stores = []
        for raw_store in stores or ():
            key = str(raw_store or "").strip().casefold().replace("-", "_")
            store = STORE_NAMES.get(key)
            if store is None:
                raise ValueError(f"Loja nao autorizada: {raw_store}.")
            if store not in normalized_stores:
                normalized_stores.append(store)
        if not normalized_stores:
            raise ValueError("Informe ao menos uma loja autorizada.")
        if int(max_offers) != 1:
            raise ValueError("O ciclo unico permite exatamente max_offers=1.")
        if str(transport or "").strip().casefold() != "evolution":
            raise ValueError("Somente o transporte Evolution e aceito.")
        raw_database_path = str(database_path or "").strip()
        if not raw_database_path:
            raise ValueError("O caminho do banco e obrigatorio.")
        database = Path(raw_database_path).expanduser()
        if database.exists() and not database.is_file():
            raise ValueError("O caminho do banco deve apontar para um arquivo.")
        if not database.parent.exists():
            raise ValueError("A pasta informada para o banco nao existe.")
        if real_send and not database.is_file():
            raise ValueError(
                "O envio real exige um banco SQLite existente."
            )
        return cls(
            term=term,
            stores=tuple(normalized_stores),
            destination=normalized_destination,
            max_offers=1,
            transport="evolution",
            database_path=str(database),
            mode=(
                SingleCycleMode.REAL
                if real_send else SingleCycleMode.DRY_RUN
            ),
        )


@dataclass(frozen=True, slots=True)
class SingleCycleResult:
    execution_id: str
    term: str
    stores_consulted: tuple[str, ...]
    stores_with_error: tuple[str, ...]
    collected_count: int
    eligible_count: int
    selected_offer: bool
    store: str
    title: str
    current_price: float
    previous_price: float
    discount_percent: float
    summarized_link: str
    masked_destination: str
    mode: str
    transport_calls: int
    delivery_status: str
    attempt_status: str
    final_result: str
    shadow_pipeline_enabled: bool
    shadow_database_touched: bool
    temporary_database_used: bool
    affiliate_block_reasons: tuple[str, ...]
    duration_seconds: float

    def as_dict(self):
        return asdict(self)


class TransportCallGuard:

    def __init__(self, transport, maximum=1):
        self.transport = transport
        self.maximum = max(int(maximum), 1)
        self.calls = 0

    def __call__(self, message, image, destination):
        if self.calls >= self.maximum:
            raise RuntimeError("Segunda chamada de transporte bloqueada.")
        self.calls += 1
        return self.transport(message, image, destination)


class SingleCycleRunner:
    """Executa uma coleta isolada sem tocar monitoramentos ou filas globais."""

    def __init__(
        self,
        config,
        *,
        collector: Callable | None = None,
        transport: Callable | None = None,
        database=None,
        notifier=None,
        clock=None,
        amazon_associate_tag=None,
    ):
        if not isinstance(config, SingleCycleConfig):
            raise TypeError("config deve ser SingleCycleConfig.")
        self.config = config
        self.collector = collector or self.collect_store
        self.transport = transport
        self.database = database
        self.notifier = notifier
        self.clock = clock or time.monotonic
        self._amazon_associate_tag = (
            validate_associate_tag(amazon_associate_tag)
            if amazon_associate_tag is not None else ""
        )

    def collect_store(self, term, store_name):
        messages = []
        manager = StoreManager(
            progress_callback=messages.append,
            enabled_stores=[store_name],
            offer_shadow_enabled=(
                False
                if self.config.mode == SingleCycleMode.DRY_RUN
                else None
            ),
        )
        products = manager.search_all(term)
        errors = [
            message for message in messages
            if str(message).strip().startswith("[ERRO]")
        ]
        if errors:
            raise RuntimeError(errors[-1].split(":", 1)[-1].strip())
        return products

    def run(self):
        started = self.clock()
        execution_id = uuid4().hex
        database, owned_database, temporary = self.open_database()
        notifier = self.notifier or Notifier(database)
        try:
            products, stores_with_error = self.collect(execution_id)
            eligible = self.eligible_products(
                products,
                notifier,
                database,
                execution_id,
            )
            selected = eligible[:self.config.max_offers]
            if not selected:
                return self.result(
                    execution_id,
                    stores_with_error,
                    products,
                    eligible,
                    None,
                    0,
                    "",
                    "",
                    "no_eligible_offer",
                    started,
                    notifier,
                )
            offer = selected[0]
            if self.config.mode == SingleCycleMode.DRY_RUN:
                fake_transport = self.transport or (
                    lambda _message, _image, _destination: {
                        "id": "dry-run"
                    }
                )
                guarded = TransportCallGuard(fake_transport)
                guarded(
                    notifier.format_alert(offer),
                    offer.get("imagem_whatsapp") or offer.get("imagem", ""),
                    self.config.destination,
                )
                return self.result(
                    execution_id,
                    stores_with_error,
                    products,
                    eligible,
                    offer,
                    guarded.calls,
                    "simulado",
                    "simulado",
                    "dry_run_completed",
                    started,
                    notifier,
                )
            return self.real_delivery(
                execution_id,
                stores_with_error,
                products,
                eligible,
                offer,
                database,
                notifier,
                started,
            )
        finally:
            self._amazon_associate_tag = ""
            if owned_database:
                database.fechar()
            if temporary is not None:
                temporary.cleanup()

    def open_database(self):
        if self.database is not None:
            return self.database, False, None
        if self.config.mode == SingleCycleMode.DRY_RUN:
            temporary = tempfile.TemporaryDirectory()
            path = Path(temporary.name) / "single_cycle.db"
            return Database(path), True, temporary
        return Database(self.config.database_path), True, None

    def collect(self, execution_id):
        products = []
        errors = []
        for store in self.config.stores:
            try:
                collected = self.collector(self.config.term, store)
            except Exception:
                errors.append(store)
                continue
            for raw_product in collected or ():
                product = dict(raw_product)
                if str(product.get("loja") or "").strip() != store:
                    continue
                product["_single_cycle_execution_id"] = execution_id
                product["preco_valor"] = self.price(product)
                self.enrich_amazon_affiliate(product)
                products.append(product)
        return products, tuple(errors)

    def enrich_amazon_affiliate(self, product):
        if str(product.get("loja") or "").strip() != "Amazon":
            return product
        original = str(product.get("link") or "").strip()
        product["link_original"] = original
        if not self._amazon_associate_tag:
            product["_affiliate_error"] = "associate_tag_nao_configurada"
            return product
        provider = AmazonAffiliateProvider(StoreAffiliateConfig(
            associate_tag=self._amazon_associate_tag
        ))
        affiliate_url, source, error = provider.generate(original)
        if error or not provider.validate(affiliate_url, original):
            product["_affiliate_error"] = error or "link_gerado_invalido"
            return product
        product["link_afiliado_salvo"] = affiliate_url
        product["_affiliate_source"] = source
        product["_affiliate_error"] = ""
        return product

    def eligible_products(
        self,
        products,
        notifier,
        database,
        execution_id,
    ):
        eligible = []
        seen = set()
        max_age = notifier.float_env("MAX_OFFER_AGE_HOURS")
        minimum_discount = notifier.float_env("MIN_DISCOUNT_PERCENT")
        for product in products:
            if product.get("_single_cycle_execution_id") != execution_id:
                continue
            if product.get("loja") not in self.config.stores:
                continue
            title = str(product.get("titulo") or "").strip()
            link = str(product.get("link") or "").strip()
            image = product.get("imagem_whatsapp") or product.get("imagem", "")
            current = self.price(product)
            if not title or not link.startswith(("http://", "https://")):
                continue
            if not (
                isinstance(image, (bytes, bytearray))
                or str(image).startswith(("http://", "https://"))
            ):
                continue
            if current <= 0 or product.get("disponivel") is False:
                continue
            try:
                if int(product.get("estoque", 1)) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            if max_age > 0 and notifier.offer_is_stale(product, max_age):
                continue
            previous = notifier.comparison_price(product)
            discount = notifier.discount_percent(product)
            if (
                previous > current
                and minimum_discount > 0
                and discount < minimum_discount
            ):
                continue
            ready, _blocked = notifier.partition_affiliate_ready([product])
            if not ready:
                continue
            signature = (
                str(product.get("loja") or "").strip().casefold(),
                " ".join(title.casefold().split()),
            )
            key = link or signature
            if key in seen:
                continue
            product.setdefault("assinatura", "|".join(signature))
            if self.was_already_notified(database, product):
                continue
            seen.add(key)
            eligible.append(product)
        return sorted(eligible, key=notifier.offer_priority_key)

    @staticmethod
    def was_already_notified(database, product):
        checker = getattr(database, "notificacao_ja_enviada", None)
        if not callable(checker):
            return False
        try:
            return bool(checker(product))
        except Exception:
            return False

    def real_delivery(
        self,
        execution_id,
        stores_with_error,
        products,
        eligible,
        offer,
        database,
        notifier,
        started,
    ):
        canary = TransactionalCanaryConfig(
            enabled=True,
            destinations=frozenset({self.config.destination}),
        )
        if not canary.authorizes(self.config.destination):
            raise RuntimeError("O destino nao foi autorizado pelo canario.")
        repository = DeliveryRepository(self.config.database_path)
        repository.migrate()
        guarded = TransportCallGuard(
            self.transport or notifier.send_evolution_image
        )
        try:
            service = DeliveryService(
                repository,
                retry_policy=TransactionalRetryPolicy(
                    enabled=True,
                    max_attempts=1,
                ),
            )
            delivery = notifier.transactional_delivery(
                offer,
                "WhatsApp",
                self.config.destination,
            )
            result = service.deliver(
                delivery,
                send=lambda: guarded(
                    notifier.format_alert(offer),
                    offer.get("imagem_whatsapp") or offer.get("imagem", ""),
                    self.config.destination,
                ),
                record_history=lambda: notifier.record_single_delivery(
                    database,
                    offer,
                    "WhatsApp",
                    self.config.destination,
                ),
                sanitized_metadata={
                    "content_type": (
                        "image/bytes"
                        if isinstance(
                            offer.get("imagem_whatsapp"),
                            (bytes, bytearray),
                        )
                        else "image/url"
                    ),
                    "destination_masked": result_mask(
                        self.config.destination
                    ),
                },
            )
            attempt_status = self.attempt_status(repository, result.delivery_id)
            return self.result(
                execution_id,
                stores_with_error,
                products,
                eligible,
                offer,
                guarded.calls,
                result.status.value,
                attempt_status,
                (
                    "already_processed"
                    if result.already_sent
                    else "sent"
                    if result.sent
                    else "review_required"
                    if result.status == DeliveryStatus.REVIEW_REQUIRED
                    else "delivery_failed"
                ),
                started,
                notifier,
            )
        finally:
            repository.close()

    @staticmethod
    def attempt_status(repository, delivery_id):
        attempts = repository.attempts_for(delivery_id)
        return attempts[-1].status.value if attempts else ""

    def result(
        self,
        execution_id,
        stores_with_error,
        products,
        eligible,
        offer,
        transport_calls,
        delivery_status,
        attempt_status,
        final_result,
        started,
        notifier,
    ):
        current = self.price(offer) if offer else 0.0
        previous = notifier.comparison_price(offer) if offer else 0.0
        return SingleCycleResult(
            execution_id=execution_id,
            term=self.config.term,
            stores_consulted=self.config.stores,
            stores_with_error=stores_with_error,
            collected_count=len(products),
            eligible_count=len(eligible),
            selected_offer=offer is not None,
            store=str((offer or {}).get("loja") or ""),
            title=str((offer or {}).get("titulo") or ""),
            current_price=current,
            previous_price=previous,
            discount_percent=(
                notifier.discount_percent(offer) if offer else 0.0
            ),
            summarized_link=summarize_link(
                str((offer or {}).get("link") or "")
            ),
            masked_destination=result_mask(self.config.destination),
            mode=self.config.mode.value,
            transport_calls=int(transport_calls),
            delivery_status=str(delivery_status or ""),
            attempt_status=str(attempt_status or ""),
            final_result=final_result,
            shadow_pipeline_enabled=(
                False
                if self.config.mode == SingleCycleMode.DRY_RUN
                else self.shadow_pipeline_enabled()
            ),
            shadow_database_touched=False,
            temporary_database_used=(
                self.config.mode == SingleCycleMode.DRY_RUN
            ),
            affiliate_block_reasons=tuple(sorted({
                str(product.get("_affiliate_error") or "").strip()
                for product in products
                if product.get("_affiliate_error")
            })),
            duration_seconds=round(max(self.clock() - started, 0), 3),
        )

    @staticmethod
    def shadow_pipeline_enabled():
        from src.offers.pipeline import OfferPipeline

        return OfferPipeline.enabled()

    @staticmethod
    def price(product):
        if not product:
            return 0.0
        value = product.get("preco_valor")
        if isinstance(value, (int, float)):
            return float(value)
        return float(Parser.price_to_float(product.get("preco", "")) or 0)


def result_mask(destination):
    normalized = normalize_canary_destination(destination) or ""
    if "@g.us" in normalized:
        local, domain = normalized.split("@", 1)
        return f"{local[:4]}*****{local[-4:]}@{domain}"
    return (
        f"{normalized[:4]}*****{normalized[-4:]}"
        if len(normalized) > 8 else "***"
    )


def summarize_link(link):
    try:
        parsed = urlsplit(link)
    except ValueError:
        return ""
    if not parsed.hostname:
        return ""
    path = parsed.path.rstrip("/")
    tail = path.rsplit("/", 1)[-1][:32] if path else ""
    return f"{parsed.hostname}/.../{tail}" if tail else parsed.hostname
