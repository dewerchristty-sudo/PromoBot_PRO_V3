import sqlite3
from pathlib import Path

from src.statistics.models import (
    CoverageAverage,
    CoverageCount,
    GroupCount,
    RecentSend,
    StatisticsSnapshot,
    TimeSeriesPoint,
)


class StatisticsRepository:
    """Agregações do banco principal por uma conexão SQLite somente leitura."""

    FAILURE_STATES = (
        "falhou",
        "aguardando_nova_tentativa",
        "falha_definitiva",
        "revisao_necessaria",
    )

    def __init__(self, database_path):
        self.database_path = Path(database_path).resolve()
        uri = f"file:{self.database_path.as_posix()}?mode=ro"
        self.connection = sqlite3.connect(uri, uri=True)
        self.connection.row_factory = sqlite3.Row
        self.closed = False
        self._tables = self._load_tables()
        self._columns = {}

    def _load_tables(self):
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        return {row["name"] for row in rows}

    def _table_exists(self, table):
        return table in self._tables

    def _table_columns(self, table):
        if table not in self._columns:
            if not self._table_exists(table):
                self._columns[table] = set()
            else:
                cursor = self.connection.execute(
                    f"SELECT * FROM {table} LIMIT 0"
                )
                self._columns[table] = {
                    description[0] for description in cursor.description
                }
        return self._columns[table]

    def _has_columns(self, table, *columns):
        available = self._table_columns(table)
        return all(column in available for column in columns)

    def _scalar(self, query, parameters=()):
        row = self.connection.execute(query, parameters).fetchone()
        return int(row[0] or 0) if row else 0

    def _count(self, table, where="", parameters=()):
        if not self._table_exists(table):
            return 0
        query = f"SELECT COUNT(*) FROM {table}"
        if where:
            query += f" WHERE {where}"
        return self._scalar(query, parameters)

    def _groups(self, query, parameters=()):
        return tuple(
            GroupCount(str(row["label"] or "Não informado"), int(row["total"]))
            for row in self.connection.execute(query, parameters).fetchall()
        )

    def products_by_store(self):
        if not self._has_columns("produtos", "loja"):
            return ()
        return self._groups("""
            SELECT COALESCE(NULLIF(TRIM(loja), ''), 'Não informada') AS label,
                   COUNT(*) AS total
            FROM produtos
            GROUP BY COALESCE(NULLIF(TRIM(loja), ''), 'Não informada')
            ORDER BY total DESC, label
        """)

    def sends_by_channel(self):
        if not self._has_columns("historico_envios", "canal", "status"):
            return ()
        return self._groups("""
            SELECT COALESCE(NULLIF(TRIM(canal), ''), 'Não informado') AS label,
                   COUNT(*) AS total
            FROM historico_envios
            WHERE status = 'enviado'
            GROUP BY COALESCE(NULLIF(TRIM(canal), ''), 'Não informado')
            ORDER BY total DESC, label
        """)

    def most_sent_products(self, limit=10):
        required = ("titulo", "link_original", "status")
        if not self._has_columns("historico_envios", *required):
            return ()
        return self._groups("""
            SELECT COALESCE(NULLIF(TRIM(MAX(titulo)), ''), 'Sem título') AS label,
                   COUNT(*) AS total
            FROM historico_envios
            WHERE status = 'enviado'
            GROUP BY COALESCE(NULLIF(TRIM(link_original), ''), titulo)
            ORDER BY total DESC, label
            LIMIT ?
        """, (max(int(limit), 1),))

    def recent_sends(self, limit=15):
        required = ("loja", "titulo", "canal", "status", "data")
        if not self._has_columns("historico_envios", *required):
            return ()
        rows = self.connection.execute("""
            SELECT loja, titulo, canal, status, data
            FROM historico_envios
            WHERE status = 'enviado'
            ORDER BY data DESC, id DESC
            LIMIT ?
        """, (max(int(limit), 1),)).fetchall()
        return tuple(
            RecentSend(
                store=str(row["loja"] or ""),
                title=str(row["titulo"] or ""),
                channel=str(row["canal"] or ""),
                status=str(row["status"] or ""),
                sent_at=str(row["data"] or ""),
            )
            for row in rows
        )

    def time_series(self, table, date_column, weekly=False):
        if not self._has_columns(table, date_column):
            return ()
        period = (
            f"strftime('%Y-W%W', {date_column})"
            if weekly else f"date({date_column})"
        )
        where = ""
        if table == "historico_envios" and self._has_columns(table, "status"):
            where = "WHERE status = 'enviado'"
        rows = self.connection.execute(f"""
            SELECT {period} AS period, COUNT(*) AS total
            FROM {table}
            {where}
            GROUP BY {period}
            HAVING period IS NOT NULL
            ORDER BY period
        """).fetchall()
        return tuple(
            TimeSeriesPoint(str(row["period"]), int(row["total"]))
            for row in rows
        )

    def product_categories(self, limit=10):
        if not self._table_exists("produtos"):
            return CoverageCount()
        columns = self._table_columns("produtos")
        total = self._count("produtos")
        candidates = [
            column for column in ("categoria_manual", "categoria_original")
            if column in columns
        ]
        if not candidates:
            return CoverageCount(total=total)
        expressions = [f"NULLIF(TRIM({column}), '')" for column in candidates]
        category = f"COALESCE({', '.join(expressions)})"
        covered = self._scalar(
            f"SELECT COUNT(*) FROM produtos WHERE {category} IS NOT NULL"
        )
        items = self._groups(f"""
            SELECT COALESCE({category}, 'Sem categoria') AS label,
                   COUNT(*) AS total
            FROM produtos
            GROUP BY COALESCE({category}, 'Sem categoria')
            ORDER BY total DESC, label
            LIMIT ?
        """, (max(int(limit), 1),))
        return CoverageCount(items=items, covered=covered, total=total)

    def sent_categories(self, limit=10):
        product_columns = self._table_columns("produtos")
        history_columns = self._table_columns("historico_envios")
        required_products = {"link"}
        required_history = {"link_original", "status"}
        total = self._count(
            "historico_envios",
            "status = 'enviado'",
        ) if "status" in history_columns else 0
        category_columns = [
            column for column in ("categoria_manual", "categoria_original")
            if column in product_columns
        ]
        if (
            not required_products <= product_columns
            or not required_history <= history_columns
            or not category_columns
        ):
            return CoverageCount(total=total)
        expressions = [
            f"NULLIF(TRIM(p.{column}), '')" for column in category_columns
        ]
        category = f"COALESCE({', '.join(expressions)})"
        covered = self._scalar(f"""
            SELECT COUNT(*)
            FROM historico_envios h
            JOIN produtos p ON p.link = h.link_original
            WHERE h.status = 'enviado' AND {category} IS NOT NULL
        """)
        items = self._groups(f"""
            SELECT {category} AS label, COUNT(*) AS total
            FROM historico_envios h
            JOIN produtos p ON p.link = h.link_original
            WHERE h.status = 'enviado' AND {category} IS NOT NULL
            GROUP BY {category}
            ORDER BY total DESC, label
            LIMIT ?
        """, (max(int(limit), 1),))
        return CoverageCount(items=items, covered=covered, total=total)

    def commercial_averages(self):
        total = self._count("produtos")
        required = ("preco_valor", "preco_antigo")
        if not self._has_columns("produtos", *required):
            empty = CoverageAverage(total=total)
            return empty, empty
        row = self.connection.execute("""
            SELECT COUNT(*) AS covered,
                   AVG((preco_antigo - preco_valor) / preco_antigo * 100.0)
                       AS average_discount,
                   AVG(preco_antigo - preco_valor) AS average_savings
            FROM produtos
            WHERE preco_valor > 0 AND preco_antigo > preco_valor
        """).fetchone()
        covered = int(row["covered"] or 0)
        discount = CoverageAverage(
            average=float(row["average_discount"] or 0),
            covered=covered,
            total=total,
        )
        savings = CoverageAverage(
            average=float(row["average_savings"] or 0),
            covered=covered,
            total=total,
        )
        return discount, savings

    def snapshot(self, category_limit=10):
        total_products = self._count("produtos")
        total_sends = (
            self._count("historico_envios", "status = 'enviado'")
            if self._has_columns("historico_envios", "status") else 0
        )
        pending_reviews = (
            self._count("pendencias_revisao", "status = 'pendente'")
            if self._has_columns("pendencias_revisao", "status") else 0
        )
        active_alerts = (
            self._count("alertas", "ativo = 1")
            if self._has_columns("alertas", "ativo") else 0
        )
        failed_deliveries = 0
        if self._has_columns("entregas_destino", "status"):
            placeholders = ", ".join("?" for _ in self.FAILURE_STATES)
            failed_deliveries = self._count(
                "entregas_destino",
                f"status IN ({placeholders})",
                self.FAILURE_STATES,
            )
        discount, savings = self.commercial_averages()
        return StatisticsSnapshot(
            total_products=total_products,
            total_sends=total_sends,
            pending_reviews=pending_reviews,
            active_alerts=active_alerts,
            failed_deliveries=failed_deliveries,
            products_by_store=self.products_by_store(),
            sends_by_channel=self.sends_by_channel(),
            most_sent_products=self.most_sent_products(),
            recent_sends=self.recent_sends(),
            daily_collections=self.time_series("produtos", "data"),
            daily_sends=self.time_series("historico_envios", "data"),
            weekly_collections=self.time_series(
                "produtos", "data", weekly=True
            ),
            weekly_sends=self.time_series(
                "historico_envios", "data", weekly=True
            ),
            products_by_category=self.product_categories(category_limit),
            sent_categories=self.sent_categories(category_limit),
            average_discount=discount,
            average_savings=savings,
        )

    def close(self):
        if not self.closed:
            self.connection.close()
            self.closed = True
