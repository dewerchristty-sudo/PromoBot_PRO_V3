"""Consultas estatísticas somente leitura do banco principal."""

from src.statistics.models import (
    CoverageAverage,
    CoverageCount,
    GroupCount,
    RecentSend,
    StatisticsSnapshot,
    TimeSeriesPoint,
)
from src.statistics.repository import StatisticsRepository

__all__ = [
    "CoverageAverage",
    "CoverageCount",
    "GroupCount",
    "RecentSend",
    "StatisticsRepository",
    "StatisticsSnapshot",
    "TimeSeriesPoint",
]
