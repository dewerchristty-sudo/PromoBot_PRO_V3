import hashlib
import sqlite3

from src.delivery_diagnostics import DeliveryDiagnosticsRepository


def create_databases(tmp_path):
    hunter = tmp_path / "hunter.db"
    main = tmp_path / "main.db"
    connection = sqlite3.connect(hunter)
    connection.executescript("""
        CREATE TABLE promotion_hunter_runs(
            status TEXT, collected_count INTEGER, unique_count INTEGER
        );
        CREATE TABLE promotion_hunter_decisions(
            decision_status TEXT, reason TEXT, created_at TEXT
        );
        CREATE TABLE promotion_hunter_delivery_queue(
            id INTEGER, store TEXT, title TEXT, status TEXT, attempts INTEGER,
            last_error TEXT, product_url TEXT, image_url TEXT, updated_at TEXT
        );
        CREATE TABLE promotion_hunter_delivery_attempts(
            status TEXT, error_message TEXT
        );
        INSERT INTO promotion_hunter_runs VALUES('success',10,9);
        INSERT INTO promotion_hunter_decisions VALUES
            ('aprovado','oferta_aprovada','2026-08-01 10:00:00'),
            ('descartado','duplicidade_ativa','2026-08-01 10:00:00'),
            ('pendente','link_afiliado_ausente','2026-08-01 10:00:00'),
            ('pendente','SQLite objects created in a thread','2026-08-01 11:00:00');
        INSERT INTO promotion_hunter_delivery_queue VALUES(
            1,'Amazon','Produto','failed',1,
            'A imagem possui 320 x 320 pixels','url-produto','url-imagem',
            '2026-08-01 12:00:00'
        );
        INSERT INTO promotion_hunter_delivery_attempts VALUES
            ('failed','imagem inválida'),('sent','');
    """)
    connection.commit()
    connection.close()
    connection = sqlite3.connect(main)
    connection.executescript("""
        CREATE TABLE historico_envios(canal TEXT);
        INSERT INTO historico_envios VALUES('WhatsApp');
    """)
    connection.commit()
    connection.close()
    return hunter, main


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_operational_funnel_uses_real_hunter_tables(tmp_path):
    hunter, main = create_databases(tmp_path)
    repository = DeliveryDiagnosticsRepository(hunter, main)
    snapshot = repository.snapshot()
    repository.close()
    stages = {stage.name: stage for stage in snapshot.funnel}
    assert stages["Produtos coletados"].total == 10
    assert stages["Produtos normalizados"].total == 9
    assert stages["Produtos aprovados"].total == 1
    assert stages["Bloqueados por duplicidade"].total == 1
    assert stages["Bloqueados por afiliado"].total == 1
    assert stages["Bloqueados por imagem"].total == 1
    assert stages["Entrega final confirmada"].total is None
    assert "não é persistida" in stages["Entrega final confirmada"].main_reason


def test_trace_identifies_exact_image_stage(tmp_path):
    hunter, main = create_databases(tmp_path)
    repository = DeliveryDiagnosticsRepository(hunter, main)
    snapshot = repository.snapshot()
    repository.close()
    assert snapshot.traces[0].stage == "IMAGEM"
    assert snapshot.traces[0].store == "Amazon"
    assert snapshot.traces[0].product_url == "url-produto"
    assert snapshot.traces[0].image_url == "url-imagem"


def test_diagnostics_are_strictly_read_only(tmp_path):
    hunter, main = create_databases(tmp_path)
    before = (digest(hunter), digest(main))
    repository = DeliveryDiagnosticsRepository(hunter, main)
    repository.snapshot()
    with sqlite3.connect(hunter) as verification:
        expected_rows = verification.execute(
            "SELECT COUNT(*) FROM promotion_hunter_decisions"
        ).fetchone()[0]
    repository.close()
    assert expected_rows == 4
    assert before == (digest(hunter), digest(main))
def test_missing_hunter_database_uses_empty_read_only_snapshot(tmp_path):
    main = tmp_path / "main.db"
    connection = sqlite3.connect(main)
    connection.execute(
        "CREATE TABLE historico_envios (canal TEXT)"
    )
    connection.close()

    repository = DeliveryDiagnosticsRepository(
        tmp_path / "promotion_hunter.db", main
    )
    try:
        snapshot = repository.snapshot()
    finally:
        repository.close()

    assert snapshot.funnel[0].total == 0
    assert not (tmp_path / "promotion_hunter.db").exists()
