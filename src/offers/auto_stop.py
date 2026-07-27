class OfferCanaryAutoStop:
    def __init__(self, repository):
        self.repository = repository

    def evaluate(self, flags):
        if not flags.auto_stop_enabled:
            return ""
        metrics = self.repository.canary_safety_metrics()
        if metrics["consecutive_errors"] >= flags.max_consecutive_errors:
            return "Erros consecutivos acima do limite."
        if metrics["rollbacks_hour"] > flags.max_rollbacks_per_hour:
            return "Rollbacks repetidos na última hora."
        if metrics["error_rate_percent"] > flags.max_error_rate_percent:
            return "Taxa de erro acima do limite."
        if metrics["average_decision_ms"] > flags.max_decision_time_ms:
            return "Tempo médio de decisão acima do limite."
        if flags.stop_on_duplicate and metrics["duplicates"] > 0:
            return "Duplicidade detectada."
        if flags.stop_on_audit_failure and metrics["audit_failures"] > 0:
            return "Falha de auditoria detectada."
        if metrics["limit_violations"] > 0:
            return "Envios acima dos limites configurados."
        return ""
