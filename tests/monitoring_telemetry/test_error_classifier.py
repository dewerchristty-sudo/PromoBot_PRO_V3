import unittest

from src.monitoring_telemetry.error_classifier import (
    classify_error,
    sanitize_error_message,
)


class MonitorTelemetryErrorClassifierTest(unittest.TestCase):

    def test_classifies_only_supported_evidence(self):
        cases = (
            (RuntimeError("HTTP 503"), "http_503"),
            (RuntimeError("captcha required"), "captcha"),
            (RuntimeError("Robot Check"), "robot_check"),
            (RuntimeError("verify page"), "verify_page"),
            (RuntimeError("traffic/error"), "traffic_error"),
            (TimeoutError("timed out"), "timeout"),
            (RuntimeError("page.goto navigation failed"), "navigation_error"),
            (RuntimeError("unexpected"), "unknown_error"),
        )
        for error, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(classify_error(error), expected)

    def test_none_has_no_classification(self):
        self.assertIsNone(classify_error(None))

    def test_sanitizes_sensitive_content_and_limits_message(self):
        message = (
            "token=segredo cookie=privado telefone 5511999999999 "
            "https://example.com/produto?token=abc "
            "data:image/png;base64,QUJDREVGRw== "
            + "x" * 500
        )
        sanitized = sanitize_error_message(message)
        self.assertNotIn("segredo", sanitized)
        self.assertNotIn("privado", sanitized)
        self.assertNotIn("5511999999999", sanitized)
        self.assertNotIn("token=abc", sanitized)
        self.assertNotIn("QUJDREVGRw", sanitized)
        self.assertLessEqual(len(sanitized), 300)


if __name__ == "__main__":
    unittest.main()
