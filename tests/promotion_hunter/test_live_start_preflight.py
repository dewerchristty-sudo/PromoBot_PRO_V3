import hashlib
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.promotion_hunter.live_start import LiveStartPreflight


TZ = ZoneInfo("America/Sao_Paulo")


class WhatsApp:
    def __init__(self, state="open", error=None):
        self.state = state
        self.error = error
    def connection_state(self):
        if self.error:
            raise self.error
        return self.state


def database(path, *, scheduler=0, backlog=0):
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE promotion_hunter_scheduler_state(
            singleton_id INTEGER PRIMARY KEY, running INTEGER
        );
        CREATE TABLE promotion_hunter_delivery_queue(
            id INTEGER PRIMARY KEY, status TEXT, approved_at TEXT
        );
        INSERT INTO promotion_hunter_scheduler_state VALUES(1, 0);
    """)
    connection.execute(
        "UPDATE promotion_hunter_scheduler_state SET running=?", (scheduler,)
    )
    for identifier in range(backlog):
        connection.execute(
            "INSERT INTO promotion_hunter_delivery_queue VALUES(?, 'pending', datetime('now','-25 hours'))",
            (identifier + 1,),
        )
    connection.commit()
    connection.close()


def app_database(path, accelerated="false"):
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE configuracoes_app(chave TEXT PRIMARY KEY, valor TEXT)"
    )
    connection.execute(
        "INSERT INTO configuracoes_app VALUES"
        "('promotion_hunter_accelerated_mode', ?)", (accelerated,)
    )
    connection.commit()
    connection.close()


@pytest.fixture
def configured(monkeypatch, tmp_path):
    hunter = tmp_path / "hunter_test.sqlite"
    app = tmp_path / "promobot.db"
    env = tmp_path / ".env"
    env.write_text("AMAZON_ASSOCIATE_TAG=miguelchristt-20\n", encoding="utf-8")
    database(hunter)
    app_database(app)
    monkeypatch.setenv("PROMOBOT_ENV_PATH", str(env))
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    monkeypatch.setenv("PROMOTION_HUNTER_REAL_SEND_AUTHORIZED", "true")
    monkeypatch.setenv("AMAZON_ASSOCIATE_TAG", "miguelchristt-20")
    monkeypatch.setenv(
        "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA", "120000000000@g.us"
    )
    return hunter, app


def guard(paths, **kwargs):
    hunter, app = paths
    return LiveStartPreflight(
        hunter, app, whatsapp=kwargs.pop("whatsapp", WhatsApp()),
        clock=kwargs.pop("clock", lambda: datetime(2026, 8, 3, 12, tzinfo=TZ)),
        lock_checker=kwargs.pop("lock_checker", lambda: False),
    )


def test_authorized_preflight_is_read_only_and_applies_safe_limits(configured):
    before = hashlib.sha256(configured[0].read_bytes()).hexdigest()
    result = guard(configured).run()
    after = hashlib.sha256(configured[0].read_bytes()).hexdigest()
    assert result.allowed and not result.errors
    assert before == after
    assert result.details["stores"] == ("Amazon",)
    assert result.details["max_per_cycle"] == 1
    assert result.details["max_per_session"] == 2
    assert result.details["pending_backlog"] == 0


@pytest.mark.parametrize("name", [
    "PROMOTION_HUNTER_LIVE_DELIVERY",
    "PROMOTION_HUNTER_REAL_SEND_AUTHORIZED",
])
def test_missing_or_false_authorization_blocks(configured, monkeypatch, name):
    monkeypatch.setenv(name, "false")
    result = guard(configured).run()
    assert not result.allowed
    assert any(name in item for item in result.errors)


@pytest.mark.parametrize("state", ["close", "connecting", "unknown"])
def test_whatsapp_not_open_blocks(configured, state):
    assert not guard(configured, whatsapp=WhatsApp(state)).run().allowed


def test_evolution_offline_blocks(configured):
    result = guard(
        configured, whatsapp=WhatsApp(error=ConnectionError("offline"))
    ).run()
    assert not result.allowed
    assert any("Evolution API" in item for item in result.errors)


def test_mutex_or_active_controller_blocks(configured):
    assert not guard(configured, lock_checker=lambda: True).run().allowed
    assert not guard(configured).run(controller_running=True).allowed


def test_outside_window_blocks(configured):
    result = guard(
        configured, clock=lambda: datetime(2026, 8, 3, 23, tzinfo=TZ)
    ).run()
    assert not result.allowed
    assert any("janela operacional" in item for item in result.errors)


def test_blocked_or_review_destination_blocks(configured, monkeypatch):
    destination = "120000000000@g.us"
    monkeypatch.setenv("PROMOTION_HUNTER_BLOCKED_GROUP", destination)
    assert not guard(configured).run().allowed
    monkeypatch.delenv("PROMOTION_HUNTER_BLOCKED_GROUP")
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", destination)
    assert not guard(configured).run().allowed


def test_old_backlog_is_reported_but_does_not_block(configured):
    """Backlog antigo e reportado via details, mas NAO bloqueia o LIVE."""
    connection = sqlite3.connect(configured[0])
    connection.execute(
        "INSERT INTO promotion_hunter_delivery_queue VALUES(1, 'pending', datetime('now','-25 hours'))"
    )
    connection.commit()
    connection.close()
    before = configured[0].read_bytes()
    result = guard(configured).run()
    # Old backlog does NOT block — LIVE is allowed
    assert result.allowed, f"Old backlog should not block. Errors: {result.errors}"
    assert result.details["pending_backlog"] == 1
    assert result.details["pending_total"] == 1
    assert result.details["pending_session"] == 0
    assert configured[0].read_bytes() == before


def test_session_items_do_not_block_live(configured):
    """Items aprovados nas ultimas 24h (sessao atual) NAO bloqueiam o LIVE."""
    connection = sqlite3.connect(configured[0])
    # Insert items with approved_at within the last hour (current session)
    for i in range(5):
        connection.execute(
            "INSERT INTO promotion_hunter_delivery_queue VALUES(?, 'pending', datetime('now','-1 hour'))",
            (i + 1,),
        )
    connection.commit()
    connection.close()
    before = configured[0].read_bytes()
    result = guard(configured).run()
    # Session items should NOT block — allowed=True
    assert result.allowed, f"Session items should not block. Errors: {result.errors}"
    assert result.details["pending_total"] == 5
    assert result.details["pending_session"] == 5
    assert result.details["pending_backlog"] == 0
    assert configured[0].read_bytes() == before


def test_mixed_session_and_backlog(configured):
    """Sessao atual + backlog: LIVE permitido, backlog reportado em details."""
    connection = sqlite3.connect(configured[0])
    for i in range(3):
        connection.execute(
            "INSERT INTO promotion_hunter_delivery_queue VALUES(?, 'pending', datetime('now','-1 hour'))",
            (i + 1,),
        )
    for i in range(3, 5):
        connection.execute(
            "INSERT INTO promotion_hunter_delivery_queue VALUES(?, 'pending', datetime('now','-25 hours'))",
            (i + 1,),
        )
    connection.commit()
    connection.close()
    result = guard(configured).run()
    # Old backlog does NOT block
    assert result.allowed, f"Mixed should allow LIVE. Errors: {result.errors}"
    assert result.details["pending_total"] == 5
    assert result.details["pending_session"] == 3
    assert result.details["pending_backlog"] == 2
