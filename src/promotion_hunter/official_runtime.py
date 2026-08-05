"""Runtime oficial importavel do Promotion Hunter multi-loja.

Este modulo e a unica montagem usada pelo CLI e pela interface. Ele nao
depende de arquivos Python externos quando executado por PyInstaller.
"""
from __future__ import annotations

import argparse
import os
import threading
import time

from src.affiliates.amazon import validate_associate_tag
from src.affiliates.config import AffiliateConfig

from .contracts import PromotionSource
from .delivery.authorization import require_real_delivery_authorized
from .process_lock import HunterProcessLock
from .profiles import build_profile_sources, RotatingProfileSources


ML_TERMS = [
    "jogo de cama", "lencol", "travesseiro", "toalha", "cortina", "tapete",
    "armario", "sofa", "colchao", "mesa", "cadeira", "organizador",
    "air fryer", "liquidificador", "micro-ondas", "geladeira",
    "maquina de lavar", "cafeteira", "panela eletrica", "forno eletrico",
    "aspirador", "ventilador", "ferro de passar", "celular", "notebook",
    "fralda", "detergente",
]
AMAZON_TERMS = [
    "smartphone", "celular", "notebook", "computador", "monitor", "SSD",
    "memoria RAM", "teclado", "mouse", "fone", "smartwatch", "smart TV",
    "impressora", "roteador", "placa de video", "processador", "perfume",
    "maquiagem", "hidratante", "protetor solar", "shampoo", "condicionador",
    "mascara capilar", "batom", "rimel", "kit de beleza", "air fryer",
    "jogo de cama", "fralda", "detergente",
]
SHOPEE_TERMS = [
    "celular", "fone", "perfume", "maquiagem", "smartwatch", "air fryer",
    "fralda", "lenco umedecido", "mamadeira", "chupeta", "carrinho de bebe",
    "bebe conforto", "banheira infantil", "kit de higiene", "roupa de bebe",
    "brinquedo infantil", "detergente", "sabao", "desinfetante", "amaciante",
    "papel higienico", "vassoura", "rodo", "balde", "organizador",
    "saco de lixo", "jogo de cama", "micro-ondas",
]
ALL_TERMS = ML_TERMS + AMAZON_TERMS + SHOPEE_TERMS


class RotatingSources:
    def __init__(self, sources, per_store=6):
        self.per_store = max(1, int(per_store))
        self.by_store = {}
        self.cursors = {}
        for source in sources:
            self.by_store.setdefault(source.store, []).append(source)
            self.cursors.setdefault(source.store, 0)

    def __iter__(self):
        selected = []
        for store, items in self.by_store.items():
            start = self.cursors[store] % len(items)
            count = min(self.per_store, len(items))
            selected.extend(items[(start + offset) % len(items)] for offset in range(count))
            self.cursors[store] = (start + count) % len(items)
        return iter(selected)


def build_sources(limit=5, per_store=6, stores=None, enabled_profiles=None):
    selected_stores = tuple(stores or ("Mercado Livre", "Amazon", "Shopee"))
    sources = build_profile_sources(
        stores=selected_stores, limit=limit, enabled_profiles=enabled_profiles
    )
    return RotatingProfileSources(sources, per_store)


def build_official_runtime(*, mode="analysis_only", limit=5,
                           max_messages=3, per_store=6, stores=None,
                           max_session_messages=10, enabled_profiles=None):
    if mode == "live":
        require_real_delivery_authorized(boundary="official_runtime.initialize")
    else:
        os.environ["PROMOTION_HUNTER_LIVE_DELIVERY"] = "false"
    affiliate_config = AffiliateConfig.from_environment()
    try:
        validate_associate_tag(affiliate_config.amazon.associate_tag)
    except ValueError as exc:
        raise RuntimeError(
            "Promotion Hunter Amazon indisponivel: " + str(exc)
            + f" Arquivo de configuracao: {affiliate_config.env_path}"
        ) from exc
    from scripts.run_promotion_hunter_pilot import build_runtime, parser
    args = parser().parse_args([
        "--mode", mode.replace("_", "-"), "--term", "placeholder",
        "--limit", str(limit), "--max-messages", str(max_messages),
    ])
    args.mode = mode
    args.max_session_messages = int(max_session_messages)
    repository, pipeline, runner, _unused = build_runtime(
        args, affiliate_config=affiliate_config
    )
    sources = build_sources(
        limit, per_store, stores=stores, enabled_profiles=enabled_profiles
    )
    return repository, pipeline, runner, sources


