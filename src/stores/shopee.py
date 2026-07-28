import json
import logging
import re
import time
from html import unescape
from urllib.parse import parse_qs, quote_plus, urlparse

import asyncio
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

from src.constants import TIMEOUT_WAIT_MEDIUM
from src.stores.base_store import BaseStore

logger = logging.getLogger(__name__)


class ShopeeVariationRequired(ValueError):
    """Signals that explicit user selection is required before import."""

    def __init__(self, message, catalog=None):
        super().__init__(message)
        self.catalog = catalog or {"groups": [], "models": []}


class Shopee(BaseStore):

    @property
    def name(self):
        return "Shopee"

    @property
    def base_url(self):
        return "https://shopee.com.br/search?keyword={}"

    # ======================================================

    @staticmethod
    def normalize_price(raw_value):
        """Converte os formatos de preco usados pela Shopee para 12,34."""

        text = str(raw_value or "").strip()
        if not text:
            return ""

        text = re.sub(r"[^\d,.-]", "", text)
        if not text:
            return ""

        # A API da Shopee normalmente representa R$ 31,97 como 3197000
        # (cinco casas decimais implícitas).
        if re.fullmatch(r"\d+", text):
            number = int(text)
            if number >= 100000:
                return f"{number / 100000:.2f}".replace(".", ",")
            if number == 0:
                return ""
            return text

        if "," in text:
            # Formato brasileiro: 1.299,90.
            normalized = text.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d+\.\d{1,2}", text):
            # Metadados Open Graph/JSON-LD: 31.97.
            normalized = text
        else:
            normalized = text.replace(".", "")

        try:
            return f"{float(normalized):.2f}".replace(".", ",")
        except ValueError:
            return ""

    @staticmethod
    def selected_model_id(url):
        query = parse_qs(urlparse(str(url or "")).query)
        direct = query.get("display_model_id")
        if direct and direct[0]:
            return str(direct[0])
        for raw in query.get("extraParams", []):
            try:
                value = json.loads(raw).get("display_model_id")
            except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if value:
                return str(value)
        return ""

    @classmethod
    def variation_catalog_from_page(cls, soup):
        """Extract variation names and stock relationships without choosing one."""
        catalogs = []

        def option_name(option):
            if isinstance(option, str):
                return option.strip()
            if not isinstance(option, dict):
                return ""
            return str(
                option.get("name")
                or option.get("option")
                or option.get("value")
                or option.get("label")
                or ""
            ).strip()

        def model_stock(model):
            for field in ("stock", "normal_stock", "seller_stock"):
                value = model.get(field)
                if isinstance(value, (int, float)):
                    return max(int(value), 0)
            stock_info = model.get("stock_info") or model.get("stock_detail")
            if isinstance(stock_info, dict):
                for field in ("stock", "normal_stock", "seller_stock"):
                    value = stock_info.get(field)
                    if isinstance(value, (int, float)):
                        return max(int(value), 0)
            return 1

        def tier_indexes(model):
            value = model.get("tier_index") or model.get("tier_indexes")
            if value is None and isinstance(model.get("extinfo"), dict):
                value = model["extinfo"].get("tier_index")
            if not isinstance(value, list):
                return []
            try:
                return [int(index) for index in value]
            except (TypeError, ValueError):
                return []

        def inspect(node):
            if not isinstance(node, dict):
                return
            tiers = node.get("tier_variations")
            models = node.get("models")
            if isinstance(tiers, list) and tiers and isinstance(models, list):
                groups = []
                for tier in tiers:
                    if not isinstance(tier, dict):
                        continue
                    options = [
                        name for name in map(
                            option_name,
                            tier.get("options") or tier.get("option_list") or [],
                        )
                        if name
                    ]
                    if options:
                        groups.append({
                            "name": str(
                                tier.get("name")
                                or tier.get("label")
                                or f"Variação {len(groups) + 1}"
                            ).strip(),
                            "options": options,
                        })
                parsed_models = []
                for model in models:
                    if not isinstance(model, dict):
                        continue
                    indexes = tier_indexes(model)
                    if len(indexes) != len(groups):
                        continue
                    names = []
                    valid = True
                    for group, index in zip(groups, indexes):
                        if index < 0 or index >= len(group["options"]):
                            valid = False
                            break
                        names.append(group["options"][index])
                    if not valid:
                        continue
                    parsed_models.append({
                        "id": str(
                            model.get("modelid")
                            or model.get("model_id")
                            or model.get("id")
                            or ""
                        ),
                        "name": " / ".join(names),
                        "tier_indexes": indexes,
                        "options": names,
                        "stock": model_stock(model),
                    })
                if groups and parsed_models:
                    catalogs.append({
                        "groups": groups,
                        "models": parsed_models,
                    })
            for child in node.values():
                if isinstance(child, dict):
                    inspect(child)
                elif isinstance(child, list):
                    for item in child:
                        inspect(item)

        for script in soup.select("script"):
            raw = unescape(script.string or script.get_text() or "").strip()
            if not raw:
                continue
            payloads = []
            for candidate in (raw, raw.replace('\\"', '"')):
                if candidate[:1] not in {"{", "["}:
                    continue
                try:
                    payloads.append(json.loads(candidate))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
            for payload in payloads:
                inspect(payload)

        if not catalogs:
            return {"groups": [], "models": []}
        return max(
            catalogs,
            key=lambda catalog: (
                len(catalog["groups"]),
                len(catalog["models"]),
            ),
        )

    @staticmethod
    def model_for_selection(catalog, selection):
        groups = catalog.get("groups") or []
        models = catalog.get("models") or []
        if not groups or len(selection or {}) != len(groups):
            raise ValueError("Selecione todas as opções obrigatórias.")
        selected_names = []
        for group in groups:
            value = str((selection or {}).get(group["name"], "")).strip()
            if value not in group["options"]:
                raise ValueError(
                    f"Selecione uma opção válida para {group['name']}."
                )
            selected_names.append(value)
        for model in models:
            if model.get("options") == selected_names:
                if int(model.get("stock") or 0) <= 0:
                    raise ValueError("A variação selecionada está sem estoque.")
                return model
        raise ValueError("A combinação de variações selecionada não está disponível.")

    @staticmethod
    def catalog_requires_selection(catalog):
        in_stock_models = [
            model for model in (catalog.get("models") or [])
            if int(model.get("stock") or 0) > 0
        ]
        return len(in_stock_models) > 1

    @staticmethod
    def available_variation_options(catalog, group_index, prior_selection):
        """List in-stock options compatible with selections from earlier groups."""
        groups = catalog.get("groups") or []
        models = catalog.get("models") or []
        if group_index < 0 or group_index >= len(groups):
            return []
        available = []
        for option in groups[group_index]["options"]:
            for model in models:
                if int(model.get("stock") or 0) <= 0:
                    continue
                names = model.get("options") or []
                if len(names) != len(groups) or names[group_index] != option:
                    continue
                compatible = all(
                    names[index] == prior_selection.get(groups[index]["name"])
                    for index in range(group_index)
                )
                if compatible:
                    available.append(option)
                    break
        return available

    @classmethod
    def apply_variation_selection(cls, page, catalog, selection):
        """Click the exact user-selected options and verify the chosen model."""
        model = cls.model_for_selection(catalog, selection)
        for group in catalog["groups"]:
            option = selection[group["name"]]
            result = page.evaluate(
                """({groupName, optionName}) => {
                    const normalize = value => (value || '')
                        .replace(/\\s+/g, ' ').trim().toLowerCase();
                    const root = document.querySelector(
                        '[data-testid="product-detail"], main, .product-briefing'
                    ) || document.body;
                    const expected = normalize(optionName);
                    const nodes = Array.from(root.querySelectorAll(
                        'button, [role="button"], [role="radio"], label, div'
                    )).filter(node => {
                        const rect = node.getBoundingClientRect();
                        const style = getComputedStyle(node);
                        return normalize(node.textContent) === expected
                            && rect.width > 0 && rect.height > 0
                            && style.display !== 'none'
                            && style.visibility !== 'hidden';
                    });
                    const node = nodes.sort(
                        (left, right) => left.childElementCount - right.childElementCount
                    )[0];
                    if (!node) return {ok: false, reason: 'not_found'};
                    if (node.disabled || node.getAttribute('aria-disabled') === 'true'
                            || /disabled|sold.?out|esgotad/.test(
                                `${node.className} ${node.textContent}`.toLowerCase()
                            )) {
                        return {ok: false, reason: 'out_of_stock'};
                    }
                    node.click();
                    return {
                        ok: true,
                        group: groupName,
                        option: optionName,
                        tag: node.tagName.toLowerCase(),
                        className: String(node.className || '')
                    };
                }""",
                {"groupName": group["name"], "optionName": option},
            ) or {}
            if not result.get("ok"):
                if result.get("reason") == "out_of_stock":
                    raise ValueError("A variação selecionada está sem estoque.")
                raise ValueError(
                    f"Não foi possível selecionar {group['name']}: {option}."
                )
            page.wait_for_timeout(500)
        return model

    @classmethod
    def stable_variation_price(cls, page):
        first = cls.current_price_from_visible_page(page, return_details=True)
        page.wait_for_timeout(700)
        second = cls.current_price_from_visible_page(page, return_details=True)
        if (
            not first
            or not second
            or first.get("ambiguous")
            or second.get("ambiguous")
            or first.get("current") != second.get("current")
            or first.get("origin") != second.get("origin")
        ):
            raise ValueError(
                "O preço da variação não ficou estável ou permaneceu ambíguo."
            )
        return second

    @classmethod
    def prices_from_page(cls, soup):
        """Extrai preco atual e anterior dos JSONs internos da pagina.

        Usa parser JSON real em vez de regex para evitar confusao
        entre preco de variacao, faixa, cupom, frete e parcelamento.
        """

        current = ""
        old = ""

        # Prioridade 1: JSON-LD estruturado (application/ld+json)
        for script in soup.select("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.string or script.get_text() or "null")
                candidates = payload if isinstance(payload, list) else [payload]
                for candidate in candidates:
                    if isinstance(candidate, dict) and candidate.get("@type") == "Product":
                        offers = candidate.get("offers") or {}
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        if isinstance(offers, dict):
                            price_raw = offers.get("price") or ""
                            if price_raw:
                                normalized = cls.normalize_price(str(price_raw))
                                if normalized and cls.price_number(normalized) > 0:
                                    current = current or normalized
                            original_raw = offers.get("price_before_discount") or offers.get("original_price") or ""
                            if original_raw:
                                normalized = cls.normalize_price(str(original_raw))
                                if normalized and cls.price_number(normalized) > 0:
                                    old = old or normalized
                        if current:
                            break
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if current and old:
                return current, old

        # Prioridade 2: JSON interno via json.loads (navegação estruturada)
        for script in soup.select("script"):
            raw = unescape(script.string or script.get_text() or "")
            raw = raw.strip()
            if not raw or raw[0:1] not in {"{", "["}:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            stack = [payload] if not isinstance(payload, list) else list(payload)
            while stack and (not current or not old):
                node = stack.pop()
                if isinstance(node, list):
                    stack.extend(node)
                elif isinstance(node, dict):
                    # Verifica se este nó parece ser um produto com preço
                    price_raw = node.get("price")
                    if price_raw is not None and not current:
                        normalized = cls.normalize_price(str(price_raw))
                        if normalized and cls.price_number(normalized) > 0:
                            current = normalized
                    # price_before_discount no mesmo nível
                    old_raw = node.get("price_before_discount")
                    if old_raw is not None and not old:
                        normalized = cls.normalize_price(str(old_raw))
                        if normalized and cls.price_number(normalized) > 0:
                            old = normalized
                    # price_min / price_max (faixa) - só usa se price for 0 ou ausente
                    if not current:
                        price_min = node.get("price_min")
                        price_max = node.get("price_max")
                        if price_min is not None and price_max is not None:
                            min_val = cls.price_number(cls.normalize_price(str(price_min)))
                            max_val = cls.price_number(cls.normalize_price(str(price_max)))
                            if min_val > 0 and max_val > 0 and min_val != max_val:
                                # Faixa de preços: não inventa valor, retorna vazio
                                current = ""
                    # price_min_before_discount
                    if not old:
                        old_min = node.get("price_min_before_discount")
                        if old_min is not None:
                            normalized = cls.normalize_price(str(old_min))
                            if normalized and cls.price_number(normalized) > 0:
                                old = normalized
                    # Percorre filhos
                    stack.extend(
                        value for value in node.values()
                        if isinstance(value, (dict, list))
                    )

        # Prioridade 3: fallback regex para JavaScript (window.__INITIAL_STATE__ etc.)
        # So executa se as prioridades 1 e 2 nao encontraram preco valido.
        if not current:
            for script in soup.select("script"):
                text = unescape(script.string or script.get_text() or "")
                text = text.replace('\\"', '"')
                if not text.strip():
                    continue
                # Verifica se ha indícios de dados de produto (nao cupom/frete/parcela)
                has_product_context = any(
                    marker in text
                    for marker in (
                        '"product"', '"item"', '"product_name"', '"productDetail"',
                        '"name"', '"title"', '"price_range"',
                    )
                )
                if not has_product_context and not re.search(
                    r'"(?:price|price_min|price_before_discount)"', text
                ):
                    continue
                # Detecta e rejeita faixa de precos (price_min != price_max > 0)
                has_range = False
                min_match = re.search(r'"price_min"\s*:\s*"?(\d+)"?', text)
                max_match = re.search(r'"price_max"\s*:\s*"?(\d+)"?', text)
                if min_match and max_match:
                    pmin = cls.price_number(cls.normalize_price(min_match.group(1)))
                    pmax = cls.price_number(cls.normalize_price(max_match.group(1)))
                    if pmin > 0 and pmax > 0 and pmin != pmax:
                        has_range = True
                # So aceita price se nao for faixa
                if not has_range and not current:
                    price_match = re.search(
                        r'"price"\s*:\s*"?(\d+(?:[.,]\d+)?)"?', text
                    )
                    if price_match and price_match.group(1) != "0":
                        normalized = cls.normalize_price(price_match.group(1))
                        if normalized and cls.price_number(normalized) > 0:
                            current = normalized
                # price_before_discount - busca no mesmo script
                if not old:
                    old_match = re.search(
                        r'"price_before_discount"\s*:\s*"?(\d+(?:[.,]\d+)?)"?',
                        text,
                    )
                    if old_match and old_match.group(1) != "0":
                        normalized = cls.normalize_price(old_match.group(1))
                        if normalized and cls.price_number(normalized) > 0:
                            old = normalized
                if current:
                    break

        return current, old

    @classmethod
    def price_details_from_page(cls, soup):
        """Return price data tied to the main product, including its origin."""
        result = {
            "current": "", "old": "", "origin": "",
            "is_range": False, "range_min": "", "range_max": "",
            "has_variations": False,
        }

        def valid(raw):
            value = cls.normalize_price(raw)
            return value if cls.price_number(value) > 0 else ""

        def inspect_node(node):
            if not isinstance(node, dict):
                return
            variations = (
                node.get("variations") or node.get("models")
                or node.get("tier_variations")
            )
            if isinstance(variations, list) and len(variations) > 1:
                result["has_variations"] = True

            minimum = valid(node.get("price_min"))
            maximum = valid(node.get("price_max"))
            if minimum and maximum and minimum != maximum:
                result.update({
                    "is_range": True,
                    "range_min": minimum,
                    "range_max": maximum,
                    "origin": "faixa",
                })
                return

            for field, origin in (
                ("price_with_coupon", "cupom"),
                ("price_after_coupon", "cupom"),
                ("price_pix", "preço Pix"),
                ("pix_price", "preço Pix"),
                ("price", "preço normal"),
            ):
                price = valid(node.get(field))
                if price and not result["current"]:
                    result["current"] = price
                    result["origin"] = origin
                    break
            for field in (
                "price_before_discount",
                "price_min_before_discount",
                "original_price",
            ):
                old = valid(node.get(field))
                if old and not result["old"]:
                    result["old"] = old
                    break

        def walk(value, parent_key=""):
            if isinstance(value, list):
                for child in value:
                    walk(child, parent_key)
                return
            if not isinstance(value, dict):
                return
            excluded = re.search(
                r"recommend|similar|shipping|freight|frete|installment|"
                r"parcel|cashback|coupon_wallet",
                parent_key,
                re.I,
            )
            product_keys = {
                "price", "price_min", "price_max", "product_name", "itemid",
                "item_id", "variations", "models", "tier_variations",
            }
            if not excluded and product_keys.intersection(value):
                inspect_node(value)
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    walk(child, str(key))

        for script in soup.select("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.string or script.get_text() or "null")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            for product in payload if isinstance(payload, list) else [payload]:
                if not isinstance(product, dict) or product.get("@type") != "Product":
                    continue
                offers = product.get("offers") or {}
                offers = offers[0] if isinstance(offers, list) and offers else offers
                if isinstance(offers, dict):
                    low = valid(offers.get("lowPrice"))
                    high = valid(offers.get("highPrice"))
                    if low and high and low != high:
                        result.update({
                            "is_range": True, "range_min": low,
                            "range_max": high, "origin": "faixa",
                        })
                    else:
                        inspect_node(offers)

        for script in soup.select("script:not([type='application/ld+json'])"):
            raw = unescape(script.string or script.get_text() or "").strip()
            if not raw:
                continue
            decoded = raw.replace('\\"', '"')
            payload = None
            if decoded[:1] in {"{", "["}:
                try:
                    payload = json.loads(decoded)
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            if payload is not None:
                walk(payload)
                continue

            range_match = re.search(
                r'"price_min"\s*:\s*"?(\d+)"?.*?'
                r'"price_max"\s*:\s*"?(\d+)"?',
                decoded,
                re.S,
            )
            if range_match:
                minimum, maximum = map(valid, range_match.groups())
                if minimum and maximum and minimum != maximum:
                    result.update({
                        "is_range": True, "range_min": minimum,
                        "range_max": maximum, "origin": "faixa",
                    })
            if not result["is_range"] and re.search(
                r'"(?:product|product_name|productDetail|item)"', decoded
            ):
                match = re.search(
                    r'"price"\s*:\s*"?(\d+(?:[.,]\d+)?)"?',
                    decoded,
                )
                if match and not result["current"]:
                    result["current"] = valid(match.group(1))
                    if result["current"]:
                        result["origin"] = "preço normal"
            match = re.search(
                r'"price_before_discount"\s*:\s*"?(\d+(?:[.,]\d+)?)"?',
                decoded,
            )
            if match and not result["old"]:
                result["old"] = valid(match.group(1))

        if result["is_range"]:
            result["current"] = ""
            result["old"] = ""
            result["origin"] = "faixa"
        elif result["has_variations"] and result["current"]:
            result["origin"] = "variação"
        return result

    # ======================================================

    @classmethod
    def current_price_from_visible_page(cls, page, return_details=False):
        """Read the main rendered price without accepting unrelated values."""
        try:
            candidates = page.evaluate(
                """() => {
                    const root = document.querySelector(
                        '[data-testid="product-detail"], main, .product-briefing'
                    ) || document.body;
                    const values = [];
                    for (const node of root.querySelectorAll('*')) {
                        const text = (node.textContent || '').trim();
                        if (!/R\\$\\s*[\\d.]+,\\d{2}/.test(text)) continue;
                        const parent = node.parentElement;
                        const context = [
                            node.className, parent && parent.className,
                            parent && parent.textContent
                        ].join(' ').toLowerCase();
                        const style = getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        if (style.display === 'none' || style.visibility === 'hidden'
                                || Number(style.opacity) === 0
                                || rect.width === 0 || rect.height === 0) continue;
                        if (style.textDecorationLine.includes('line-through')) continue;
                        if (/parcel|x\\s*de|frete|shipping|cashback|recomend|similar|original|antes/.test(context)) continue;
                        if (!/price|pre[cç]o|pix|cupom|coupon|voucher/.test(context)) continue;
                        values.push({
                            text,
                            className: String(node.className || ''),
                            parentClass: String((parent && parent.className) || ''),
                            context: context.slice(0, 300),
                            tag: node.tagName.toLowerCase(),
                            fontSize: parseFloat(style.fontSize) || 0,
                            top: rect.top
                        });
                    }
                    return values;
                }"""
            ) or []
        except Exception:
            return {} if return_details else ""

        accepted = []
        for candidate in candidates:
            text = str(candidate.get("text", ""))
            prices = re.findall(r"R\$\s*([\d.]+,\d{2})", text)
            if len(prices) != 1:
                continue
            context = " ".join((
                str(candidate.get("className", "")),
                str(candidate.get("parentClass", "")),
                str(candidate.get("context", "")),
            )).lower()
            if re.search(
                r"parcel|frete|shipping|cashback|recomend|similar|original|antes",
                context,
            ):
                continue
            origin = "preço normal"
            if re.search(r"pix|à vista|a vista", context):
                origin = "preço Pix"
            elif re.search(r"cupom|coupon|voucher", context):
                origin = "cupom"
            value = cls.normalize_price(prices[0])
            if cls.price_number(value) > 0:
                accepted.append({
                    "current": value,
                    "origin": origin,
                    "element": {
                        "tag": candidate.get("tag", ""),
                        "class": candidate.get("className", ""),
                        "parent_class": candidate.get("parentClass", ""),
                        "text": text,
                    },
                    "_font_size": float(candidate.get("fontSize") or 0),
                    "_top": float(candidate.get("top") or 0),
                })
        if accepted:
            # The main offer is the most visually prominent valid price.
            accepted.sort(
                key=lambda item: (
                    item["_font_size"],
                    -abs(item["_top"]),
                ),
                reverse=True,
            )
            details = accepted[0]
            details["ambiguous"] = any(
                candidate["current"] != details["current"]
                and abs(
                    candidate["_font_size"] - details["_font_size"]
                ) < 0.5
                for candidate in accepted[1:]
            )
            details.pop("_font_size", None)
            details.pop("_top", None)
            logger.info(
                "Shopee price DOM: value=%s origin=%s element=%s",
                details["current"],
                details["origin"],
                details["element"],
            )
            return details if return_details else details["current"]
        return {} if return_details else ""

    @classmethod
    def _diagnose_price_from_visible_page(cls, page):
        """DIAGNÓSTICO TEMPORÁRIO AMPLO — Le o DOM e mostra como o preco esta estruturado."""

        try:
            # Espera adicional e scroll para garantir renderizacao
            page.wait_for_timeout(2000)
            page.evaluate("window.scrollTo(0, 300)")
            page.wait_for_timeout(1000)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)

            result = page.evaluate(
                """() => {
                    const diag = {};

                    // 1. Total de elementos com R$ no DOM
                    const allNodes = document.querySelectorAll('body *');
                    let rsCount = 0;
                    const rsLines = [];
                    for (const node of allNodes) {
                        const t = (node.textContent || '').trim();
                        if (/R\\$/.test(t)) {
                            rsCount++;
                            if (rsLines.length < 30) {
                                rsLines.push(t.slice(0, 120));
                            }
                        }
                    }
                    diag.totalComR$ = rsCount;
                    diag.amostrasR$ = rsLines;

                    // 2. Elementos folha com R$ (sem filhos)
                    const leafWithRS = [];
                    for (const node of allNodes) {
                        if (node.children.length > 0) continue;
                        const t = (node.textContent || '').trim();
                        if (!t) continue;
                        const tag = node.tagName.toLowerCase();
                        const cls = (node.className || '').slice(0, 100);
                        const parent = node.parentElement;
                        const parentTag = parent ? parent.tagName.toLowerCase() : '';
                        const parentCls = parent ? (parent.className || '').slice(0, 100) : '';
                        const prevSib = node.previousElementSibling;
                        const nextSib = node.nextElementSibling;
                        const prevText = prevSib ? (prevSib.textContent || '').trim().slice(0, 60) : '';
                        const nextText = nextSib ? (nextSib.textContent || '').trim().slice(0, 60) : '';
                        const parentText = parent ? (parent.textContent || '').trim().slice(0, 120) : '';

                        if (/R\\$/.test(t)) {
                            leafWithRS.push({
                                tag: tag,
                                class: cls,
                                text: t.slice(0, 80),
                                parentTag: parentTag,
                                parentClass: parentCls,
                                parentText: parentText.slice(0, 120),
                                prevSib: prevText,
                                nextSib: nextText
                            });
                        }
                    }
                    diag.leafComR$ = leafWithRS;

                    // 3. Elementos com "33,98" ou "3398" proximo de R$
                    const priceCandidates = [];
                    for (const node of allNodes) {
                        if (node.children.length > 0) continue;
                        const t = (node.textContent || '').trim();
                        if (!t) continue;
                        // So numeros e virgula, ou contem 33,98
                        if (/^[\\d.,]+$/.test(t) || /33[.,]?98/.test(t)) {
                            const parent = node.parentElement;
                            const parentText = parent ? (parent.textContent || '').trim() : '';
                            if (/R\\$/.test(parentText)) {
                                priceCandidates.push({
                                    tag: node.tagName.toLowerCase(),
                                    class: (node.className || '').slice(0, 80),
                                    text: t.slice(0, 40),
                                    parentTag: parent ? parent.tagName.toLowerCase() : '',
                                    parentClass: parent ? (parent.className || '').slice(0, 80) : '',
                                    parentText: parentText.slice(0, 100)
                                });
                            }
                        }
                    }
                    diag.priceCandidates = priceCandidates;

                    // 4. Verifica spans separados (R$ em um, numero em outro)
                    const splitPrices = [];
                    for (const node of allNodes) {
                        if (node.children.length > 0) continue;
                        const t = (node.textContent || '').trim();
                        if (t === 'R$') {
                            const next = node.nextElementSibling;
                            if (next) {
                                const nt = (next.textContent || '').trim();
                                splitPrices.push({
                                    tag: node.tagName.toLowerCase(),
                                    class: (node.className || '').slice(0, 60),
                                    nextTag: next.tagName.toLowerCase(),
                                    nextClass: (next.className || '').slice(0, 60),
                                    nextText: nt.slice(0, 40)
                                });
                            }
                        }
                    }
                    diag.splitPrices = splitPrices;

                    // 5. Excecao dentro do evaluate
                    diag.exception = '';

                    return diag;
                }"""
            ) or {}
        except Exception as e:
            print(f"[DIAG-DOM] EXCEÇÃO no page.evaluate: {type(e).__name__}: {e}")
            return ""

        # Exibe o diagnostico
        print(f"[DIAG-DOM] Total de elementos com R$: {result.get('totalComR$', 'N/A')}")
        print(f"[DIAG-DOM] Amostras de texto com R$ (ate 30):")
        for i, line in enumerate(result.get('amostrasR$', [])[:10]):
            print(f"  [{i}] {line}")

        print(f"\n[DIAG-DOM] Elementos folha com R$ ({len(result.get('leafComR$', []))}):")
        for r in result.get('leafComR$', [])[:20]:
            print(f"  tag={r['tag']} class={r['class']}")
            print(f"    text={r['text']}")
            print(f"    parentTag={r['parentTag']} parentClass={r['parentClass']}")
            print(f"    parentText={r['parentText']}")
            print(f"    prevSib={r['prevSib']} nextSib={r['nextSib']}")

        print(f"\n[DIAG-DOM] Candidatos a preco (numeros proximos de R$) ({len(result.get('priceCandidates', []))}):")
        for r in result.get('priceCandidates', [])[:10]:
            print(f"  tag={r['tag']} class={r['class']} text={r['text']}")
            print(f"    parentTag={r['parentTag']} parentClass={r['parentClass']}")
            print(f"    parentText={r['parentText']}")

        print(f"\n[DIAG-DOM] Spans R$ separados ({len(result.get('splitPrices', []))}):")
        for r in result.get('splitPrices', [])[:10]:
            print(f"  tag={r['tag']} class={r['class']} -> next: tag={r['nextTag']} class={r['nextClass']} text={r['nextText']}")

        if result.get('exception'):
            print(f"[DIAG-DOM] Excecao capturada: {result['exception']}")

        # Nao retorna preco ainda — apenas diagnostico
        return ""

    @classmethod
    def old_price_from_visible_page(cls, page, current_price):
        """Le o valor riscado que a Shopee renderiza na area da oferta.

        So aceita precos com evidencia semantica adicional:
        - text-decoration line-through
        - tag del ou s
        - classe contendo before, original, old-price, price-old
        - container pai identificado como bloco de preco original
        - dado estruturado do mesmo produto ou da mesma variacao
        """

        try:
            candidates = page.evaluate(
                """() => {
                    const values = [];
                    const nodes = document.querySelectorAll('body *');
                    for (const node of nodes) {
                        if (node.children.length > 0) continue;
                        const text = (node.textContent || '').trim();
                        if (!/R\\$\\s*[\\d.]+,\\d{2}/.test(text)) continue;
                        const style = getComputedStyle(node);
                        const tag = node.tagName.toLowerCase();
                        const crossed = style.textDecorationLine.includes('line-through')
                            || tag === 'del' || tag === 's';
                        const priceClass = String(node.className || '').toLowerCase();
                        const parentClass = String(
                            (node.parentElement && node.parentElement.className) || ''
                        ).toLowerCase();
                        const hasSemanticEvidence = crossed
                            || /before|original|old-price|price-old|product-price__original/
                                .test(priceClass)
                            || /original|old-price|price-original/
                                .test(parentClass);
                        if (hasSemanticEvidence) {
                            values.push(text);
                        }
                    }
                    return values;
                }"""
            ) or []
        except Exception:
            return ""

        current = cls.price_number(current_price)
        for candidate in candidates:
            for raw_price in re.findall(r"R\$\s*([\d.]+,\d{2})", candidate):
                normalized = cls.normalize_price(raw_price)
                if cls.price_number(normalized) > current:
                    return normalized
        return ""

    # ======================================================

    def search(self, product):

        url = self.base_url.format(quote_plus(product))

        print(f"\n>>> {self.name}")
        print(f"Abrindo: {url}")
        # Tentar múltiplas vezes alternando entre stealth False/True para
        # reduzir falsos-positivos de bloqueio intermitente.
        attempts = [False, True, False]
        last_result = []
        for idx, stealth in enumerate(attempts, start=1):
            if idx > 1:
                # pequeno intervalo antes de tentar novamente
                time.sleep(1)
            resultados = self._search_url(url, stealth=stealth)

            if resultados is None:
                logger.warning(
                    f"Shopee: tentativa {idx} com stealth={stealth} retornou página de verificação."
                )
                print(f"{self.name}: tentativa {idx} com stealth={stealth} -> verify page")
                continue

            # Se encontrou resultados, retorna imediatamente
            if resultados:
                return resultados

            # guarda último resultado (mesmo vazio) para retorno ao final
            last_result = resultados

        return last_result or []

    # ======================================================

    def _search_url(self, url, stealth):

        resultados = []
        page = self.browser_manager.new_page(stealth=stealth)

        try:

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=90000
            )

            page.wait_for_timeout(TIMEOUT_WAIT_MEDIUM)

            if self.is_verify_page(page):
                return None

            cards = self._extract_cards(page)

            print(f"Produtos encontrados: {len(cards)}")

            vistos = set()

            for item in cards:

                try:

                    href = item.get("href", "")
                    link = self.link(href, "https://shopee.com.br")

                    if not link or link in vistos:
                        continue

                    vistos.add(link)

                    linhas = self.text_lines(item.get("text", ""))
                    titulo = self.extract_title(linhas, item.get("imageAlt", ""))
                    preco = self.extract_price(linhas)

                    if not titulo or not preco:
                        continue

                    # Filtra anúncios inválidos (ex: "Patrocinado", "Anúncio")
                    if self._is_invalid_ad(titulo, linhas):
                        logger.debug(f"Shopee: anúncio inválido ignorado: {titulo}")
                        continue

                    resultado = {
                        "loja": self.name,
                        "titulo": titulo,
                        "preco": preco,
                        "link": link,
                        "imagem": item.get("image", ""),
                    }

                    # Tenta extrair preço anterior do texto do card
                    old_price = self._extract_old_price_from_lines(linhas, preco)
                    if old_price:
                        resultado["preco_antigo"] = old_price

                    resultados.append(resultado)

                    if len(resultados) >= 20:
                        break

                except Exception as e:
                    logger.debug(f"Erro ao processar item do Shopee: {str(e)}")
                    continue

            print(f"{self.name}: {len(resultados)} produtos encontrados.")

            return resultados

        finally:
            page.close()

    # ======================================================

    @staticmethod
    def _is_invalid_ad(titulo, lines):
        """Verifica se o card é um anúncio inválido (patrocinado, etc)."""
        text = " ".join(lines).lower()
        markers = [
            "patrocinado", "anúncio", "anuncio", "ad",
            "propaganda", "publicidade",
        ]
        for marker in markers:
            if marker in text:
                return True
        return False

    # ======================================================

    @classmethod
    def _extract_old_price_from_lines(cls, lines, current_price):
        """Tenta extrair preço anterior das linhas do card."""
        current_value = cls.price_number(current_price)
        if current_value <= 0:
            return ""
        prices = []
        for line in lines:
            if "R$" in line:
                raw = cls.normalize_price(line)
                if raw and cls.price_number(raw) > current_value:
                    prices.append(raw)
        if prices:
            return max(prices, key=cls.price_number)
        return ""

    # ======================================================

    def is_verify_page(self, page):

        current_url = (page.url or "").lower()

        if "/verify/traffic/error" in current_url:
            return True

        try:
            content = page.content().lower()
        except Exception:
            return False

        return (
            "verify/traffic/error" in content
            or "redirect_to_error_page" in content
        )

    # ======================================================

    def _extract_cards(self, page):
        """Extrai cards de produtos com múltiplos seletores para robustez."""

        selectors = [
            "a[href*='-i.']",
            "a[href*='/product/']",
            "a[href*='shopee.com.br']",
        ]

        for selector in selectors:
            cards = self._evaluate_cards(page, selector)
            if cards:
                return cards

        return []

    def _evaluate_cards(self, page, selector):

        try:
            return page.locator(selector).evaluate_all(
                """
                elements => elements.slice(0, 40).map(anchor => {
                    const image = Array.from(anchor.querySelectorAll("img"))
                        .find(img => img.src && img.src.includes("susercontent"));

                    return {
                        href: anchor.href || anchor.getAttribute("href") || "",
                        text: anchor.innerText || "",
                        image: image ? image.src : "",
                        imageAlt: image ? image.alt : ""
                    };
                })
                """
            )
        except Exception as e:
            logger.debug(f"Erro ao extrair cards do Shopee com seletor '{selector}': {str(e)}")
            return []

    # ======================================================

    def text_lines(self, text):

        return [
            line.strip()
            for line in (text or "").splitlines()
            if line.strip()
        ]

    # ======================================================

    def extract_title(self, lines, image_alt=""):

        for value in [image_alt, *lines]:

            value = " ".join((value or "").split()).strip()

            if len(value) < 12:
                continue

            if value == "flag-label" or "R$" in value:
                continue

            return value[:240]

        return ""

    # ======================================================

    def product_from_url(self, url, debug=False, variation_selection=None):
        """Executa Playwright Sync fora de event loops asyncio ativos."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._product_from_url_sync(
                url,
                debug=debug,
                variation_selection=variation_selection,
            )

        def isolated_import():
            isolated = type(self)()
            try:
                return isolated._product_from_url_sync(
                    url,
                    debug=debug,
                    variation_selection=variation_selection,
                )
            finally:
                isolated.close()

        with ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="shopee-sync-import",
        ) as executor:
            return executor.submit(isolated_import).result()

    def close(self):
        closer = getattr(self.browser_manager, "close", None)
        if callable(closer):
            closer()

    def _product_from_url_sync(
        self,
        url,
        debug=False,
        variation_selection=None,
    ):
        """Coleta um unico produto a partir da pagina da Shopee.

        Tenta duas configuracoes de navegador para contornar
        a pagina de verificacao da Shopee.

        Parameters
        ----------
        url : str
            URL do produto na Shopee.
        debug : bool, optional
            Se True, tenta abrir navegador visivel como ultima
            tentativa (para depuracao). Padrao False.
        """

        attempts = [
            {"headless": True, "stealth": True},
            {"headless": True, "stealth": False},
        ]

        if debug:
            attempts.append({"headless": False, "stealth": True})

        last_error = ""

        for idx, attempt in enumerate(attempts):
            headless = attempt["headless"]
            stealth = attempt["stealth"]

            page = self.browser_manager.new_page(stealth=stealth)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(8000)

                verify_page = self.is_verify_page(page)

                content = page.content()
                soup = BeautifulSoup(content, "lxml")
                price_details = self.price_details_from_page(soup)
                variation_catalog = self.variation_catalog_from_page(soup)
                selected_model_data = None
                if variation_selection is not None:
                    if not variation_catalog["groups"]:
                        raise ValueError(
                            "A Shopee não retornou as opções desta variação."
                        )
                    selected_model_data = self.apply_variation_selection(
                        page,
                        variation_catalog,
                        variation_selection,
                    )
                    page.wait_for_timeout(1000)
                json_price = price_details["current"]
                old_price_text = price_details["old"]

                # Tenta obter via Open Graph
                og_title = soup.find("meta", property="og:title")
                og_image = soup.find("meta", property="og:image")
                og_price = soup.find("meta", property="product:price:amount")

                title_text = og_title.get("content", "").strip() if og_title else ""
                image_url = og_image.get("content", "").strip() if og_image else ""
                price_text = og_price.get("content", "").strip() if og_price else ""

                # Fallback: extrai do JSON interno da pagina
                if not title_text or not price_text:
                    for script in soup.select("script"):
                        text = script.string or ""
                        if '"product_name"' in text or '"name"' in text:
                            match = re.search(r'"product_name"\s*:\s*"([^"]+)"', text)
                            if match and not title_text:
                                title_text = match.group(1)
                            if title_text and price_text:
                                break

                # Fallback 2: JSON-LD
                if not title_text or not price_text:
                    for script in soup.select("script[type='application/ld+json']"):
                        try:
                            payload = json.loads(script.string or script.get_text() or "null")
                            candidates = payload if isinstance(payload, list) else [payload]
                            for candidate in candidates:
                                if isinstance(candidate, dict) and candidate.get("@type") == "Product":
                                    title_text = title_text or str(candidate.get("name") or "")
                                    candidate_image = candidate.get("image") or ""
                                    if isinstance(candidate_image, list):
                                        candidate_image = candidate_image[0] if candidate_image else ""
                                    image_url = image_url or str(candidate_image).strip()
                                    offers = candidate.get("offers") or {}
                                    if isinstance(offers, list):
                                        offers = offers[0] if offers else {}
                                    if isinstance(offers, dict):
                                        price_text = price_text or str(offers.get("price") or "")
                                    break
                        except Exception:
                            continue

                # Fallback 3: busca imagem via Playwright evaluate
                if not image_url:
                    try:
                        image_url = page.evaluate(
                            """() => {
                                const selectors = [
                                    'img[src*="susercontent"]',
                                    'img[class*="product"]',
                                    'img[class*="image"]',
                                    'div[class*="image"] img',
                                    'div[class*="product"] img'
                                ];
                                for (const sel of selectors) {
                                    const img = document.querySelector(sel);
                                    if (img && img.src && img.src.startsWith('http')) {
                                        return img.src;
                                    }
                                }
                                return '';
                            }"""
                        ) or ""
                    except Exception:
                        pass

                # Fallback 4: twitter:image
                if not image_url:
                    tw_image = (
                        soup.find("meta", property="twitter:image")
                        or soup.find("meta", attrs={"name": "twitter:image"})
                    )
                    if tw_image:
                        image_url = tw_image.get("content", "").strip()

                # Fallback 5: busca imageUrl em qualquer JSON interno
                if not image_url:
                    for script in soup.select("script"):
                        text = script.string or ""
                        for pattern in [
                            r'"imageUrl"\s*:\s*"([^"]+)"',
                            r'"image"\s*:\s*"([^"]+)"',
                        ]:
                            match = re.search(pattern, text)
                            if match:
                                candidate = match.group(1)
                                if candidate.startswith("http"):
                                    image_url = candidate
                                    break
                        if image_url:
                            break

                # Structured product data wins over generic metadata. The DOM
                # may refine the modality (Pix/coupon) when explicitly labelled.
                parsed_price = self.normalize_price(json_price or price_text)
                parsed_old_price = self.normalize_price(old_price_text)
                price_origin = price_details["origin"] or "preço normal"

                if price_details["is_range"] and variation_selection is None:
                    raise ShopeeVariationRequired(
                        "Este produto possui faixa de preço "
                        f"(R$ {price_details['range_min']} a "
                        f"R$ {price_details['range_max']}) ou depende da "
                        "seleção de uma variação. Selecione a variação "
                        "desejada ou informe o preço manualmente.",
                        variation_catalog,
                    )

                selected_model = self.selected_model_id(url)
                has_variations = (
                    self.catalog_requires_selection(variation_catalog)
                    or price_details["has_variations"]
                )
                if has_variations and variation_selection is None:
                    raise ShopeeVariationRequired(
                        "Este produto possui faixa de preço ou depende da "
                        "seleção de uma variação. Selecione a variação "
                        "desejada ou informe o preço manualmente.",
                        variation_catalog,
                    )

                dom_details = (
                    self.stable_variation_price(page)
                    if variation_selection is not None
                    else self.current_price_from_visible_page(
                        page,
                        return_details=True,
                    )
                )
                if dom_details:
                    if (
                        parsed_price
                        and parsed_price != dom_details["current"]
                    ):
                        logger.warning(
                            "Shopee price conflict: structured=%s visible=%s "
                            "visible_origin=%s visible_element=%s",
                            parsed_price,
                            dom_details["current"],
                            dom_details["origin"],
                            dom_details.get("element", {}),
                        )
                    parsed_price = dom_details["current"]
                    price_origin = dom_details["origin"]

                if not parsed_old_price:
                    parsed_old_price = self.old_price_from_visible_page(
                        page,
                        parsed_price,
                    )
                valid_image = image_url.startswith(("http://", "https://"))

                # --- DIAGNÓSTICO TEMPORÁRIO ---
                print(f"[DIAG] Tentativa {idx+1}: stealth={stealth} headless={headless}")
                print(f"[DIAG] verify_page={verify_page}")
                print(f"[DIAG] title_text='{title_text[:80] if title_text else '(vazio)'}'")
                print(f"[DIAG] price_text='{price_text}'")
                print(f"[DIAG] json_price='{json_price}'")
                print(f"[DIAG] old_price_text='{old_price_text}'")
                print(f"[DIAG] parsed_price='{parsed_price}'")
                print(f"[DIAG] parsed_old_price='{parsed_old_price}'")
                print(f"[DIAG] image_url='{image_url[:60] if image_url else '(vazio)'}'")
                print(f"[DIAG] valid_image={valid_image}")
                # --- FIM DIAGNÓSTICO ---

                # Rejeita preco zero ou negativo (variacoes nao selecionadas)
                if not parsed_price or self.price_number(parsed_price) <= 0:
                    print(f"[DIAG] >>> ABORTADO: parsed_price invalido (zero/negativo)")
                    last_error = (
                        "O produto possui variacoes ou o preco nao pode ser "
                        "determinado automaticamente. "
                        "Preco depende da variacao selecionada."
                    )
                    continue

                if verify_page and (
                    not title_text or not parsed_price or not valid_image
                ):
                    print(f"[DIAG] >>> ABORTADO: verify_page e dados insuficientes")
                    last_error = (
                        "A Shopee bloqueou o acesso com pagina de "
                        "verificacao. Tente novamente mais tarde ou "
                        "cadastre o produto manualmente informando "
                        "titulo, preco e link da imagem."
                    )
                    continue

                if not title_text:
                    print(f"[DIAG] >>> ABORTADO: titulo vazio")
                    last_error = (
                        "A Shopee nao retornou os dados do produto. "
                        "Abra o link no navegador e confirme que ele "
                        "leva diretamente ao produto."
                    )
                    continue

                print(f"[DIAG] >>> SUCESSO: produto criado com preco={parsed_price}")
                product_data = {
                    "loja": self.name,
                    "titulo": title_text,
                    "preco": parsed_price,
                    "origem_preco": price_origin,
                    "link": url,
                    "imagem": image_url,
                }
                if variation_selection is not None and selected_model_data:
                    product_data["tem_variacoes"] = True
                    product_data["variacao_selecionada"] = (
                        selected_model_data["name"]
                    )
                    product_data["variacao_model_id"] = (
                        selected_model_data["id"]
                    )
                    product_data["estoque_variacao"] = int(
                        selected_model_data["stock"]
                    )
                    product_data["selecao_variacao"] = dict(
                        variation_selection
                    )
                if (
                    parsed_old_price
                    and self.price_number(parsed_old_price)
                    > self.price_number(parsed_price)
                ):
                    product_data["preco_antigo"] = parsed_old_price

                return product_data

            finally:
                page.close()

        # Todas as tentativas falharam
        print(f"[DIAG] >>> TODAS AS TENTATIVAS FALHARAM. last_error='{last_error}'")
        raise ValueError(last_error)

    # ======================================================

    def extract_price(self, lines):

        for index, line in enumerate(lines):

            if line == "R$" and index + 1 < len(lines):
                price = self.price(lines[index + 1])
                if price and self.price_number(price) > 0:
                    return price
                return ""

            if "R$" in line:
                price = self.price(line)
                if price and self.price_number(price) > 0:
                    return price
                return ""

        return ""

    @staticmethod
    def price_number(value):
        text = str(value or "").replace(".", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return 0.0
