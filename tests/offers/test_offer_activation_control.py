from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
import unittest

from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.activation import OfferActivationFlags
from src.offers.activation_control import (
    CANARY_SAFE_5_PERCENT,
    SAFE_CONFIRMATION,
    OfferActivationManager,
    OfferPreflight,
)
from src.offers.activation_report import OfferActivationReport
from src.offers.auto_stop import OfferCanaryAutoStop
from src.offers.canary import OfferCanaryController


class OfferActivationControlTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.config = root / "activation.json"
        self.repository = OfferPipelineRepository(root / "shadow.db")
        self.repository.migrate()
        self.environment = patch.dict(os.environ, {
            "OFFER_ACTIVATION_CONFIG_PATH": str(self.config),
            "OFFER_INTELLIGENT_SCHEDULER_ENABLED": "False",
            "OFFER_CANARY_PERCENT": "0",
        })
        self.environment.start()
        self.manager = OfferActivationManager(
            self.repository, self.config
        )

    def tearDown(self):
        self.repository.close()
        self.environment.stop()
        self.tempdir.cleanup()

    def test_perfil_seguro_e_preverificacoes_aprovadas(self):
        flags = CANARY_SAFE_5_PERCENT.flags()
        checks = OfferPreflight(self.repository).run(flags)
        self.assertTrue(all(check.passed for check in checks))
        self.assertEqual(flags.canary_percent, 5)
        self.assertEqual(flags.minimum_score_to_send, 90)
        self.assertEqual(flags.max_send_per_hour, 1)
        self.assertEqual(flags.max_send_per_day, 3)
        self.assertTrue(flags.dry_run_transport)

    def test_preverificacao_reprovada_sem_rollback_bloqueia(self):
        profile = replace(
            CANARY_SAFE_5_PERCENT, name="SEM_ROLLBACK"
        )
        with patch.object(
            profile.__class__, "flags",
            return_value=replace(profile.flags(), enable_rollback=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "Rollback"):
                self.manager.activate(
                    profile, "tester", "CONFIRMO DRY RUN"
                )
        self.assertFalse(self.config.exists())

    def test_confirmacao_obrigatoria_nao_altera_configuracao(self):
        with self.assertRaises(PermissionError):
            self.manager.activate(
                CANARY_SAFE_5_PERCENT, "tester", "sim"
            )
        self.assertFalse(self.config.exists())

    def test_sessao_dry_run_persistida_e_reiniciada(self):
        session_id = self.manager.activate(
            CANARY_SAFE_5_PERCENT, "tester", "CONFIRMO DRY RUN"
        )
        flags = OfferActivationFlags.from_environment()
        self.assertTrue(flags.intelligent_scheduler_enabled)
        self.assertTrue(flags.dry_run_transport)
        session = self.repository.current_activation_session()
        self.assertEqual(session["id"], session_id)
        self.assertEqual(session["status"], "dry_run")
        restarted = OfferActivationManager(
            self.repository, self.config
        )
        self.assertEqual(
            restarted.repository.current_activation_session()["id"],
            session_id,
        )

    def test_canary_real_exige_frase_forte(self):
        with self.assertRaises(PermissionError):
            self.manager.activate(
                CANARY_SAFE_5_PERCENT, "tester",
                "CONFIRMO DRY RUN", real_transport=True,
            )
        session = self.manager.activate(
            CANARY_SAFE_5_PERCENT, "tester",
            SAFE_CONFIRMATION, real_transport=True,
        )
        self.assertEqual(
            self.repository.current_activation_session()["id"], session
        )
        self.assertFalse(
            OfferActivationFlags.from_environment().dry_run_transport
        )

    def test_desativacao_imediata_preserva_dados_e_audita(self):
        session = self.manager.activate(
            CANARY_SAFE_5_PERCENT, "tester", "CONFIRMO DRY RUN"
        )
        self.manager.deactivate("tester", "fim do teste")
        flags = OfferActivationFlags.from_environment()
        self.assertFalse(flags.intelligent_scheduler_enabled)
        self.assertEqual(flags.canary_percent, 0)
        stored = self.repository.read_one(
            "SELECT * FROM offer_activation_sessions WHERE id=?", (session,)
        )
        self.assertEqual(stored["status"], "manually_stopped")
        events = self.repository.read_all(
            "SELECT * FROM offer_activation_events WHERE session_id=?",
            (session,),
        )
        self.assertGreaterEqual(len(events), 2)

    def test_dry_run_decide_audita_e_nao_chama_transporte(self):
        self.manager.activate(
            CANARY_SAFE_5_PERCENT, "tester", "CONFIRMO DRY RUN"
        )
        self.repository.conn.execute("""
            INSERT INTO offer_pipeline_runs(run_id, created_at)
            VALUES('dry-run', ?)
        """, (self.repository.iso(datetime.now(timezone.utc)),))
        self.repository.conn.execute("""
            INSERT INTO offer_pipeline_items(
                run_id,title,store,score,filter_approved,created_at
            ) VALUES('dry-run','Produto','Amazon',95,1,?)
        """, (self.repository.iso(datetime.now(timezone.utc)),))
        self.repository.conn.commit()
        transport = Mock()
        with patch.object(
            OfferCanaryController, "bucket", staticmethod(lambda _identity: 99)
        ):
            controller = OfferCanaryController(
                self.repository, OfferActivationFlags.from_environment()
            )
            sample = [{
                "titulo": "Produto", "loja": "Amazon",
                "link": "https://example.com/p",
            }]
            decision = controller.decide(sample)[0]
            self.assertEqual(
                (decision.scheduler, decision.legacy_decision),
                ("legado", "enviar"),
            )
            result = controller.execute(sample, transport)
        self.assertEqual(result, "simulated_send")
        transport.assert_not_called()
        audit = self.repository.read_one(
            "SELECT * FROM offer_canary_decisions"
        )
        self.assertEqual(audit["result"], "simulated_send")

    def test_auto_stop_desativa_e_registra(self):
        self.manager.activate(
            CANARY_SAFE_5_PERCENT, "tester", "CONFIRMO DRY RUN"
        )
        self.manager.auto_stop("duplicidade detectada", {"duplicates": 1})
        flags = OfferActivationFlags.from_environment()
        self.assertFalse(flags.intelligent_scheduler_enabled)
        self.assertEqual(
            self.repository.latest_activation_session()["status"],
            "auto_stopped",
        )
        self.assertEqual(
            self.repository.read_one(
                "SELECT COUNT(*) total FROM offer_canary_auto_stops"
            )["total"],
            1,
        )

    def test_auto_stop_por_erros_duplicidade_e_auditoria(self):
        repository = Mock()
        evaluator = OfferCanaryAutoStop(repository)
        base = {
            "consecutive_errors": 0, "rollbacks_hour": 0,
            "error_rate_percent": 0, "average_decision_ms": 0,
            "duplicates": 0, "audit_failures": 0,
            "limit_violations": 0,
        }
        flags = OfferActivationFlags()
        for field, expected in (
            ("consecutive_errors", "Erros consecutivos"),
            ("duplicates", "Duplicidade"),
            ("audit_failures", "auditoria"),
        ):
            metrics = {**base, field: 3 if field == "consecutive_errors" else 1}
            repository.canary_safety_metrics.return_value = metrics
            self.assertIn(expected, evaluator.evaluate(flags))

    def test_relatorio_csv_e_json(self):
        now = datetime.now(timezone.utc)
        self.repository.record_canary_decisions([{
            "audit_id": "report-1", "identity": "identity-report",
            "title": "Produto", "store": "Amazon",
            "category": "Tecnologia", "score": 95,
            "scheduler": "inteligente", "legacy_decision": "enviar",
            "intelligent_decision": "enviar", "difference": "nao",
            "reason": "aprovado", "flags_json": "{}",
            "canary_percent": 5, "result": "simulated_send",
            "sent": False, "rollback_reason": "",
            "decision_ms": 2.5, "created_at": now,
        }])
        report = OfferActivationReport(self.repository)
        data = report.build()
        self.assertEqual(data["decisions"], 1)
        csv_path = report.export_csv(
            Path(self.tempdir.name) / "report.csv"
        )
        json_path = report.export_json(
            Path(self.tempdir.name) / "report.json"
        )
        self.assertIn("Produto", csv_path.read_text(encoding="utf-8-sig"))
        self.assertEqual(
            json.loads(json_path.read_text(encoding="utf-8"))["decisions"], 1
        )

    def test_env_real_nao_e_editado(self):
        env_path = Path(".env")
        before = env_path.read_bytes()
        self.manager.activate(
            CANARY_SAFE_5_PERCENT, "tester", "CONFIRMO DRY RUN"
        )
        self.assertEqual(env_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
