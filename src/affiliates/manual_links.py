from __future__ import annotations

from contextlib import closing
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from src.stores.active import normalize_store_name

from .validation import product_identity


class ManualAffiliateLinkLookup:
    """Consulta os vínculos salvos pela tela manual sem alterar o banco."""

    def __init__(self, database_path: str | Path | None = None):
        self.database_path = (
            Path(database_path) if database_path else self.default_database_path()
        )

    @staticmethod
    def default_database_path() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "promobot.db"
        return Path("promobot.db")

    @staticmethod
    def normalize_url(value: str) -> str:
        parts = urlsplit(str(value or "").strip())
        return urlunsplit((
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/"),
            "",
            "",
        ))

    def resolve(self, store: str, original_url: str) -> tuple[str, str]:
        store_normalized = normalize_store_name(store)
        if not store_normalized:
            return "", ""

        path = self.database_path.resolve()
        if not path.is_file():
            return "", ""

        try:
            with closing(sqlite3.connect(
                path.as_uri() + "?mode=ro", uri=True, timeout=5
            )) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    "SELECT link_original, link_afiliado "
                    "FROM links_afiliados "
                    "WHERE lower(trim(loja)) = lower(trim(?))",
                    (store_normalized,),
                ).fetchall()
        except sqlite3.Error:
            return "", ""

        if not rows:
            return "", ""

        requested_identity = product_identity(store, original_url)
        if requested_identity:
            identity_matches = [
                str(row["link_afiliado"] or "").strip()
                for row in rows
                if product_identity(store, row["link_original"])
                == requested_identity
            ]
            unique_matches = tuple(dict.fromkeys(
                value for value in identity_matches if value
            ))
            if len(unique_matches) == 1:
                return unique_matches[0], "manual_registry_identity"

        normalized = self.normalize_url(original_url)
        for row in rows:
            if self.normalize_url(row["link_original"]) == normalized:
                return (
                    str(row["link_afiliado"] or "").strip(),
                    "manual_registry_url",
                )
        return "", ""

    def close(self):
        pass