class OfficialHunterController:
    """Controla um runtime em processo, inclusive no executavel congelado."""
    def __init__(self, runtime_factory=build_official_runtime,
                 scheduler_factory=None, process_lock_factory=HunterProcessLock):
        self.runtime_factory = runtime_factory
        self.scheduler_factory = scheduler_factory
        self.process_lock_factory = process_lock_factory
        self.process_lock = None
        self.repository = self.pipeline = self.runner = self.scheduler = None
        self.sources = None
        self.mode = None

    @property
    def running(self):
        return bool(self.scheduler and self.scheduler.running)

    def start(self, *, mode="analysis_only", interval=30, limit=5,
              max_messages=3, per_store=6, stores=None,
              max_session_messages=10, enabled_profiles=None):
        if self.running:
            return False
        lock = self.process_lock_factory()
        if not lock.acquire():
            raise RuntimeError("Ja existe um Promotion Hunter ativo.")
        try:
            runtime_options = dict(
                mode=mode, limit=limit, max_messages=max_messages,
                per_store=per_store, stores=stores,
                max_session_messages=max_session_messages,
            )
            if enabled_profiles is not None:
                runtime_options["enabled_profiles"] = enabled_profiles
            runtime = self.runtime_factory(**runtime_options)
            self.repository, self.pipeline, self.runner, self.sources = runtime
            if self.scheduler_factory is None:
                from .scheduler import PromotionHunterScheduler
                scheduler_factory = PromotionHunterScheduler
            else:
                scheduler_factory = self.scheduler_factory
            self.scheduler = scheduler_factory(
                self.runner, self.sources, self.repository,
                interval=interval, mode=mode,
            )
            if not self.scheduler.start():
                raise RuntimeError("Scheduler recusou a inicializacao.")
            self.process_lock = lock
            self.mode = mode
            return True
        except Exception:
            lock.release()
            self._close_runtime()
            raise

    def stop(self):
        try:
            if self.scheduler:
                self.scheduler.stop()
        finally:
            self._close_runtime()
            if self.process_lock:
                self.process_lock.release()
                self.process_lock = None
            self.mode = None

    def _close_runtime(self):
        if self.runner:
            self.runner.stop()
        if self.pipeline:
            self.pipeline.close()
        if self.repository:
            self.repository.close()
        self.scheduler = self.runner = self.pipeline = self.repository = None
        self.sources = None


def parser():
    value = argparse.ArgumentParser(description="Promotion Hunter oficial multi-loja")
    value.add_argument("--mode", choices=("live", "analysis_only"), default="analysis_only")
    value.add_argument("--interval", type=int, default=30)
    value.add_argument("--limit", type=int, choices=range(1, 11), default=5)
    value.add_argument("--max-messages", type=int, default=3)
    value.add_argument("--sources-per-store", type=int, default=6)
    value.add_argument("--once", action="store_true")
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    lock = HunterProcessLock()
    if not lock.acquire():
        print("Ja existe um Promotion Hunter ativo.")
        return 1
    repository = pipeline = runner = scheduler = None
    try:
        repository, pipeline, runner, sources = build_official_runtime(
            mode=args.mode, limit=args.limit, max_messages=args.max_messages,
            per_store=args.sources_per_store,
        )
        if args.once:
            result = runner.run_once(sources, mode=args.mode)
            print(result)
            return 0
        from .scheduler import PromotionHunterScheduler
        scheduler = PromotionHunterScheduler(
            runner, sources, repository, interval=args.interval, mode=args.mode
        )
        scheduler.start()
        while scheduler.running:
            time.sleep(1)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        if scheduler:
            scheduler.stop()
        if runner:
            runner.stop()
        if pipeline:
            pipeline.close()
        if repository:
            repository.close()
        lock.release()
