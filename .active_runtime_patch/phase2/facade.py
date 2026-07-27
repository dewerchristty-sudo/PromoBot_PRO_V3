from dataclasses import dataclass, field

from .analytics import DashboardStatistics
from .approval import ApprovalWorkspace
from .history import ObservationalOfferHistory
from .price_monitoring import PriceTrendAnalyzer
from .scheduling import PublicationQueue
from .store_catalog import StoreCatalog


@dataclass
class Phase2Foundation:
    """Ponto de composição opt-in, deliberadamente ausente do runtime atual."""

    publication_queue: PublicationQueue = field(default_factory=PublicationQueue)
    statistics: DashboardStatistics = field(default_factory=DashboardStatistics)
    history: ObservationalOfferHistory = field(
        default_factory=ObservationalOfferHistory
    )
    approvals: ApprovalWorkspace = field(default_factory=ApprovalWorkspace)
    stores: StoreCatalog = field(default_factory=StoreCatalog.future_stores)
    price_analyzer: PriceTrendAnalyzer = field(default_factory=PriceTrendAnalyzer)
