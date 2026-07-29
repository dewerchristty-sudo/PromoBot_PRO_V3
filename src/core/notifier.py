import base64
import os
import random
import re
import time
import logging
import sys
import unicodedata
from io import BytesIO
from datetime import datetime
from datetime import timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from typing import Any, Optional

import requests
from dotenv import load_dotenv
from PIL import Image, ImageOps, UnidentifiedImageError
from src.core.delivery_models import (
    DeliveryBatchResult,
    DeliveryStatus,
    DestinationDelivery,
    DestinationDeliveryResult,
    delivery_publication_key,
    mask_delivery_destination,
)
from src.core.delivery_service import DeliveryService
from src.core.retry_policy import TransactionalRetryPolicy
from src.core.transactional_canary import TransactionalCanaryConfig
from src.database.delivery_repository import DeliveryRepository
from src.stores.active import is_active_store

logger = logging.getLogger(__name__)


class LowResolutionImageError(ValueError):
    def __init__(self, message, image_url, width, height):
        super().__init__(message)
        self.image_url = image_url
        self.width = int(width)
        self.height = int(height)


class EvolutionSendError(RuntimeError):
    pass


class Notifier:

    ALWAYS_DISABLED_NOTIFICATION_STORES = set()
    MAX_MANUAL_IMAGE_BYTES = 15 * 1024 * 1024
    MIN_MANUAL_IMAGE_WIDTH = 500
    MIN_MANUAL_IMAGE_HEIGHT = 500

    @staticmethod
    def evolution_diagnostic_logger():

        runtime_root = (
            Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]
        )
        log_dir = runtime_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        diagnostic_logger = logging.getLogger(
            "promobot.evolution_api_diagnostic"
        )
        diagnostic_logger.setLevel(logging.WARNING)
        diagnostic_logger.propagate = False
        log_path = (log_dir / "evolution_api_diagnostic.log").resolve()
        has_target_handler = any(
            isinstance(handler, logging.FileHandler)
            and Path(handler.baseFilename).resolve() == log_path
            for handler in diagnostic_logger.handlers
        )
        if not has_target_handler:
            handler = logging.FileHandler(
                log_path,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s"
            ))
            diagnostic_logger.addHandler(handler)
        return diagnostic_logger

    WHATSAPP_CATEGORY_KEYWORDS = {
        "mamae_bebe": (
            "bebe", "bebê", "mamae", "mamãe", "materna", "maternidade",
            "gestante", "fralda", "lenço umedecido", "mamadeira", "chupeta",
            "berço", "carrinho de bebe", "cadeirinha", "enxoval de bebe",
            "infantil", "recem-nascido", "recém-nascido",
        ),
        "eletrodomesticos": (
            "geladeira", "refrigerador", "fogao", "fogão", "micro-ondas",
            "microondas", "air fryer", "fritadeira", "liquidificador",
            "batedeira", "cafeteira", "sanduicheira", "maquina de lavar",
            "máquina de lavar", "lava-louças", "lava loucas", "ventilador",
            "ar-condicionado", "ar condicionado", "eletroportatil",
        ),
        "smartphones_tecnologia": (
            "smartphone", "celular", "iphone", "galaxy", "tablet", "notebook",
            "computador", "monitor", "smartwatch", "fone", "headset",
            "caixa de som", "videogame", "playstation", "xbox", "nintendo",
            "carregador", "cabo usb", "camera", "câmera", "roteador", "ssd",
            "memoria ram", "memória ram", "teclado", "mouse", "smart tv",
            "mini tv", "tv portatil", "televisao", "televisão", "televisor",
        ),
        "beleza_perfumaria": (
            "perfume", "perfumaria", "body splash", "maquiagem", "batom",
            "hidratante", "protetor solar", "shampoo", "condicionador",
            "mascara capilar", "mascara de tratamento", "máscara capilar",
            "secador", "chapinha",
            "modelador", "barbeador", "desodorante", "skincare", "cosmetico",
            "cosmético",
        ),
        "limpeza_utilidades": (
            "detergente", "sabao", "sabão", "desinfetante", "amaciante",
            "limpador", "vassoura", "rodo", "balde", "pano", "aspirador",
            "organizador", "pote", "panela", "talher", "utensilio",
            "utensílio", "lixeira", "escorredor", "mop", "limpeza",
        ),
        "casa_enxoval": (
            "jogo de cama", "lencol", "lençol", "travesseiro", "cobertor",
            "edredom", "toalha", "tapete", "cortina", "capa de sofa",
            "capa de sofá", "almofada", "colchao", "colchão", "movel",
            "móvel", "decoracao", "decoração", "enxoval", "sofa", "sofá",
            "guarda-roupa", "mesa", "cadeira",
        ),
    }

    ALERT_HEADLINES = (
        "\U0001f6a8 OFERTA REL\u00c2MPAGO! Corre antes que acabe!",
        "\U0001f525 PRE\u00c7O CAIU! Aproveite enquanto d\u00e1 tempo!",
        "\u26a1 PROMO\u00c7\u00c3O IMPERD\u00cdVEL! Estoque limitado!",
        "\U0001f3f7\ufe0f ACHADINHO DO DIA! Olha esse pre\u00e7o!",
        "\U0001f4a5 DESCONTO LIBERADO! Garanta o seu!",
        "\U0001f929 OFERTA ENCONTRADA! Vale a pena conferir!",
        "\u23f0 CORRE! Essa promo\u00e7\u00e3o pode acabar a qualquer momento!",
        "\U0001f4b8 ECONOMIZE AGORA! Oferta por tempo limitado!",
        "\U0001f6d2 HORA DE APROVEITAR! Pre\u00e7o especial encontrado!",
        "\U0001f680 SUPEROFERTA NO AR! N\u00e3o deixe passar!",
    )

    def __init__(self, database=None, delivery_service=None):

        load_dotenv()
        self.database = database
        self._delivery_service = delivery_service
        self._delivery_repository = None
        self._last_headline = None
        self._headline_queue = []

    def configured_channels(self):

        channels = []

        if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
            channels.append("Telegram")

        if self.whatsapp_configured():
            channels.append("WhatsApp")

        return channels

    @staticmethod
    def transactional_delivery_enabled():

        return os.getenv(
            "ENABLE_TRANSACTIONAL_DELIVERY",
            "false",
        ).strip().casefold() in {"1", "true", "yes", "on", "sim"}

    def transactional_delivery_service(self):

        if self._delivery_service is not None:
            return self._delivery_service
        if self.database is None or not getattr(self.database, "db", None):
            raise RuntimeError(
                "Banco indisponivel para a entrega transacional."
            )
        repository = DeliveryRepository(self.database.db)
        try:
            repository.migrate()
        except Exception:
            repository.close()
            raise
        self._delivery_repository = repository
        self._delivery_service = DeliveryService(
            repository,
            retry_policy=TransactionalRetryPolicy.from_environment(),
        )
        return self._delivery_service

    def close_transactional_delivery(self):

        if self._delivery_repository is not None:
            self._delivery_repository.close()
            self._delivery_repository = None
            self._delivery_service = None

    def transactional_delivery(self, item, channel, destination):

        publication_key = self.transactional_publication_key(item)
        return DestinationDelivery.create(
            publication_key,
            channel,
            destination,
            alert_id=self.value(item, "alerta_id"),
            original_link=self.value(item, "link", "") or "",
            signature=self.value(item, "assinatura", "") or "",
            decision_origin=(
                self.value(item, "origem_decisao", "legado") or "legado"
            ),
        )

    def transactional_canary_config(self):

        return TransactionalCanaryConfig.from_environment()

    def legacy_delivery_result(
        self,
        item,
        channel,
        destination,
        *,
        sent=False,
        error="",
        history_error="",
        transport_result=None,
    ):

        delivery = self.transactional_delivery(item, channel, destination)
        return DestinationDeliveryResult(
            delivery_id=0,
            delivery_key=f"legacy:{delivery.delivery_key}",
            publication_key=delivery.publication_key,
            channel=channel,
            masked_destination=mask_delivery_destination(destination),
            status=DeliveryStatus.SENT if sent else DeliveryStatus.FAILED,
            sent=sent,
            error=error,
            external_id=DeliveryService.external_id(transport_result),
            history_error=history_error,
        )

    def deliver_legacy_destination(
        self,
        item,
        channel,
        destination,
        send,
    ):

        try:
            transport_result = send()
        except Exception as error:
            safe_error = DeliveryService.safe_error(error, destination)
            return self.legacy_delivery_result(
                item,
                channel,
                destination,
                error=safe_error,
            )
        history_error = ""
        try:
            self.record_single_delivery(
                self.database,
                item,
                channel,
                destination,
            )
        except Exception as error:
            history_error = DeliveryService.safe_error(error, destination)
        return self.legacy_delivery_result(
            item,
            channel,
            destination,
            sent=True,
            history_error=history_error,
            transport_result=transport_result,
        )

    def transactional_publication_key(self, item):

        return delivery_publication_key(
            alert_id=self.value(item, "alerta_id", ""),
            original_link=self.value(item, "link", ""),
            signature=self.value(item, "assinatura", ""),
            price=self.value(item, "preco_valor", self.value(item, "preco", "")),
        )

    def transactional_delivered_alerts(self, alerts, result):

        completed = result.completed_publication_keys
        return [
            alert for alert in alerts
            if self.transactional_publication_key(alert) in completed
        ]

    def send_alerts(
        self,
        alerts,
        database=None,
        enforce_offer_quality=True,
        ignore_notification_hours=False,
    ):

        alerts = [
            alert for alert in alerts or ()
            if is_active_store(self.value(alert, "loja", "store"))
        ]
        if not alerts:
            return "Nenhum alerta disparado."

        if (
            not ignore_notification_hours
            and not self.within_notification_hours()
        ):
            return "Nenhum envio: fora do horario permitido (08h as 22h)."

        database = database or self.database

        if database is not None and self.database is None:
            self.database = database

        enabled_alerts, disabled_alerts = self.partition_enabled_stores(alerts)
        if enforce_offer_quality:
            quality_alerts, stale_alerts, low_discount_alerts = (
                self.partition_offer_quality(enabled_alerts)
            )
        else:
            quality_alerts = list(enabled_alerts)
            stale_alerts = []
            low_discount_alerts = []
        ready_alerts, blocked_alerts = self.partition_affiliate_ready(
            quality_alerts
        )
        image_alerts, image_blocked_alerts = self.partition_image_ready(
            ready_alerts
        )
        telegram_alerts = list(image_alerts)
        whatsapp_alerts, unrouted_alerts = self.partition_whatsapp_routable(
            image_alerts
        )
        # A vaga horaria deve ficar com a melhor oportunidade, e nao apenas
        # com o primeiro produto que chegou da coleta.
        whatsapp_alerts = sorted(
            whatsapp_alerts,
            key=self.offer_priority_key,
        )
        whatsapp_alerts, rate_limited_alerts = self.apply_hourly_limit(
            whatsapp_alerts,
            database,
        )

        self.record_review_pendencies(
            database,
            disabled_alerts=disabled_alerts,
            stale_alerts=stale_alerts,
            low_discount_alerts=low_discount_alerts,
            affiliate_pending=blocked_alerts,
            image_pending=image_blocked_alerts,
            unrouted_alerts=unrouted_alerts,
        )
        if rate_limited_alerts and database is not None:
            enqueue = getattr(database, "enfileirar_notificacoes", None)
            if enqueue:
                enqueue(rate_limited_alerts, "Limite horario; nova tentativa automatica.")

        if not telegram_alerts and not whatsapp_alerts:
            return "Nenhum envio: " + self.skipped_summary(
                disabled_alerts,
                stale_alerts,
                low_discount_alerts,
                blocked_alerts,
                rate_limited_alerts,
                unrouted_alerts,
                image_blocked_alerts,
            )

        sent = []
        errors = []
        delivered_alerts = []
        history_error = False
        transactional = self.transactional_delivery_enabled()

        try:
            telegram_result = self.send_telegram_alerts(telegram_alerts)
            if telegram_result:
                sent.append("Telegram")
                if isinstance(telegram_result, DeliveryBatchResult):
                    delivered_alerts.extend(
                        self.transactional_delivered_alerts(
                            telegram_alerts,
                            telegram_result,
                        )
                    )
                    history_error = (
                        history_error or bool(telegram_result.history_errors)
                    )
                else:
                    delivered_alerts.extend(telegram_alerts)
                if (
                    database is not None
                    and not isinstance(telegram_result, DeliveryBatchResult)
                ):
                    try:
                        self.record_deliveries(database, telegram_alerts, ["Telegram"])
                    except Exception:
                        history_error = True
            if isinstance(telegram_result, DeliveryBatchResult):
                errors.extend(telegram_result.errors)
        except Exception as error:
            errors.append(f"Telegram: {error}")

        try:
            whatsapp_result = self.send_whatsapp_alerts(whatsapp_alerts)
            if whatsapp_result:
                sent.append("WhatsApp")
                if isinstance(whatsapp_result, DeliveryBatchResult):
                    delivered_alerts.extend(
                        self.transactional_delivered_alerts(
                            whatsapp_alerts,
                            whatsapp_result,
                        )
                    )
                    history_error = (
                        history_error or bool(whatsapp_result.history_errors)
                    )
                else:
                    delivered_alerts.extend(whatsapp_alerts)
                if (
                    database is not None
                    and not isinstance(whatsapp_result, DeliveryBatchResult)
                ):
                    try:
                        self.record_deliveries(database, whatsapp_alerts, ["WhatsApp"])
                    except Exception:
                        history_error = True
            if isinstance(whatsapp_result, DeliveryBatchResult):
                errors.extend(whatsapp_result.errors)
        except Exception as error:
            errors.append(f"WhatsApp: {error}")

        if sent:
            if database is not None:
                resolver = getattr(database, "resolver_pendencias_por_chaves", None)
                if resolver:
                    resolver([
                        self.value(alert, "link", "") or ""
                        for alert in delivered_alerts
                    ])
                alerts_with_id = [
                    alert
                    for alert in delivered_alerts
                    if self.value(alert, "alerta_id") is not None
                ]
                if alerts_with_id:
                    database.marcar_notificacoes_enviadas(alerts_with_id)

            result = "Enviado por: " + ", ".join(sent)
            if blocked_alerts:
                result += f" | {len(blocked_alerts)} aguardando link afiliado"
            if image_blocked_alerts:
                result += f" | {len(image_blocked_alerts)} sem imagem valida"
            if disabled_alerts:
                result += f" | {len(disabled_alerts)} de lojas desabilitadas"
            if stale_alerts:
                result += f" | {len(stale_alerts)} ofertas vencidas"
            if low_discount_alerts:
                result += f" | {len(low_discount_alerts)} abaixo do desconto minimo"
            if rate_limited_alerts:
                result += f" | {len(rate_limited_alerts)} aguardando limite horario"
            if unrouted_alerts:
                result += f" | {len(unrouted_alerts)} sem categoria segura"
            if history_error:
                result += " | aviso: falha ao registrar historico local"
            if transactional and errors:
                result += f" | {len(errors)} falha(s) isolada(s) por destino"

            return result

        if errors:
            return "Falha ao enviar: " + " | ".join(errors)

        if any((
            disabled_alerts,
            stale_alerts,
            low_discount_alerts,
            blocked_alerts,
            rate_limited_alerts,
            unrouted_alerts,
            image_blocked_alerts,
        )):
            return "Nenhum envio: " + self.skipped_summary(
                disabled_alerts,
                stale_alerts,
                low_discount_alerts,
                blocked_alerts,
                rate_limited_alerts,
                unrouted_alerts,
                image_blocked_alerts,
            )

        return "Configure WhatsApp no arquivo .env."

    def send_manual_alerts(
        self,
        alerts,
        database=None,
        ignore_notification_hours=False,
    ):
        """Envia apos confirmacao humana, sem o filtro automatico de qualidade."""

        return self.send_alerts(
            alerts,
            database=database,
            enforce_offer_quality=False,
            ignore_notification_hours=ignore_notification_hours,
        )

    def send_test_alert(self, item):

        if not is_active_store(self.value(item, "loja", "store")):
            return "Falha no teste: loja inativa."
        if self.database is None:
            return "Falha no teste: banco de dados indisponivel."

        image = str(self.value(item, "imagem", "") or "").strip()
        if not image.startswith("http"):
            return "Falha no teste: produto sem imagem valida."

        ready, blocked = self.partition_affiliate_ready([item])
        if blocked or not ready:
            return "Falha no teste: link afiliado oficial nao validado."

        recipients = self.whatsapp_recipients_for_alert(item)
        if len(recipients) != 1:
            return "Falha no teste: grupo de destino nao configurado."

        if not self.whatsapp_configured():
            return "Falha no teste: WhatsApp nao configurado."

        recipient = recipients[0]
        if self.whatsapp_group_rate_limited(recipient):
            return "Falha no teste: limite horario do grupo atingido."

        message = "\U0001f9ea TESTE CONTROLADO DO PROMOBOT\n\n" + self.format_alert(item)

        try:
            self.send_whatsapp_message(message, image, recipient)
            original_link = self.value(item, "link", "") or ""
            self.database.registrar_envio(
                self.value(item, "loja", "") or "",
                self.value(item, "titulo", "") or "",
                original_link,
                self.affiliate_link(item),
                self.database.etiqueta_link_afiliado(original_link),
                "WhatsApp Teste",
                recipient,
            )
        except Exception as error:
            return f"Falha no teste: {error}"

        return "Teste enviado por WhatsApp para 1 grupo."

    def send_review_alert(self, item):
        """Envia manualmente ao grupo privado, sem consumir o limite dos grupos."""

        if not is_active_store(self.value(item, "loja", "store")):
            return "Falha: loja inativa."
        recipient = os.getenv("WHATSAPP_REVIEW_GROUP", "").strip()
        if not recipient.endswith("@g.us"):
            return "Falha: grupo de revisao nao configurado."
        if not self.whatsapp_configured():
            return "Falha: WhatsApp nao configurado."
        if not self.has_affiliate_link(item):
            return "Falha: link afiliado oficial nao validado."

        image = self.verified_whatsapp_image(item)
        if not image.startswith("http"):
            return "Falha: imagem do produto nao confirmada."

        try:
            self.send_whatsapp_message(self.format_alert(item), image, recipient)
            if self.database is not None:
                registrar = getattr(self.database, "registrar_envio", None)
                if registrar:
                    original_link = self.value(item, "link", "") or ""
                    registrar(
                        self.value(item, "loja", "") or "",
                        self.value(item, "titulo", "") or "",
                        original_link,
                        self.affiliate_link(item),
                        self.database.etiqueta_link_afiliado(original_link),
                        "WhatsApp Revisao",
                        recipient,
                    )
        except Exception as error:
            return f"Falha no envio para revisao: {error}"

        return "Oferta enviada para o grupo Revisao PromoBot."

    def partition_enabled_stores(self, alerts):

        disabled_names = {
            name.strip().lower()
            for name in os.getenv("NOTIFICATION_DISABLED_STORES", "").split(",")
            if name.strip()
        }
        disabled_names.update(self.ALWAYS_DISABLED_NOTIFICATION_STORES)
        enabled = []
        disabled = []

        for alert in alerts:
            store = str(self.value(alert, "loja", "") or "").strip().lower()
            target = disabled if store in disabled_names else enabled
            target.append(alert)

        return enabled, disabled

    def partition_offer_quality(self, alerts):

        max_age_hours = self.float_env("MAX_OFFER_AGE_HOURS")
        min_discount = self.float_env("MIN_DISCOUNT_PERCENT")
        ready = []
        stale = []
        low_discount = []

        for alert in alerts:
            if max_age_hours > 0 and self.offer_is_stale(alert, max_age_hours):
                stale.append(alert)
                continue

            if min_discount > 0 and self.discount_percent(alert) < min_discount:
                low_discount.append(alert)
                continue

            ready.append(alert)

        return ready, stale, low_discount

    def partition_image_ready(self, alerts):

        ready = []
        blocked = []
        for alert in alerts:
            image = str(self.value(alert, "imagem", "") or "").strip()
            target = ready if image.startswith(("http://", "https://")) else blocked
            target.append(alert)
        return ready, blocked

    def record_review_pendencies(
        self,
        database,
        disabled_alerts=None,
        stale_alerts=None,
        low_discount_alerts=None,
        affiliate_pending=None,
        image_pending=None,
        unrouted_alerts=None,
    ):

        register = getattr(database, "registrar_pendencias_revisao", None)
        if not register:
            return
        groups = (
            (disabled_alerts, "loja_desabilitada", "Loja desabilitada para envio."),
            (stale_alerts, "oferta_vencida", "Oferta com mais de 24 horas; confirme antes de enviar."),
            (low_discount_alerts, "desconto_insuficiente", "Desconto abaixo do minimo; confirme antes de enviar."),
            (affiliate_pending, "link_afiliado", "Link afiliado oficial ainda nao foi validado."),
            (image_pending, "imagem", "Produto sem imagem valida para a notificacao."),
            (unrouted_alerts, "categoria", "Categoria ou grupo de destino nao identificado."),
        )
        for alerts, kind, reason in groups:
            if alerts:
                register(alerts, kind, reason)

    def offer_is_stale(self, item, max_age_hours):

        raw_date = str(self.value(item, "data", "") or "").strip()

        if not raw_date:
            return False

        try:
            offer_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            if offer_date.tzinfo is None:
                offer_date = offer_date.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - offer_date.astimezone(timezone.utc)
            return age.total_seconds() > max_age_hours * 3600
        except ValueError:
            return True

    def discount_percent(self, item):

        current_price = self.value(item, "preco_valor")
        old_price = self.comparison_price(item)

        if not current_price or not old_price or old_price <= current_price:
            return 0.0

        return ((old_price - current_price) / old_price) * 100

    def prioritize_affiliate_queue(self, items):

        with_image = []
        without_image = []

        for item in items:
            image = str(self.value(item, "imagem", "") or "").strip()
            target = with_image if image.startswith("http") else without_image
            target.append(item)

        with_image.sort(key=self.offer_priority_key)

        return with_image, without_image

    def offer_priority_key(self, item):

        current = self.price_number(self.value(item, "preco_valor"))
        previous = self.comparison_price(item)
        saving = max(previous - current, 0) if current > 0 else 0

        return (
            -self.discount_percent(item),
            -saving,
            current if current > 0 else float("inf"),
        )

    def apply_hourly_limit(self, alerts, database):

        limit = int(self.float_env("MAX_NOTIFICATIONS_PER_HOUR"))

        if limit <= 0 or database is None:
            return list(alerts), []

        recent = database.contar_envios_recentes(60, "WhatsApp")
        available = max(limit - int(recent), 0)

        return list(alerts[:available]), list(alerts[available:])

    def skipped_summary(
        self,
        disabled,
        stale,
        low_discount,
        affiliate_pending,
        rate_limited,
        unrouted=None,
        image_pending=None,
    ):

        reasons = []
        if disabled:
            reasons.append(f"{len(disabled)} de lojas desabilitadas")
        if stale:
            reasons.append(f"{len(stale)} ofertas com mais de 24 horas")
        if low_discount:
            reasons.append(f"{len(low_discount)} abaixo do desconto minimo")
        if affiliate_pending:
            reasons.append(f"{len(affiliate_pending)} aguardando link afiliado")
        if image_pending:
            reasons.append(f"{len(image_pending)} sem imagem valida")
        if rate_limited:
            reasons.append(f"{len(rate_limited)} aguardando limite horario")
        if unrouted:
            diagnostics = [
                self.category_routing_diagnostic(item)
                for item in unrouted
            ]
            technical = ", ".join(dict.fromkeys(
                diagnostic["reason"] for diagnostic in diagnostics
            ))
            reasons.append(
                f"{len(unrouted)} sem categoria segura ({technical})"
            )

        return " | ".join(reasons) or "nenhum produto elegivel"

    def partition_whatsapp_routable(self, alerts):

        if not self.whatsapp_category_groups():
            return list(alerts), []
        ready = []
        unrouted = []
        for alert in alerts:
            target = ready if self.whatsapp_recipients_for_alert(alert) else unrouted
            target.append(alert)
        return ready, unrouted

    def float_env(self, name, default=0):

        try:
            return float(os.getenv(name, str(default)) or default)
        except ValueError:
            return float(default)

    def within_notification_hours(self):

        start_hour = int(self.float_env("NOTIFICATION_START_HOUR"))
        end_hour = int(self.float_env("NOTIFICATION_END_HOUR")) or 24
        current_hour = datetime.now().hour

        if start_hour == end_hour:
            return True

        if start_hour < end_hour:
            return start_hour <= current_hour < end_hour

        return current_hour >= start_hour or current_hour < end_hour

    def wait_between_notifications(self):

        minimum = max(self.float_env("MIN_NOTIFICATION_INTERVAL_SECONDS"), 0)
        maximum = max(self.float_env("MAX_NOTIFICATION_INTERVAL_SECONDS"), minimum)

        if maximum > 0:
            time.sleep(random.uniform(minimum, maximum))

    def record_deliveries(self, database, alerts, channels):

        if self.transactional_delivery_enabled():
            return

        for alert in alerts:
            original_link = self.value(alert, "link", "") or ""
            affiliate_link = self.affiliate_link(alert)
            label = database.etiqueta_link_afiliado(original_link)
            label = label if isinstance(label, str) else ""

            for channel in channels:
                destinations = (
                    self.whatsapp_recipients_for_alert(alert)
                    if channel == "WhatsApp"
                    else [os.getenv("TELEGRAM_CHAT_ID", "")]
                )
                destinations = list(dict.fromkeys(destinations))
                for destination in destinations:
                    database.registrar_envio(
                        self.value(alert, "loja", "") or "",
                        self.value(alert, "titulo", "") or "",
                        original_link,
                        affiliate_link,
                        label,
                        channel,
                        destination,
                    )

    def record_single_delivery(self, database, alert, channel, destination):

        original_link = self.value(alert, "link", "") or ""
        affiliate_link = self.affiliate_link(alert)
        label = database.etiqueta_link_afiliado(original_link)
        label = label if isinstance(label, str) else ""
        database.registrar_envio(
            self.value(alert, "loja", "") or "",
            self.value(alert, "titulo", "") or "",
            original_link,
            affiliate_link,
            label,
            channel,
            destination,
        )

    def format_alert(self, item):

        return "\n".join([
            self.random_headline(),
            "",
            "\U0001f4f1 Produto:",
            str(self.value(item, "titulo", "") or ""),
            "",
            "\U0001f3ea Loja:",
            str(self.value(item, "loja", "") or ""),
            "",
            *self.offer_price_lines(item),
            "\U0001f6d2 Compre aqui:",
            *self.link_lines(item),
        ]).strip()

    def offer_price_lines(self, item):

        current_price = self.value(item, "preco_valor")
        old_price = self.comparison_price(item)
        current_text = (
            self.format_money(current_price)
            if current_price is not None
            else f"R$ {self.value(item, 'preco')}"
        )
        lines = []

        if old_price and current_price is not None and old_price > current_price:
            saving = old_price - current_price
            discount = (saving / old_price) * 100
            discount_text = f"{discount:.1f}".replace(".0", "").replace(".", ",")
            lines.extend([
                "\u274c Pre\u00e7o anterior:",
                f"De: {self.format_money(old_price)}",
                "",
            ])

        lines.extend([
            "\u2705 Pre\u00e7o promocional:",
            f"Por: {current_text}",
            "",
        ])

        if old_price and current_price is not None and old_price > current_price:
            lines.extend([
                "\U0001f4b0 Voc\u00ea economiza:",
                f"{self.format_money(saving)} \u2014 desconto de {discount_text}%",
                "",
            ])

        return lines

    def comparison_price(self, item):

        candidates = (
            self.value(item, "preco_antigo"),
            self.value(item, "maior_preco"),
        )

        for candidate in candidates:
            value = self.price_number(candidate)
            if value > 0:
                return value

        if self.database is None:
            return 0.0

        loader = getattr(self.database, "maior_preco_historico", None)
        if not callable(loader):
            return 0.0

        try:
            value = loader(
                self.value(item, "id"),
                self.value(item, "link", "") or "",
            )
            return self.price_number(value)
        except Exception:
            return 0.0

    @staticmethod
    def price_number(value):

        if isinstance(value, (int, float)):
            return float(value)

        text = str(value or "").strip()
        if not text:
            return 0.0

        text = re.sub(r"[^\d,.-]", "", text)
        if "," in text:
            text = text.replace(".", "").replace(",", ".")

        try:
            return float(text)
        except (TypeError, ValueError):
            return 0.0

    def random_headline(self):

        if not self._headline_queue:
            self._headline_queue = list(self.ALERT_HEADLINES)
            random.shuffle(self._headline_queue)

            if (
                self._last_headline
                and self._headline_queue[-1] == self._last_headline
            ):
                self._headline_queue[0], self._headline_queue[-1] = (
                    self._headline_queue[-1],
                    self._headline_queue[0],
                )

        self._last_headline = self._headline_queue.pop()

        return self._last_headline

    def link_lines(self, item):

        link = self.affiliate_link(item)
        lines = [link]

        storefront = os.getenv("SHOPEE_AFFILIATE_STOREFRONT", "").strip()

        if self.is_shopee(item) and storefront and storefront != link:
            lines.extend([
                "",
                "Mais achadinhos da ViVi na vitrine da Shopee:",
                storefront,
            ])

        storefront = os.getenv("MERCADOLIVRE_AFFILIATE_STOREFRONT", "").strip()

        if self.is_mercado_livre(item) and storefront and storefront != link:
            lines.extend([
                "",
                "Mais achadinhos da ViVi no Mercado Livre:",
                storefront,
            ])

        return lines

    def affiliate_link(self, item):

        link = self.value(item, "link", "") or ""

        saved_in_query = self.value(item, "link_afiliado_salvo", "")
        if isinstance(saved_in_query, str) and saved_in_query.strip():
            return saved_in_query.strip()

        if self.database is not None and self.requires_affiliate_link(item):
            saved_link = self.database.buscar_link_afiliado(link)

            if isinstance(saved_link, str) and saved_link.strip():
                return saved_link.strip()

        if self.is_mercado_livre(item):
            mapped = self.mapped_affiliate_link(
                link,
                os.getenv("MERCADOLIVRE_AFFILIATE_MAP", "")
            )

            if mapped:
                return mapped

            template = os.getenv("MERCADOLIVRE_AFFILIATE_TEMPLATE", "").strip()

            if template:
                affiliate_id = os.getenv("MERCADOLIVRE_AFFILIATE_ID", "").strip()

                return template.format(
                    url=link,
                    url_encoded=quote(link, safe=""),
                    affiliate_id=affiliate_id,
                    product_id=self.product_id(link),
                )

            return link

        if not self.is_shopee(item):
            return link

        mapped = self.mapped_shopee_affiliate_link(
            link,
            os.getenv("SHOPEE_AFFILIATE_MAP", "")
        )

        if mapped:
            return mapped

        template = os.getenv("SHOPEE_AFFILIATE_TEMPLATE", "").strip()

        if not template:
            return link

        affiliate_id = os.getenv("SHOPEE_AFFILIATE_ID", "").strip()

        return template.format(
            url=link,
            url_encoded=quote(link, safe=""),
            affiliate_id=affiliate_id,
        )

    def partition_affiliate_ready(self, alerts):

        ready = []
        blocked = []

        for alert in alerts:
            if self.requires_affiliate_link(alert) and not self.has_affiliate_link(alert):
                blocked.append(alert)
            else:
                ready.append(alert)

        return ready, blocked

    def requires_affiliate_link(self, item):

        return (
            self.is_shopee(item)
            or self.is_mercado_livre(item)
            or self.is_amazon(item)
        )

    def has_affiliate_link(self, item):

        original = (self.value(item, "link", "") or "").strip()
        affiliate = self.affiliate_link(item).strip()

        return bool(affiliate and affiliate != original)

    def mapped_shopee_affiliate_link(self, link, mapping):

        keys = self.shopee_mapping_keys(link)

        for key, value in self.mapping_entries(mapping):

            if key in keys:
                return value

        return ""

    def shopee_mapping_keys(self, link):

        keys = {self.normalize_url(link)}

        short_match = re.search(
            r"(?:br\.shp\.ee|s\.shopee\.com\.br)/([^/?#]+)",
            link or "",
            re.IGNORECASE
        )

        if short_match:
            keys.add(short_match.group(1))

        item_match = re.search(r"(?:fromItem=|-i\.\d+\.)(\d+)", link or "")

        if item_match:
            keys.add(item_match.group(1))

        return {key for key in keys if key}

    def is_shopee(self, item):

        loja = (self.value(item, "loja", "") or "").strip().lower()
        link = (self.value(item, "link", "") or "").strip().lower()

        return loja == "shopee" or "shopee.com.br" in link

    def is_mercado_livre(self, item):

        loja = (self.value(item, "loja", "") or "").strip().lower()
        link = (self.value(item, "link", "") or "").strip().lower()

        return (
            loja == "mercado livre"
            or "mercadolivre.com" in link
            or "produto.mercadolivre.com" in link
        )

    def is_amazon(self, item):

        loja = (self.value(item, "loja", "") or "").strip().lower()
        link = (self.value(item, "link", "") or "").strip().lower()

        return (
            loja == "amazon"
            or "amazon.com.br" in link
            or "amzn.to" in link
        )

    def mapped_affiliate_link(self, link, mapping):

        product_id = self.product_id(link)

        if not product_id:
            return ""

        for key, value in self.mapping_entries(mapping):

            if key.upper() == product_id:
                return value

        return ""

    def mapping_entries(self, mapping):

        entries = re.split(r"[\n;]+", mapping or "")

        for entry in entries:

            if "=" not in entry:
                continue

            key, value = entry.split("=", 1)
            key = self.normalize_url(key.strip())
            value = value.strip()

            if key and value:
                yield key, value

    def normalize_url(self, value):

        value = (value or "").strip()

        if not value.startswith("http"):
            return value

        return value.split("#", 1)[0].split("?", 1)[0].rstrip("/")

    def product_id(self, link):

        match = re.search(r"(MLB\d+)", link or "", re.IGNORECASE)

        if not match:
            return ""

        return match.group(1).upper()

    def format_price_lines(self, item):

        current_price = self.value(item, "preco_valor")
        old_price = self.comparison_price(item)

        if current_price is None:
            return [f"Preco de promocao: R$ {self.value(item, 'preco')}"]

        current_text = self.format_money(current_price)

        if old_price and old_price > current_price:
            saving = old_price - current_price
            discount = (saving / old_price) * 100

            return [
                f"Preco antigo: ~{self.format_money(old_price)}~",
                f"Preco de promocao: {current_text}",
                f"Voce economiza: {self.format_money(saving)} ({discount:.1f}%)",
            ]

        return [f"Preco de promocao: {current_text}"]

    def format_money(self, value):

        formatted = f"{float(value):,.2f}".translate(
            str.maketrans({",": ".", ".": ","})
        )
        return f"R$ {formatted}"

    def send_telegram_alerts(self, alerts):

        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not token or not chat_id:
            return False

        canary = self.transactional_canary_config()
        if canary.active(self.transactional_delivery_enabled()):
            return self.send_telegram_canary_alerts(
                alerts,
                token,
                chat_id,
                canary,
            )

        if self.transactional_delivery_enabled():
            results = []
            service = self.transactional_delivery_service()
            try:
                for item in alerts[:10]:
                    imagem = (self.value(item, "imagem", "") or "").strip()
                    if not imagem.startswith("http"):
                        continue
                    delivery = self.transactional_delivery(
                        item,
                        "Telegram",
                        chat_id,
                    )
                    results.append(service.deliver(
                        delivery,
                        send=lambda item=item, imagem=imagem: (
                            self.send_telegram_photo(
                                token,
                                chat_id,
                                imagem,
                                self.format_alert(item),
                            )
                        ),
                        record_history=lambda item=item: (
                            self.record_single_delivery(
                                self.database,
                                item,
                                "Telegram",
                                chat_id,
                            )
                        ),
                        sanitized_metadata={
                            "content_type": "image/url",
                            "destination_masked": (
                                mask_delivery_destination(chat_id)
                            ),
                        },
                    ))
                return DeliveryBatchResult(tuple(results))
            finally:
                self.close_transactional_delivery()

        enviados = 0

        for item in alerts[:10]:

            message = self.format_alert(item)
            imagem = (self.value(item, "imagem", "") or "").strip()

            if not imagem.startswith("http"):
                continue

            self.send_telegram_photo(token, chat_id, imagem, message)

            enviados += 1

        return enviados > 0

    def send_telegram_canary_alerts(self, alerts, token, chat_id, canary):

        results = []
        service = None
        try:
            for item in alerts[:10]:
                imagem = (self.value(item, "imagem", "") or "").strip()
                if not imagem.startswith("http"):
                    continue
                send = lambda item=item, imagem=imagem: (
                    self.send_telegram_photo(
                        token,
                        chat_id,
                        imagem,
                        self.format_alert(item),
                    )
                )
                if canary.authorizes(chat_id):
                    service = service or self.transactional_delivery_service()
                    results.append(service.deliver(
                        self.transactional_delivery(
                            item,
                            "Telegram",
                            chat_id,
                        ),
                        send=send,
                        record_history=lambda item=item: (
                            self.record_single_delivery(
                                self.database,
                                item,
                                "Telegram",
                                chat_id,
                            )
                        ),
                        sanitized_metadata={
                            "content_type": "image/url",
                            "destination_masked": (
                                mask_delivery_destination(chat_id)
                            ),
                        },
                    ))
                else:
                    results.append(self.deliver_legacy_destination(
                        item,
                        "Telegram",
                        chat_id,
                        send,
                    ))
            return DeliveryBatchResult(tuple(results))
        finally:
            if service is not None:
                self.close_transactional_delivery()

    def send_whatsapp_alerts(self, alerts):

        if not self.whatsapp_configured():
            return False

        canary = self.transactional_canary_config()
        if canary.active(self.transactional_delivery_enabled()):
            return self.send_whatsapp_canary_alerts(alerts, canary)

        if self.transactional_delivery_enabled():
            results = []
            service = self.transactional_delivery_service()
            try:
                for index, item in enumerate(alerts[:10]):
                    if index > 0:
                        self.wait_between_notifications()
                    imagem_original = self.verified_whatsapp_image(item)
                    imagem_preparada = self.value(item, "imagem_whatsapp")
                    imagem = (
                        imagem_preparada
                        if self.evolution_configured() and imagem_preparada
                        else imagem_original
                    )
                    if not (
                        isinstance(imagem, (bytes, bytearray))
                        or str(imagem).startswith("http")
                    ):
                        continue
                    for recipient in self.whatsapp_recipients_for_alert(item):
                        if self.whatsapp_group_rate_limited(recipient):
                            continue
                        delivery = self.transactional_delivery(
                            item,
                            "WhatsApp",
                            recipient,
                        )
                        results.append(service.deliver(
                            delivery,
                            send=lambda item=item, imagem=imagem,
                            recipient=recipient: self.send_whatsapp_message(
                                self.format_alert(item),
                                imagem,
                                recipient,
                            ),
                            record_history=lambda item=item,
                            recipient=recipient: self.record_single_delivery(
                                self.database,
                                item,
                                "WhatsApp",
                                recipient,
                            ),
                            sanitized_metadata={
                                "content_type": (
                                    "image/bytes"
                                    if isinstance(imagem, (bytes, bytearray))
                                    else "image/url"
                                ),
                                "size_bytes": (
                                    len(imagem)
                                    if isinstance(imagem, (bytes, bytearray))
                                    else 0
                                ),
                                "destination_masked": (
                                    mask_delivery_destination(recipient)
                                ),
                            },
                        ))
                return DeliveryBatchResult(tuple(results))
            finally:
                self.close_transactional_delivery()

        enviados = 0

        for index, item in enumerate(alerts[:10]):

            if index > 0:
                self.wait_between_notifications()

            imagem_original = self.verified_whatsapp_image(item)
            imagem_preparada = self.value(item, "imagem_whatsapp")
            imagem = (
                imagem_preparada
                if self.evolution_configured() and imagem_preparada
                else imagem_original
            )
            if not (
                isinstance(imagem, (bytes, bytearray))
                or str(imagem).startswith("http")
            ):
                logger.warning(
                    "Envio bloqueado: nao foi possivel confirmar a imagem "
                    "do produto %s.",
                    self.value(item, "link", ""),
                )
                continue

            for recipient in self.whatsapp_recipients_for_alert(item):
                if self.whatsapp_group_rate_limited(recipient):
                    continue
                self.send_whatsapp_message(self.format_alert(item), imagem, recipient)
                enviados += 1

        return enviados > 0

    def send_whatsapp_canary_alerts(self, alerts, canary):

        results = []
        service = None
        try:
            for index, item in enumerate(alerts[:10]):
                if index > 0:
                    self.wait_between_notifications()
                imagem_original = self.verified_whatsapp_image(item)
                imagem_preparada = self.value(item, "imagem_whatsapp")
                imagem = (
                    imagem_preparada
                    if self.evolution_configured() and imagem_preparada
                    else imagem_original
                )
                if not (
                    isinstance(imagem, (bytes, bytearray))
                    or str(imagem).startswith("http")
                ):
                    logger.warning(
                        "Envio bloqueado: nao foi possivel confirmar a imagem "
                        "do produto %s.",
                        self.value(item, "link", ""),
                    )
                    continue
                for recipient in self.whatsapp_recipients_for_alert(item):
                    if self.whatsapp_group_rate_limited(recipient):
                        continue
                    send = lambda item=item, imagem=imagem, recipient=recipient: (
                        self.send_whatsapp_message(
                            self.format_alert(item),
                            imagem,
                            recipient,
                        )
                    )
                    if canary.authorizes(recipient):
                        service = service or self.transactional_delivery_service()
                        results.append(service.deliver(
                            self.transactional_delivery(
                                item,
                                "WhatsApp",
                                recipient,
                            ),
                            send=send,
                            record_history=lambda item=item,
                            recipient=recipient: self.record_single_delivery(
                                self.database,
                                item,
                                "WhatsApp",
                                recipient,
                            ),
                            sanitized_metadata={
                                "content_type": (
                                    "image/bytes"
                                    if isinstance(imagem, (bytes, bytearray))
                                    else "image/url"
                                ),
                                "size_bytes": (
                                    len(imagem)
                                    if isinstance(imagem, (bytes, bytearray))
                                    else 0
                                ),
                                "destination_masked": (
                                    mask_delivery_destination(recipient)
                                ),
                            },
                        ))
                    else:
                        results.append(self.deliver_legacy_destination(
                            item,
                            "WhatsApp",
                            recipient,
                            send,
                        ))
            return DeliveryBatchResult(tuple(results))
        finally:
            if service is not None:
                self.close_transactional_delivery()

    def verified_whatsapp_image(self, item):
        """Confirma na Shopee que a foto pertence ao ID do anúncio.

        Os cartões da busca da Shopee são atualizados dinamicamente e podem
        reutilizar temporariamente a foto de outro cartão. A API do próprio
        anúncio usa os IDs presentes no link e evita esse desalinhamento.
        """

        current = str(self.value(item, "imagem", "") or "").strip()
        if self.value(item, "imagem_manual", False):
            return current
        store = str(self.value(item, "loja", "") or "").casefold()
        link = str(self.value(item, "link", "") or "").strip()

        if "shopee" not in store and "shopee.com.br" not in link.casefold():
            return current

        match = (
            re.search(r"-i\.(\d+)\.(\d+)(?:[/?#]|$)", link)
            or re.search(r"/product/(\d+)/(\d+)(?:[/?#]|$)", link)
        )
        if not match:
            return ""

        shop_id, item_id = match.groups()
        try:
            response = requests.get(
                "https://shopee.com.br/api/v4/pdp/get_pc",
                params={"shop_id": shop_id, "item_id": item_id},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                    ),
                    "Referer": link,
                },
                timeout=15,
            )
            response.raise_for_status()
            product = (response.json().get("data") or {}).get("item") or {}
            image = product.get("image") or ""
            if not image:
                images = product.get("images") or []
                image = images[0] if images else ""
            image = str(image).strip()
            if image and not image.startswith("http"):
                image = f"https://down-br.img.susercontent.com/file/{image}"
            if not image.startswith(("http://", "https://")):
                return self.verified_shopee_cdn_image(current, link)

            product_id = self.value(item, "id")
            updater = (
                getattr(self.database, "atualizar_imagem_produto", None)
                if self.database is not None else None
            )
            if updater and product_id:
                updater(product_id, image)
            return image
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            # A API de produto pode responder 403 mesmo com a página e o CDN
            # públicos. Nesse caso, aceite somente a imagem que veio do mesmo
            # cartão do anúncio e que o CDN oficial confirmar como imagem.
            return self.verified_shopee_cdn_image(current, link)

    @staticmethod
    def verified_shopee_cdn_image(image_url, product_link):

        image_url = str(image_url or "").strip()
        product_link = str(product_link or "").strip()
        image_host = (urlparse(image_url).hostname or "").casefold()

        if (
            not re.search(r"-i\.\d+\.\d+(?:[/?#]|$)", product_link)
            or not image_url.startswith("https://")
            or not (
                image_host == "susercontent.com"
                or image_host.endswith(".susercontent.com")
            )
        ):
            return ""

        try:
            response = requests.get(
                image_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://shopee.com.br/",
                },
                stream=True,
                timeout=15,
            )
            response.raise_for_status()
            content_type = str(
                response.headers.get("Content-Type") or ""
            ).casefold()
            return image_url if content_type.startswith("image/") else ""
        except requests.RequestException:
            return ""
        finally:
            if "response" in locals():
                response.close()

    @staticmethod
    def best_image_url_candidates(image_url):
        image_url = str(image_url or "").strip()
        if not image_url:
            return []
        host = (urlparse(image_url).hostname or "").casefold()
        candidates = []
        if host == "susercontent.com" or host.endswith(".susercontent.com"):
            original = re.sub(
                r"@resize_[^/?#]+(?=(?:[?#]|$))",
                "",
                image_url,
                count=1,
                flags=re.IGNORECASE,
            )
            if original != image_url:
                candidates.append(original)
        candidates.append(image_url)
        return list(dict.fromkeys(candidates))

    def download_image(self, image_url):
        last_error = None
        for candidate in self.best_image_url_candidates(image_url):
            response = None
            try:
                response = requests.get(
                    candidate,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                        ),
                        "Referer": "https://shopee.com.br/",
                        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                    },
                    stream=True,
                    timeout=(10, 30),
                )
                if response.status_code != 200:
                    raise ValueError(
                        f"A imagem respondeu com HTTP {response.status_code}."
                    )
                content_type = str(
                    response.headers.get("Content-Type") or ""
                ).casefold()
                if not content_type.startswith("image/"):
                    raise ValueError(
                        "A URL informada nao retornou conteudo de imagem."
                    )
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_size = int(content_length)
                    except (TypeError, ValueError):
                        declared_size = 0
                    if declared_size > self.MAX_MANUAL_IMAGE_BYTES:
                        raise ValueError("A imagem excede o limite de 15 MiB.")
                content = bytearray()
                for chunk in response.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    content.extend(chunk)
                    if len(content) > self.MAX_MANUAL_IMAGE_BYTES:
                        raise ValueError("A imagem excede o limite de 15 MiB.")
                if not content:
                    raise ValueError("O arquivo de imagem esta vazio.")
                return candidate, bytes(content)
            except requests.Timeout as error:
                last_error = ValueError(
                    "O download da imagem excedeu o tempo limite."
                )
                last_error.__cause__ = error
            except requests.ConnectionError as error:
                last_error = ValueError(
                    "Nao foi possivel conectar ao servidor da imagem."
                )
                last_error.__cause__ = error
            except (requests.RequestException, ValueError) as error:
                last_error = (
                    error
                    if isinstance(error, ValueError)
                    else ValueError(f"Falha ao baixar a imagem: {error}")
                )
            finally:
                if response is not None:
                    response.close()
        raise last_error or ValueError("Nao foi possivel baixar a imagem.")

    def prepare_whatsapp_image(self, image_url, allow_low_resolution=False):

        resolved_url, original = self.download_image(image_url)
        try:
            image = Image.open(BytesIO(original))
            image.load()
        except (
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombError,
        ) as error:
            raise ValueError(
                "O arquivo recebido nao e uma imagem valida."
            ) from error

        original_format = image.format
        image = ImageOps.exif_transpose(image)
        width, height = image.size
        if (
            width < self.MIN_MANUAL_IMAGE_WIDTH
            or height < self.MIN_MANUAL_IMAGE_HEIGHT
        ):
            error = LowResolutionImageError(
                f"A imagem possui {width} x {height} pixels.\n\n"
                "O minimo recomendado e 500 x 500 pixels para garantir "
                "boa qualidade no WhatsApp.",
                resolved_url,
                width,
                height,
            )
            if not allow_low_resolution:
                raise error

        if original_format == "JPEG":
            return original

        has_transparency = (
            image.mode in {"RGBA", "LA"}
            or (
                image.mode == "P"
                and "transparency" in image.info
            )
        )
        if has_transparency:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", image.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")

        output = BytesIO()
        image.save(
            output,
            format="JPEG",
            quality=90,
            subsampling=0,
            optimize=True,
        )
        return output.getvalue()

    def is_unmissable_offer(self, item):

        current = self.value(item, "preco_valor")
        old_price = self.comparison_price(item)
        try:
            current = float(current)
            old_price = float(old_price)
        except (TypeError, ValueError):
            return False

        if current <= 0 or old_price <= current:
            return False

        discount = ((old_price - current) / old_price) * 100
        saving = old_price - current
        minimum_discount = self.float_env(
            "PERSONAL_ALERT_MIN_DISCOUNT_PERCENT", 60
        )
        maximum_discount = self.float_env(
            "PERSONAL_ALERT_MAX_DISCOUNT_PERCENT", 90
        )
        minimum_saving = self.float_env(
            "PERSONAL_ALERT_MIN_SAVINGS", 50
        )
        minimum_price = self.float_env(
            "PERSONAL_ALERT_MIN_PRICE", 5
        )

        return (
            bool(self.personal_alert_phones())
            and current >= minimum_price
            and discount >= minimum_discount
            and (maximum_discount <= 0 or discount <= maximum_discount)
            and saving >= minimum_saving
        )

    def format_personal_alert(self, item):

        return (
            "\U0001f6a8 OFERTA IMPERDIVEL — COPIA PESSOAL\n"
            "Esta oferta tambem foi encaminhada aos grupos.\n\n"
            + self.format_alert(item)
        )

    def whatsapp_group_rate_limited(self, recipient):

        limit = int(self.float_env("MAX_NOTIFICATIONS_PER_GROUP_PER_HOUR"))
        if limit <= 0 or self.database is None:
            return False
        counter = getattr(
            self.database, "contar_envios_destino_recentes", None
        )
        if not counter:
            return False
        try:
            recent = int(counter(recipient, 60, "WhatsApp"))
        except (TypeError, ValueError):
            return False
        return recent >= limit

    def whatsapp_configured(self):

        provider = os.getenv("WHATSAPP_PROVIDER", "").strip().lower()

        if provider == "evolution" or self.evolution_configured():
            return self.evolution_configured()

        if provider == "zapi" or self.zapi_configured():
            return self.zapi_configured()

        return bool(os.getenv("WHATSAPP_WEBHOOK_URL") and self.whatsapp_phones())

    def evolution_configured(self):

        return all([
            os.getenv("EVOLUTION_API_URL"),
            os.getenv("EVOLUTION_INSTANCE"),
            os.getenv("EVOLUTION_API_KEY"),
            self.whatsapp_recipients(),
        ])

    def whatsapp_connection_health(self):

        if not self.evolution_configured():
            return False, "Evolution API não configurada"
        api_url = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
        instance = os.getenv("EVOLUTION_INSTANCE")
        try:
            response = requests.get(
                f"{api_url}/instance/connectionState/{instance}",
                headers={"apikey": os.getenv("EVOLUTION_API_KEY", "")},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            state = str(
                data.get("instance", {}).get("state")
                or data.get("state") or data.get("status") or ""
            ).lower()
            connected = state in {"open", "connected", "online"}
            return connected, state or "estado desconhecido"
        except Exception as error:
            return False, str(error)

    def zapi_configured(self):

        return all([
            os.getenv("ZAPI_INSTANCE_ID"),
            os.getenv("ZAPI_INSTANCE_TOKEN"),
            os.getenv("ZAPI_CLIENT_TOKEN"),
            self.whatsapp_phones(),
        ])

    def whatsapp_recipients(self):

        recipients = self.whatsapp_groups() + self.whatsapp_phones()
        recipients.extend(self.whatsapp_category_groups().values())
        recipients.extend(self.personal_alert_phones())
        return list(dict.fromkeys(recipients))[:10]

    def whatsapp_category_groups(self):

        keys = {
            "mamae_bebe": "WHATSAPP_GROUP_MAMAE_BEBE",
            "casa_enxoval": "WHATSAPP_GROUP_CASA_ENXOVAL",
            "eletrodomesticos": "WHATSAPP_GROUP_ELETRODOMESTICOS",
            "smartphones_tecnologia": "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA",
            "beleza_perfumaria": "WHATSAPP_GROUP_BELEZA_PERFUMARIA",
            "limpeza_utilidades": "WHATSAPP_GROUP_LIMPEZA_UTILIDADES",
        }
        return {
            category: os.getenv(env_name, "").strip()
            for category, env_name in keys.items()
            if os.getenv(env_name, "").strip()
        }

    def whatsapp_category(self, item):

        manual_category = str(
            self.value(item, "categoria_manual", "") or ""
        ).strip()
        if manual_category in self.WHATSAPP_CATEGORY_KEYWORDS:
            return manual_category

        if self.is_mercado_livre(item):
            mercado_livre_category, _trace = (
                self.detect_mercado_livre_category(item)
            )
            if mercado_livre_category:
                return mercado_livre_category

        text = self.searchable_text(" ".join([
            str(self.value(item, "titulo", "") or ""),
            str(self.value(item, "termo", "") or ""),
        ]))

        keywords_by_category = dict(self.WHATSAPP_CATEGORY_KEYWORDS)
        if self.database is not None:
            loader = getattr(self.database, "listar_palavras_categorias", None)
            custom = loader() if loader else {}
            for category, keywords in custom.items():
                if keywords:
                    keywords_by_category[category] = tuple(keywords)

        for category, keywords in keywords_by_category.items():
            if any(self.searchable_text(keyword) in text for keyword in keywords):
                return category

        return None

    def detect_mercado_livre_category(self, item):
        """Adaptação exclusiva para a taxonomia da página Mercado Livre."""

        breadcrumb = str(
            self.value(item, "breadcrumb", "") or ""
        ).strip()
        original = str(
            self.value(item, "categoria_original", "") or ""
        ).strip()
        category_text = self.searchable_text(
            " ".join(value for value in (breadcrumb, original) if value)
        )
        trace = {
            "function": "Notifier.detect_mercado_livre_category",
            "rule": "MERCADO_LIVRE_BREADCRUMB_KEYWORDS",
            "breadcrumb": breadcrumb,
            "original_category": original,
            "comparison": "",
        }
        if not category_text:
            trace["comparison"] = "breadcrumb_and_original_category_empty"
            return None, trace
        keywords_by_category = dict(self.WHATSAPP_CATEGORY_KEYWORDS)
        if self.database is not None:
            loader = getattr(self.database, "listar_palavras_categorias", None)
            custom = loader() if loader else {}
            for category, keywords in custom.items():
                if keywords:
                    keywords_by_category[category] = tuple(keywords)
        comparisons = []
        for category, keywords in keywords_by_category.items():
            matched = next((
                keyword for keyword in keywords
                if self.searchable_text(keyword) in category_text
            ), None)
            if matched:
                trace["comparison"] = (
                    f"matched:{category}:{self.searchable_text(matched)}"
                )
                return category, trace
            comparisons.append(category)
        trace["comparison"] = (
            "no_keyword_match_in:" + ",".join(comparisons)
        )
        return None, trace

    def category_routing_diagnostic(self, item):
        """Explica o roteamento sem aprovar ou modificar categorias."""

        raw_manual = str(
            self.value(item, "categoria_manual", "") or ""
        ).strip()
        ml_trace = None
        if self.is_mercado_livre(item):
            _ml_category, ml_trace = self.detect_mercado_livre_category(item)
        detected = self.whatsapp_category(item)
        source = (
            "MANUAL_CATEGORY"
            if raw_manual and detected == raw_manual
            else "TITLE_KEYWORDS" if detected else "NOT_DETECTED"
        )
        groups = self.whatsapp_category_groups()
        general = self.whatsapp_groups() + self.whatsapp_phones()
        ml_received_category = bool(
            ml_trace and (
                ml_trace["breadcrumb"] or ml_trace["original_category"]
            )
        )
        if raw_manual and raw_manual not in self.WHATSAPP_CATEGORY_KEYWORDS:
            reason = "CATEGORY_NOT_MAPPED"
        elif self.is_mercado_livre(item) and not detected and ml_received_category:
            reason = "CATEGORY_NOT_MAPPED"
        elif not detected:
            reason = "CATEGORY_NOT_DETECTED"
        elif detected not in self.WHATSAPP_CATEGORY_KEYWORDS:
            reason = "CATEGORY_NORMALIZATION_FAILED"
        elif groups and detected not in groups:
            reason = "CATEGORY_WITHOUT_DESTINATION"
        elif not groups and not general:
            reason = "CATEGORY_WITHOUT_DESTINATION"
        else:
            reason = "READY"
        destination = groups.get(detected, "") if detected else ""
        if not destination and general:
            destination = general[0]
        diagnostic = {
            "detected_category": (
                raw_manual
                or detected
                or (
                    ml_trace["original_category"]
                    if ml_trace else ""
                )
                or (
                    ml_trace["breadcrumb"]
                    if ml_trace else ""
                )
            ),
            "canonical_category": detected or "",
            "source": source,
            "reason": reason,
            "destination_configured": bool(destination),
            "breadcrumb": (
                ml_trace["breadcrumb"] if ml_trace else ""
            ),
            "original_category": (
                ml_trace["original_category"] if ml_trace else ""
            ),
            "detector_function": (
                ml_trace["function"]
                if ml_trace else "Notifier.whatsapp_category"
            ),
            "applied_rule": (
                ml_trace["rule"]
                if ml_trace else "TITLE_OR_MANUAL_CATEGORY_KEYWORDS"
            ),
            "failed_comparison": (
                ml_trace["comparison"] if ml_trace else ""
            ),
        }
        logger.info(
            "category classification diagnostic: store=%s product=%s "
            "original_url=%s title=%s breadcrumb=%s original_category=%s "
            "detected_category=%s canonical_category=%s "
            "group_found=%s detector_function=%s applied_rule=%s "
            "comparison=%s rejection_reason=%s",
            str(self.value(item, "loja", "") or ""),
            str(self.value(item, "titulo", "") or ""),
            str(self.value(item, "link", "") or ""),
            str(self.value(item, "titulo", "") or ""),
            diagnostic["breadcrumb"] or "NOT_RECEIVED",
            diagnostic["original_category"] or "NOT_RECEIVED",
            diagnostic["detected_category"] or "NOT_DETECTED",
            diagnostic["canonical_category"] or "NOT_MAPPED",
            bool(destination),
            diagnostic["detector_function"],
            diagnostic["applied_rule"],
            diagnostic["failed_comparison"] or "NOT_APPLICABLE",
            reason,
        )
        return diagnostic

    def category_block_message(self, item):
        diagnostic = self.category_routing_diagnostic(item)
        title = str(self.value(item, "titulo", "") or "Produto").strip()
        store = str(self.value(item, "loja", "") or "Loja não informada").strip()
        detected = diagnostic["detected_category"] or "Não detectada"
        canonical = diagnostic["canonical_category"] or "Não atribuída"
        return "\n".join((
            "Envio bloqueado",
            "",
            f"Produto: {title}",
            f"Loja: {store}",
            f"Categoria detectada: {detected}",
            f"Categoria canônica: {canonical}",
            "Status: categoria ainda não está aprovada para envio.",
            f"Motivo técnico: {diagnostic['reason']}",
            "Ação recomendada: abra “Central Categorias”, revise a "
            "categoria e confirme um grupo de destino.",
        ))

    @staticmethod
    def searchable_text(value):
        """Normaliza caixa e acentos para classificar titulos com seguranca."""

        normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
        return "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )

    def whatsapp_recipients_for_alert(self, item):

        category_groups = self.whatsapp_category_groups()
        recipients = self.whatsapp_groups() + self.whatsapp_phones()
        if category_groups:
            category = self.whatsapp_category(item)
            recipient = category_groups.get(category)
            if recipient:
                recipients.append(recipient)
        return list(dict.fromkeys(recipients))[:10]

    def whatsapp_groups(self):

        groups = os.getenv("WHATSAPP_GROUPS", "")

        return [
            group.strip()
            for group in groups.split(",")
            if group.strip()
        ][:10]

    def whatsapp_phones(self):

        phones = os.getenv("WHATSAPP_PHONES") or os.getenv("WHATSAPP_PHONE", "")

        return [
            phone.strip()
            for phone in phones.split(",")
            if phone.strip()
        ][:10]

    def personal_alert_phones(self):

        phones = os.getenv("WHATSAPP_PERSONAL_ALERT_PHONES", "")
        normalized = []
        for phone in phones.split(","):
            digits = re.sub(r"\D", "", phone)
            if 12 <= len(digits) <= 13:
                normalized.append(digits)
        return list(dict.fromkeys(normalized))[:3]

    def value(self, item, key, default=None):

        try:
            return item[key]
        except Exception:
            return default

    def send_telegram_message(self, token, chat_id, message):

        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=30
        )
        response.raise_for_status()

        return True

    def send_telegram_photo(self, token, chat_id, photo, caption):

        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            json={
                "chat_id": chat_id,
                "photo": photo,
                "caption": caption[:1000],
            },
            timeout=30
        )
        response.raise_for_status()

        return True

    def send_whatsapp_message(self, message, image_url, phone):

        if self.evolution_configured():
            return self.send_evolution_image(message, image_url, phone)

        if self.zapi_configured():
            return self.send_zapi_image(message, image_url, phone)

        return self.send_whatsapp_webhook(message, image_url, phone)

    def send_evolution_image(self, message, image_url, phone):

        if (
            not isinstance(image_url, (bytes, bytearray))
            and str(image_url or "").startswith("http")
        ):
            image_url = self.prepare_whatsapp_image(image_url)
        api_url = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
        instance = os.getenv("EVOLUTION_INSTANCE")
        api_key = os.getenv("EVOLUTION_API_KEY")
        endpoint = f"{api_url}/message/sendMedia/{instance}"
        diagnostic_logger = self.evolution_diagnostic_logger()
        destination = str(phone or "")
        masked_destination = self.mask_evolution_destination(destination)
        self.validate_evolution_destination(destination)
        connected, connection_state = self.whatsapp_connection_health()
        if not connected:
            raise EvolutionSendError(
                "A instância da Evolution não está conectada "
                f"(estado: {connection_state})."
            )
        media_diagnostic = {
            "source": (
                "arquivo_validado"
                if isinstance(image_url, (bytes, bytearray))
                else "url_original"
            ),
            "file_name": "produto.jpg",
            "format": "desconhecido",
            "content_type": "application/json",
            "mime_type": "desconhecido",
            "width": 0,
            "height": 0,
            "size_bytes": (
                len(image_url)
                if isinstance(image_url, (bytes, bytearray))
                else 0
            ),
        }
        if isinstance(image_url, (bytes, bytearray)):
            media_bytes, detected = self.validate_evolution_media(
                bytes(image_url),
                "image/jpeg",
            )
            media_diagnostic.update(detected)
            media_value = base64.b64encode(media_bytes).decode("ascii")
        else:
            raise EvolutionSendError(
                "O arquivo de imagem não foi preparado para o envio."
            )

        request_kwargs = {
            "json": {
                "number": phone,
                "mediatype": "image",
                "mimetype": media_diagnostic["mime_type"],
                "caption": message[:1000],
                "media": media_value,
                "fileName": media_diagnostic["file_name"],
            },
            "headers": {
                "apikey": api_key,
                "Content-Type": "application/json",
            },
            "timeout": 30,
        }

        diagnostic_logger.warning(
            "Evolution API: status_http=pendente endpoint=%s "
            "content_type=%s file_name=%s size_bytes=%s format=%s "
            "dimensions=%sx%s destination=%s",
            endpoint,
            media_diagnostic["content_type"],
            media_diagnostic["file_name"],
            media_diagnostic["size_bytes"],
            media_diagnostic["format"],
            media_diagnostic["width"],
            media_diagnostic["height"],
            masked_destination,
        )
        response = None
        try:
            response = requests.post(
                endpoint,
                **request_kwargs,
            )
            try:
                response_json = response.json()
            except ValueError:
                response_json = None
            diagnostic_logger.warning(
                "Evolution API: destination=%s status_code=%s response=%r",
                masked_destination,
                response.status_code,
                self.summarize_evolution_response(response, response_json),
            )
            response.raise_for_status()
            return True
        except requests.HTTPError as error:
            if response is None:
                diagnostic_logger.exception(
                    "Evolution API: falha antes da resposta destination=%s "
                    "endpoint=%s media=%r",
                    masked_destination,
                    endpoint,
                    media_diagnostic,
                )
            else:
                try:
                    response_json = response.json()
                except ValueError:
                    response_json = None
                diagnostic_logger.exception(
                    "Evolution API: falha HTTP destination=%s endpoint=%s "
                    "status_code=%s response=%r media=%r",
                    masked_destination,
                    endpoint,
                    response.status_code,
                    self.summarize_evolution_response(response, response_json),
                    media_diagnostic,
                )
            summary = self.summarize_evolution_response(
                response,
                response_json,
            )
            technical_cause = (
                summary.get("message")
                or summary.get("error")
                or summary.get("text")
                or "erro interno sem detalhes"
            )
            raise EvolutionSendError(
                "A Evolution recusou o envio da imagem "
                f"(HTTP {response.status_code}: {technical_cause}). "
                "Os dados foram preservados."
            ) from error
        except Exception:
            diagnostic_logger.exception(
                "Evolution API: falha antes da resposta destination=%s "
                "endpoint=%s media=%r",
                masked_destination,
                endpoint,
                media_diagnostic,
            )
            raise

    @staticmethod
    def mask_evolution_destination(destination):
        destination = str(destination or "")
        suffix = "@g.us" if destination.endswith("@g.us") else ""
        digits = re.sub(r"\D", "", destination)
        if not digits:
            return "nao informado"
        return f"***{digits[-4:]}{suffix}"

    @staticmethod
    def validate_evolution_destination(destination):
        destination = str(destination or "").strip()
        if destination.endswith("@g.us"):
            if re.fullmatch(r"\d{10,22}@g\.us", destination):
                return True
        elif re.fullmatch(r"\d{12,13}", destination):
            return True
        raise EvolutionSendError(
            "O destino configurado para a Evolution é inválido."
        )

    @staticmethod
    def validate_evolution_media(content, declared_mime):
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise EvolutionSendError(
                "O arquivo de imagem está vazio ou não existe."
            )
        try:
            with Image.open(BytesIO(bytes(content))) as inspected:
                inspected.verify()
            with Image.open(BytesIO(bytes(content))) as inspected:
                detected_format = str(inspected.format or "").upper()
                width, height = inspected.size
        except (UnidentifiedImageError, OSError) as error:
            raise EvolutionSendError(
                "O arquivo de imagem não pode ser aberto pelo Pillow."
            ) from error
        format_mimes = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
        }
        detected_mime = format_mimes.get(detected_format)
        if not detected_mime or detected_mime != declared_mime:
            raise EvolutionSendError(
                "O MIME informado não corresponde ao formato real do arquivo."
            )
        return bytes(content), {
            "format": detected_format.lower(),
            "mime_type": detected_mime,
            "width": width,
            "height": height,
            "size_bytes": len(content),
        }

    @staticmethod
    def summarize_evolution_response(response, response_json):
        if isinstance(response_json, dict):
            summary = {
                key: (
                    response_json.get(key)
                    if key == "status"
                    else Notifier.sanitize_evolution_text(
                        response_json.get(key)
                    )
                )
                for key in ("status", "error")
                if response_json.get(key) is not None
            }
            nested = response_json.get("response")
            if isinstance(nested, dict) and nested.get("message"):
                summary["message"] = Notifier.sanitize_evolution_text(
                    nested["message"]
                )
            return summary or {"result": "resposta JSON recebida"}
        return {
            "text": Notifier.sanitize_evolution_text(
                getattr(response, "text", "") or ""
            )
        }

    @staticmethod
    def sanitize_evolution_text(value):
        text = str(value or "").replace("\r", " ").replace("\n", " ")
        text = re.sub(
            r"(?i)\b(api[-_ ]?key|token|authorization|caption)"
            r"\b\s*[:=]\s*[^,;\s]+",
            r"\1=[REMOVIDO]",
            text,
        )
        text = re.sub(r"\b\d{10,22}(?:@g\.us)?\b", "***[DESTINO]", text)
        return text[:200]

    def send_zapi_image(self, message, image_url, phone):

        instance_id = os.getenv("ZAPI_INSTANCE_ID")
        instance_token = os.getenv("ZAPI_INSTANCE_TOKEN")
        client_token = os.getenv("ZAPI_CLIENT_TOKEN")

        response = requests.post(
            "https://api.z-api.io/instances/"
            f"{instance_id}/token/{instance_token}/send-image",
            json={
                "phone": phone,
                "image": image_url,
                "caption": message[:1000],
                "viewOnce": False,
            },
            headers={
                "Client-Token": client_token,
                "Content-Type": "application/json",
            },
            timeout=30
        )
        response.raise_for_status()

        return True

    def send_whatsapp_webhook(self, message, image_url, phone):

        webhook_url = os.getenv("WHATSAPP_WEBHOOK_URL")

        token = os.getenv("WHATSAPP_TOKEN")
        headers = {}

        if token:
            headers["Authorization"] = f"Bearer {token}"

        response = requests.post(
            webhook_url,
            json={
                "phone": phone,
                "message": message,
                "image_url": image_url,
            },
            headers=headers,
            timeout=30
        )
        response.raise_for_status()

        return True
