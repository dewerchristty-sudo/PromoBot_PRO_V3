from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class ChartSeries:
    title: str
    labels: tuple[str, ...]
    values: tuple[float, ...]
    kind: str = "bar"
    color: str = "#1f8bff"


class OfferCharts:
    """Converte snapshots em séries; não consulta banco nem UI."""

    @staticmethod
    def score_over_time(hourly: Iterable[Mapping]) -> ChartSeries:
        rows = list(hourly)
        return ChartSeries(
            "Score médio por hora",
            tuple(str(row.get("label", ""))[-5:] for row in rows),
            tuple(float(row.get("average_score", 0) or 0) for row in rows),
            "line",
            "#39c6a3",
        )

    @staticmethod
    def products_by_group(
        title: str,
        rows: Iterable[Mapping],
        color="#1f8bff",
    ) -> ChartSeries:
        values = list(rows)
        return ChartSeries(
            title,
            tuple(str(row.get("label", "")) for row in values),
            tuple(float(row.get("total", 0) or 0) for row in values),
            "bar",
            color,
        )

    @staticmethod
    def approval(metrics) -> ChartSeries:
        discarded = max(
            int(metrics.total_analyzed) - int(metrics.total_approved),
            0,
        )
        return ChartSeries(
            "Aprovação",
            ("Aprovados", "Não aprovados"),
            (float(metrics.total_approved), float(discarded)),
            "bar",
            "#f0a23b",
        )

    @staticmethod
    def processing_time(hourly: Iterable[Mapping]) -> ChartSeries:
        rows = list(hourly)
        return ChartSeries(
            "Tempo médio (ms)",
            tuple(str(row.get("label", ""))[-5:] for row in rows),
            tuple(
                float(row.get("average_processing_ms", 0) or 0)
                for row in rows
            ),
            "line",
            "#c67cff",
        )
