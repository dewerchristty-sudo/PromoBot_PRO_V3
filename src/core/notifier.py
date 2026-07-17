import os
import re
from urllib.parse import quote

import requests
from dotenv import load_dotenv


class Notifier:

    def __init__(self):

        load_dotenv()

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

        sent = []
        errors = []

        try:
            if self.send_telegram_alerts(alerts):
                sent.append("Telegram")
        except Exception as error:
            errors.append(f"Telegram: {error}")

        try:
            if self.send_whatsapp_alerts(alerts):
                sent.append("WhatsApp")
        except Exception as error:
            errors.append(f"WhatsApp: {error}")

        if sent:
            if database is not None:
                database.marcar_notificacoes_enviadas(alerts)
            return "Enviado por: " + ", ".join(sent)

        if errors:
            return "Falha ao enviar: " + " | ".join(errors)

        return "Configure WhatsApp no arquivo .env."

    def format_alert(self, item):

        termo = self.value(item, "termo") or "promocoes"
        preco_alvo = self.value(item, "preco_alvo")
        price_lines = self.format_price_lines(item)
        alvo = (
            f"Alvo: R$ {preco_alvo:.2f}"
            if preco_alvo is not None
            else "Tipo: promocao encontrada"
        )

        return "\n".join([
            "Achadinhos da ViVi",
            "",
            f"Termo: {termo}",
            alvo,
            f"Loja: {self.value(item, 'loja')}",
            *price_lines,
            f"Produto: {self.value(item, 'titulo')}",
            "",
            *self.link_lines(item),
        ]).strip()

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

        template = os.getenv("SHOPEE_AFFILIATE_TEMPLATE", "").strip()

        if not template:
            return link

        affiliate_id = os.getenv("SHOPEE_AFFILIATE_ID", "").strip()

        return template.format(
            url=link,
            url_encoded=quote(link, safe=""),
            affiliate_id=affiliate_id,
        )

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

        entries = re.split(r"[\n;]+", mapping or "")

        for entry in entries:

            if "=" not in entry:
                continue

            key, value = entry.split("=", 1)

            if key.strip().upper() == product_id:
                return value.strip()

        return ""

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

        for item in alerts[:10]:

            imagem = (self.value(item, "imagem", "") or "").strip()

            if not imagem.startswith("http"):
                continue

            for phone in self.whatsapp_phones():
                self.send_whatsapp_message(self.format_alert(item), imagem, phone)
                enviados += 1

        return enviados > 0

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
            self.whatsapp_phones(),
        ])

    def zapi_configured(self):

        return all([
            os.getenv("ZAPI_INSTANCE_ID"),
            os.getenv("ZAPI_INSTANCE_TOKEN"),
            os.getenv("ZAPI_CLIENT_TOKEN"),
            self.whatsapp_phones(),
        ])

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
