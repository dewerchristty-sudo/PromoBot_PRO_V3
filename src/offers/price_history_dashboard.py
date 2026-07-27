from dataclasses import asdict

from .history import OfferHistory
from src.stores.active import ACTIVE_STORE_NAMES


class PriceHistoryDashboard:
    """Indicadores prontos para uma futura tela, sem alterar a UI atual."""

    def __init__(self, repository):
        self.repository = repository
        self.history = OfferHistory(store=repository)

    def identities(self):
        rows = self.repository.read_all("""
            SELECT canonical_identity
            FROM offer_price_history
            WHERE lower(store) IN (lower(?), lower(?), lower(?))
            GROUP BY canonical_identity
            ORDER BY canonical_identity
        """, ACTIVE_STORE_NAMES)
        return [row["canonical_identity"] for row in rows]

    def snapshot(self):
        histories = [
            self.history.analyze(identity)
            for identity in self.identities()
        ]
        valid = [item for item in histories if item.sample_count]
        return {
            "products_monitored": len(valid),
            "history_days": max(
                (item.history_span_days for item in valid), default=0
            ),
            "lowest_price": min(
                (item.minimum for item in valid), default=0
            ),
            "highest_price": max(
                (item.maximum for item in valid), default=0
            ),
            "products_falling": sum(item.trend == "caiu" for item in valid),
            "products_stable": sum(item.trend == "estavel" for item in valid),
            "new_records": sum(item.is_new_record for item in valid),
            "largest_saving_percent": max(
                (item.drop_percent for item in valid), default=0
            ),
        }

    def details(self):
        return [
            {
                **asdict(result),
                "observations": [
                    asdict(item) for item in result.observations
                ],
            }
            for result in (
                self.history.analyze(identity)
                for identity in self.identities()
            )
        ]
