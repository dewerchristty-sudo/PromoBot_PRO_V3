from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_pilot_dry_run import ForbiddenPilotTransport, run
from src.pilot import (
    CONFIRMATION_PHRASE, PilotConfig, PilotManager,
    PilotMessageFormatter, PilotProduct, validate_pilot_config,
)
from src.pilot.reports import write_diagnostic


class PilotTest(unittest.TestCase):

    def product(self, **changes):
        values = {
            "title": "SSD NVMe Kingston 1TB NV3",
            "store": "Mercado Livre",
            "current_price": 399.90,
            "previous_price": 499.90,
            "discount_percent": 20.0,
            "affiliate_url": "https://meli.la/link-oficial-secreto",
            "affiliate_valid": True,
            "image_available": True,
            "score": 95.0,
            "threshold": 90.0,
            "operationally_ready": True,
            "selected": True,
            "approved": True,
            "identity": "identidade-1",
        }
        values.update(changes)
        return PilotProduct(**values)

    def config(self, **changes):
        values = {
            "enabled": True,
            "group_id": "grupo-piloto-real",
            "max_messages": 1,
            "require_manual_confirmation": True,
            "allowed_stores": ("Mercado Livre",),
            "minimum_score": 90,
            "cooldown_minutes": 60,
            "auto_stop_on_error": True,
            "authorization_timeout_seconds": 60,
        }
        values.update(changes)
        return PilotConfig(**values)

    def test_piloto_desabilitado(self):
        decision = PilotManager(
            self.config(enabled=False)
        ).evaluate(self.product())
        self.assertEqual(decision.reason, "PILOT_DISABLED")

    def test_grupo_ausente(self):
        status = validate_pilot_config(
            self.config(group_id=""), 90
        )
        self.assertEqual(status.state, "CONFIGURATION_REQUIRED")
        self.assertIn("PILOT_GROUP_ID_MISSING", status.reasons)

    def test_configuracao_invalida_nao_reduz_threshold(self):
        status = validate_pilot_config(
            self.config(minimum_score=50), 90
        )
        self.assertFalse(status.valid)
        self.assertIn(
            "PILOT_SCORE_BELOW_PIPELINE_THRESHOLD", status.reasons
        )

    def test_produto_sem_afiliado(self):
        decision = PilotManager(self.config()).evaluate(
            self.product(affiliate_url="", affiliate_valid=False)
        )
        self.assertEqual(decision.reason, "AFFILIATE_LINK_REQUIRED")

    def test_produto_nao_operacionalmente_pronto(self):
        decision = PilotManager(self.config()).evaluate(
            self.product(operationally_ready=False)
        )
        self.assertEqual(decision.reason, "NOT_OPERATIONALLY_READY")

    def test_produto_pronto_abaixo_do_threshold(self):
        decision = PilotManager(self.config()).evaluate(
            self.product(score=15, selected=False)
        )
        self.assertTrue(decision.operationally_ready)
        self.assertFalse(decision.selected)
        self.assertFalse(decision.authorized)
        self.assertEqual(decision.reason, "SCORE_BELOW_THRESHOLD")

    def test_produto_selecionado_aguarda_confirmacao(self):
        decision = PilotManager(self.config()).evaluate(self.product())
        self.assertEqual(decision.state, "DRY_RUN")
        self.assertEqual(
            decision.reason, "MANUAL_CONFIRMATION_REQUIRED"
        )

    def test_confirmacao_manual_nao_pode_ser_desativada(self):
        decision = PilotManager(
            self.config(require_manual_confirmation=False)
        ).evaluate(self.product())
        self.assertEqual(
            decision.reason, "PILOT_CONFIGURATION_REQUIRED"
        )

    def test_autorizacao_expira_e_nao_e_reutilizada(self):
        now = [datetime(2026, 7, 26, tzinfo=timezone.utc)]
        manager = PilotManager(self.config(), clock=lambda: now[0])
        authorization, result = manager.authorize(
            self.product(), CONFIRMATION_PHRASE
        )
        self.assertEqual(result.state, "AUTHORIZED")
        now[0] += timedelta(minutes=2)
        valid, reason = manager.consume_authorization(
            authorization.authorization_id
        )
        self.assertFalse(valid)
        self.assertEqual(reason, "AUTHORIZATION_EXPIRED")

    def test_limite_de_mensagens(self):
        manager = PilotManager(
            self.config(),
            sent_history=[datetime.now(timezone.utc)],
        )
        self.assertEqual(
            manager.evaluate(self.product()).reason,
            "MESSAGE_LIMIT_REACHED",
        )

    def test_cooldown(self):
        manager = PilotManager(
            self.config(max_messages=2),
            sent_history=[datetime.now(timezone.utc)],
        )
        self.assertEqual(
            manager.evaluate(self.product()).reason, "COOLDOWN_ACTIVE"
        )

    def test_auto_stop(self):
        manager = PilotManager(self.config())
        manager.record_error("inconsistencia")
        decision = manager.evaluate(self.product())
        self.assertEqual(decision.state, "AUTO_STOPPED")
        self.assertTrue(decision.auto_stopped)

    def test_previa_mascara_link_e_nao_inventa_valores(self):
        product = self.product(previous_price=0, discount_percent=0)
        decision = PilotManager(self.config()).evaluate(product)
        preview = PilotMessageFormatter().format(product, decision)
        self.assertNotIn(product.affiliate_url, preview)
        self.assertNotIn("Preco anterior:", preview)
        self.assertIn("NOT_AUTHORIZED_FOR_PILOT", preview)

    def test_relatorios_nao_expoem_grupo(self):
        secret = "grupo-completo-secreto"
        payload = {
            "configuration": {
                "enabled": True, "group_configured": True,
                "manual_confirmation": True,
            },
            "product": {
                "score": 15, "threshold": 90,
                "operationally_ready": True, "selected": False,
                "authorized": False,
            },
            "pilot": {
                "state": "DISABLED", "reason": "SCORE_BELOW_THRESHOLD",
            },
            "transport": {"called": False},
        }
        with tempfile.TemporaryDirectory() as directory:
            paths = write_diagnostic(payload, Path(directory))
            text = "\n".join(
                path.read_text(encoding="utf-8-sig") for path in paths
            )
        self.assertNotIn(secret, text)

    @patch("scripts.run_pilot_dry_run.load_pilot_product")
    def test_dry_run_nunca_chama_transporte(self, loader):
        loader.return_value = (
            self.product(score=15, selected=False),
            {"safety": {"transport_called": False}},
        )
        transport = ForbiddenPilotTransport()
        payload, _paths = run(self.config(), transport)
        self.assertFalse(transport.called)
        self.assertFalse(payload["product"]["authorized"])
        self.assertEqual(
            payload["decision"]["reason"], "SCORE_BELOW_THRESHOLD"
        )

    def test_modulo_piloto_nao_importa_producao(self):
        source = "\n".join(
            path.read_text(encoding="utf-8").casefold()
            for path in Path("src/pilot").glob("*.py")
        )
        for forbidden in (
            "src.core.notifier", "send_whatsapp", "evolution",
            "offerscheduler", "offercanary",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
