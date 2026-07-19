import os
import random
import re
import time
import logging
from datetime import datetime
from datetime import timezone
from urllib.parse import quote
from typing import Any, Optional

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class Notifier:

    ALWAYS_DISABLED_NOTIFICATION_STORES = {"amazon"}

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
            "memoria ram", "memória ram", "teclado", "mouse",
        ),
        "beleza_perfumaria": (
            "perfume", "perfumaria", "body splash", "maquiagem", "batom",
            "hidratante", "protetor solar", "shampoo", "condicionador",
            "mascara capilar", "máscara capilar", "secador", "chapinha",
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

    def __init__(self, database=None):

        load_dotenv()
        self.database = database
        self._last_headline = None
        self._headline_queue = []

    def configured_channels(self):

        channels = []

        if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
            channels.append("Telegram")

        if self.whatsapp_configured():
            channels.append("WhatsApp")

        return channels

    def send_alerts(self, alerts, database=None):

        if not alerts:
            return "Nenhum alerta disparado."

        if not self.within_notification_hours():
            return "Nenhum envio: fora do horario permitido (08h as 22h)."

        database = database or self.database

        if database is not None and self.database is None:
            self.database = database

        enabled_alerts, disabled_alerts = self.partition_enabled_stores(alerts)
        quality_alerts, stale_alerts, low_discount_alerts = (
            self.partition_offer_quality(enabled_alerts)
        )
        ready_alerts, blocked_alerts = self.partition_affiliate_ready(
            quality_alerts
        )
        telegram_alerts = list(ready_alerts)
        whatsapp_alerts, unrouted_alerts = self.partition_whatsapp_routable(
            ready_alerts
        )
        whatsapp_alerts, rate_limited_alerts = self.apply_hourly_limit(
            whatsapp_alerts,
            database,
        )

        if not telegram_alerts and not whatsapp_alerts:
            return "Nenhum envio: " + self.skipped_summary(
                disabled_alerts,
                stale_alerts,
                low_discount_alerts,
                blocked_alerts,
                rate_limited_alerts,
                unrouted_alerts,
            )

        sent = []
        errors = []
        delivered_alerts = []
        history_error = False

        try:
            if self.send_telegram_alerts(telegram_alerts):
                sent.append("Telegram")
                delivered_alerts.extend(telegram_alerts)
                if database is not None:
                    try:
                        self.record_deliveries(database, telegram_alerts, ["Telegram"])
                    except Exception:
                        history_error = True
        except Exception as error:
            errors.append(f"Telegram: {error}")

        try:
            if self.send_whatsapp_alerts(whatsapp_alerts):
                sent.append("WhatsApp")
                delivered_alerts.extend(whatsapp_alerts)
                if database is not None:
                    try:
                        self.record_deliveries(database, whatsapp_alerts, ["WhatsApp"])
                    except Exception:
                        history_error = True
        except Exception as error:
            errors.append(f"WhatsApp: {error}")

        if sent:
            if database is not None:
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
        )):
            return "Nenhum envio: " + self.skipped_summary(
                disabled_alerts,
                stale_alerts,
                low_discount_alerts,
                blocked_alerts,
                rate_limited_alerts,
                unrouted_alerts,
            )

        return "Configure WhatsApp no arquivo .env."

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
        old_price = self.value(item, "maior_preco")

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

        with_image.sort(key=lambda item: (
            -self.discount_percent(item),
            self.value(item, "preco_valor", float("inf")) or float("inf"),
        ))

        return with_image, without_image

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
        if rate_limited:
            reasons.append(f"{len(rate_limited)} aguardando limite horario")
        if unrouted:
            reasons.append(f"{len(unrouted)} sem categoria segura")

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

    def float_env(self, name):

        try:
            return float(os.getenv(name, "0") or 0)
        except ValueError:
            return 0.0

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
        old_price = self.value(item, "maior_preco")
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
                "Mais achadinhos da ViVi na Shopee:",
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

        return self.is_shopee(item) or self.is_mercado_livre(item)

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
        old_price = self.value(item, "maior_preco")

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

        return f"R$ {value:.2f}".replace(".", ",")

    def send_telegram_alerts(self, alerts):

        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not token or not chat_id:
            return False

        enviados = 0

        for item in alerts[:10]:

            message = self.format_alert(item)
            imagem = (self.value(item, "imagem", "") or "").strip()

            if not imagem.startswith("http"):
                continue

            self.send_telegram_photo(token, chat_id, imagem, message)

            enviados += 1

        return enviados > 0

    def send_whatsapp_alerts(self, alerts):

        if not self.whatsapp_configured():
            return False

        enviados = 0

        for index, item in enumerate(alerts[:10]):

            if index > 0:
                self.wait_between_notifications()

            imagem = (self.value(item, "imagem", "") or "").strip()

            if not imagem.startswith("http"):
                continue

            for recipient in self.whatsapp_recipients_for_alert(item):
                if self.whatsapp_group_rate_limited(recipient):
                    continue
                self.send_whatsapp_message(self.format_alert(item), imagem, recipient)
                enviados += 1

        return enviados > 0

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

        text = " ".join([
            str(self.value(item, "titulo", "") or ""),
            str(self.value(item, "termo", "") or ""),
        ]).casefold()

        keywords_by_category = dict(self.WHATSAPP_CATEGORY_KEYWORDS)
        if self.database is not None:
            loader = getattr(self.database, "listar_palavras_categorias", None)
            custom = loader() if loader else {}
            for category, keywords in custom.items():
                if keywords:
                    keywords_by_category[category] = tuple(keywords)

        for category, keywords in keywords_by_category.items():
            if any(keyword.casefold() in text for keyword in keywords):
                return category

        return None

    def whatsapp_recipients_for_alert(self, item):

        category_groups = self.whatsapp_category_groups()
        if not category_groups:
            return self.whatsapp_recipients()

        category = self.whatsapp_category(item)
        recipient = category_groups.get(category)
        return [recipient] if recipient else []

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

        api_url = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
        instance = os.getenv("EVOLUTION_INSTANCE")
        api_key = os.getenv("EVOLUTION_API_KEY")

        response = requests.post(
            f"{api_url}/message/sendMedia/{instance}",
            json={
                "number": phone,
                "mediatype": "image",
                "mimetype": "image/jpeg",
                "caption": message[:1000],
                "media": image_url,
                "fileName": "produto.jpg",
                "linkPreview": True,
            },
            headers={
                "apikey": api_key,
                "Content-Type": "application/json",
            },
            timeout=30
        )
        response.raise_for_status()

        return True

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
