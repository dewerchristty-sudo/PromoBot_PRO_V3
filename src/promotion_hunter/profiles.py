"""Catálogo autorizado dos três perfis lógicos do Hunter Global."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import PromotionSource


@dataclass(frozen=True)
class HunterProfile:
    profile_id: str
    label: str
    category: str
    terms: tuple[str, ...]
    priority: int


PROFILES = (
    HunterProfile("tecnologia_acessorios", "Tecnologia e Acessórios", "smartphones_tecnologia", (
        "smartphone", "celular", "notebook", "computador", "pc gamer", "monitor",
        "ssd", "hd", "memória ram", "placa de vídeo", "processador", "placa-mãe",
        "fonte para pc", "gabinete", "impressora", "roteador", "tablet", "smartwatch",
        "fone", "headset", "mouse", "teclado", "webcam", "microfone", "caixa de som",
        "carregador", "cabo usb", "cabo hdmi", "adaptador", "hub usb", "power bank",
        "suporte para notebook", "cooler para notebook", "mochila para notebook",
        "capa para celular", "película", "controle gamer", "acessórios gamer",
    ), 1),
    HunterProfile("cosmeticos", "Cosméticos", "beleza_perfumaria", (
        "shampoo", "condicionador", "máscara capilar", "creme de cabelo", "leave-in",
        "hidratante", "perfume", "colônia", "maquiagem", "batom", "gloss", "rímel",
        "blush", "base", "protetor solar", "skincare", "sérum facial",
        "sabonete facial", "kit de beleza", "secador", "chapinha", "escova secadora",
        "barbeador",
    ), 2),
    HunterProfile("eletrodomesticos", "Eletrodomésticos", "eletrodomesticos", (
        "air fryer", "liquidificador", "cafeteira", "micro-ondas", "geladeira", "fogão",
        "máquina de lavar", "aspirador", "ventilador", "forno elétrico",
        "panela elétrica", "purificador", "batedeira", "sanduicheira", "ferro de passar",
        "torradeira", "mixer", "processador de alimentos", "grill elétrico",
    ), 3),
)
PROFILE_BY_ID = {profile.profile_id: profile for profile in PROFILES}
AUTHORIZED_PROFILE_IDS = tuple(PROFILE_BY_ID)


def build_profile_sources(*, stores, limit=5, enabled_profiles=None):
    enabled = set(enabled_profiles or AUTHORIZED_PROFILE_IDS)
    sources = []
    seen = set()
    for store in stores:
        for profile in PROFILES:
            if profile.profile_id not in enabled:
                continue
            for index, term in enumerate(profile.terms):
                unique = (store.casefold(), term.casefold())
                if unique in seen:
                    continue
                seen.add(unique)
                sources.append(PromotionSource(
                    source_id=f"{store.casefold().replace(' ', '-')}:{profile.profile_id}:{index}",
                    source_type="keyword", store=store, display_name=term,
                    configuration={
                        "keyword": term, "profile_id": profile.profile_id,
                        "canonical_category": profile.category,
                        "priority": profile.priority, "enabled": True,
                    }, limit=limit,
                ))
    return tuple(sources)


class RotatingProfileSources:
    """Rotação justa por perfil, preservando FIFO dos termos de cada perfil."""

    def __init__(self, sources, per_store=6):
        self.per_store = max(1, int(per_store))
        self.buckets = {}
        self.term_cursors = {}
        self.profile_cursors = {}
        for source in sources:
            profile_id = source.configuration["profile_id"]
            self.buckets.setdefault(source.store, {}).setdefault(profile_id, []).append(source)
            self.term_cursors.setdefault((source.store, profile_id), 0)
            self.profile_cursors.setdefault(source.store, 0)

    def __iter__(self):
        selected = []
        for store, profiles in self.buckets.items():
            order = [item for item in AUTHORIZED_PROFILE_IDS if item in profiles]
            if not order:
                continue
            start = self.profile_cursors[store] % len(order)
            for offset in range(min(self.per_store, sum(map(len, profiles.values())))):
                profile_id = order[(start + offset) % len(order)]
                items = profiles[profile_id]
                key = (store, profile_id)
                cursor = self.term_cursors[key] % len(items)
                selected.append(items[cursor])
                self.term_cursors[key] = (cursor + 1) % len(items)
            self.profile_cursors[store] = (start + self.per_store) % len(order)
        return iter(selected)
