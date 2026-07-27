import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.affiliates.validation import product_identity

from .models import OfferCandidate, OfferIdentityResult
from .score import OfferScore


class OfferIdentity:
    """Gera identidade determinística sem depender de serviços externos."""

    PROMOTIONAL_TERMS = {
        "promocao", "oferta", "imperdivel", "barato", "barata",
        "desconto", "frete", "gratis", "cupom", "liquidacao",
    }
    GENERIC_PRODUCT_TERMS = {
        "ssd", "nvme", "m2", "m.2",
    }
    TRACKING_KEYS = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term",
        "utm_content", "matt_tool", "matt_word", "tag", "ref",
    }
    COLORS = {
        "preto", "branco", "azul", "vermelho", "rosa", "verde",
        "cinza", "prata", "dourado", "roxo", "amarelo",
    }

    def identify(self, candidate: OfferCandidate) -> OfferIdentityResult:
        normalized = self.normalize_title(candidate.title)
        tokens = tuple(sorted(set(normalized.split())))
        explicit_code = self.normalize_code(candidate.product_code)
        model_code = self.normalize_code(candidate.model)
        official_key = product_identity(
            candidate.store, candidate.product_link
        )
        code = (
            official_key or explicit_code or model_code
            or self.extract_model_code(tokens)
        )
        canonical_link = self.canonicalize_link(
            candidate.product_link or candidate.affiliate_link
        )
        link_signature = self.digest(canonical_link) if canonical_link else ""

        identity_material = (
            f"{candidate.store.casefold()}|{official_key}"
            if official_key else self.identity_material(
                candidate, tokens, code
            )
        )
        signature = self.digest(identity_material)
        similarity_tokens = tuple(
            token for token in tokens if token not in self.COLORS
        )
        similarity_material = "|".join(similarity_tokens) or identity_material
        similarity_signature = self.digest(similarity_material)
        price = OfferScore.number(candidate.current_price)
        promotion_signature = self.digest(
            f"{signature}|{price:.2f}"
        )
        return OfferIdentityResult(
            signature=signature,
            normalized_title=normalized,
            canonical_link=canonical_link,
            link_signature=link_signature,
            promotion_signature=promotion_signature,
            similarity_signature=similarity_signature,
            product_code=code,
            tokens=tokens,
        )

    def normalize_title(self, title: str) -> str:
        text = self.ascii_text(title)
        text = re.sub(r"\bssd\s*m[.]?2\b", "ssd m2", text)
        text = re.sub(r"\bm[.]?2\b", "m2", text)
        text = re.sub(r"\bnvme\b", "nvme", text)
        text = re.sub(r"\bpolegadas?\b|\bpol[.]?\b", "pol", text)
        text = re.sub(
            r"\b(1000|1024)\s*gb\b",
            "1tb",
            text,
        )
        text = re.sub(r"\b(\d+(?:[.,]\d+)?)\s*(tb|gb|mb)\b", r"\1\2", text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        tokens = [
            token for token in text.split()
            if token not in self.PROMOTIONAL_TERMS
        ]
        return " ".join(tokens)

    def identity_material(
        self,
        candidate: OfferCandidate,
        tokens: tuple[str, ...],
        code: str,
    ) -> str:
        meaningful = [
            token for token in tokens
            if token not in self.GENERIC_PRODUCT_TERMS
        ]
        extras = [
            self.normalize_code(candidate.brand),
            code,
            self.normalize_code(candidate.color),
        ]
        values = sorted(set(
            value for value in [*meaningful, *extras] if value
        ))
        if values:
            return "|".join(values)
        canonical = self.canonicalize_link(
            candidate.product_link or candidate.affiliate_link
        )
        return canonical or f"{self.ascii_text(candidate.store)}|produto-sem-dados"

    @classmethod
    def canonicalize_link(cls, link: str) -> str:
        value = str(link or "").strip()
        if not value:
            return ""
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            return value.rstrip("/")
        query = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=False)
            if key.casefold() not in cls.TRACKING_KEYS
            and not key.casefold().startswith("utm_")
        ]
        path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
        return urlunparse((
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            path,
            "",
            urlencode(sorted(query)),
            "",
        ))

    @staticmethod
    def extract_model_code(tokens: tuple[str, ...]) -> str:
        candidates = [
            token for token in tokens
            if len(token) >= 3
            and any(character.isalpha() for character in token)
            and any(character.isdigit() for character in token)
            and not re.fullmatch(r"\d+(?:gb|tb|mb|pol)", token)
        ]
        return max(candidates, key=len, default="")

    @staticmethod
    def normalize_code(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", OfferIdentity.ascii_text(value))

    @staticmethod
    def ascii_text(value: str) -> str:
        normalized = unicodedata.normalize(
            "NFKD",
            str(value or "").casefold(),
        )
        return "".join(
            character for character in normalized
            if not unicodedata.combining(character)
        )

    @staticmethod
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
