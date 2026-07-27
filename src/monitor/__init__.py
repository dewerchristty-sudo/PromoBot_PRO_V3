"""
Módulo de Monitoramento Inteligente — infraestrutura independente
para futura integração com scraping de produtos.

Componentes:
    - MonitorManager: orquestrador principal (iniciar/parar/registrar)
    - MonitorScheduler: controle de intervalo de atualização
    - ProductWatcher: representa um produto monitorado individualmente
"""

from src.monitor.monitor_manager import MonitorManager
from src.monitor.scheduler import MonitorScheduler
from src.monitor.watcher import ProductWatcher

__all__ = [
    "MonitorManager",
    "MonitorScheduler",
    "ProductWatcher",
]