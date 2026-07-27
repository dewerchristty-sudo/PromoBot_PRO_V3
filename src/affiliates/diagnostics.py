from dataclasses import asdict
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import time

from .config import AffiliateConfig
from .manager import AffiliateManager
from .validation import (
    StoreValidation, is_placeholder, validate_store_config,
)


SAMPLE_URLS = {
    "Mercado Livre": "https://produto.mercadolivre.com.br/MLB-987654321",
    "Amazon": "https://www.amazon.com.br/dp/B0SAFE98765",
    "Shopee": "https://shopee.com.br/produto-i.98765.43210",
}


def validation_url(store, config, provider):
    entries = provider.mapping_entries(config.mapping)
    if not entries:
        return SAMPLE_URLS[store]
    key = entries[0][0]
    if store == "Mercado Livre" and key.upper().replace("-", "").startswith("MLB"):
        digits = "".join(character for character in key if character.isdigit())
        return f"https://produto.mercadolivre.com.br/MLB-{digits}"
    separator = "&" if "?" in SAMPLE_URLS[store] else "?"
    return f"{SAMPLE_URLS[store]}{separator}affiliate_map_key={key}"


def mercado_livre_session_status(
    profile_path=Path("data/browser_profiles/mercado_livre"),
    diagnostic_path=Path("logs/mercado_livre_diagnostico.txt"),
):
    text = ""
    if diagnostic_path.exists():
        text = diagnostic_path.read_text(
            encoding="utf-8", errors="ignore"
        ).casefold()
    if "account-verification" in text or "captcha" in text:
        return "VERIFICATION_REQUIRED"
    if "login_required" in text or "login required" in text:
        return "LOGIN_REQUIRED"
    if "access denied" in text or "blocked_temporarily" in text:
        return "BLOCKED_TEMPORARILY"
    if profile_path.exists() and profile_path.is_dir() and any(
        profile_path.iterdir()
    ):
        return "SESSION_READY"
    return "UNKNOWN_SESSION_STATE"


class AffiliateDiagnostics:

    def __init__(self, config=None, manager=None):
        self.config = config or AffiliateConfig.from_environment()
        self.manager = manager or AffiliateManager(self.config)
        self.owns_manager = manager is None

    def run(self):
        started = time.perf_counter()
        rows = []
        stores = (
            ("Mercado Livre", self.config.mercado_livre),
            ("Amazon", self.config.amazon),
            ("Shopee", self.config.shopee),
        )
        for store, config in stores:
            provider = self.manager.providers[store.casefold()]
            initial = validate_store_config(store, config, provider)
            final = initial
            generation_status = "bloqueada"
            result_status = ""
            mapping_only = bool(config.mapping and not config.template)
            if initial.generation_available and mapping_only:
                final = StoreValidation(
                    store, "CONFIGURED", True, False, True,
                    "mapa_oficial_valido_com_cobertura_por_produto",
                    masked_values=initial.masked_values,
                )
                generation_status = "disponivel_somente_para_mapeados"
                result_status = "MAPPING_COVERAGE_REQUIRED"
            elif initial.generation_available:
                result = self.manager.resolve(
                    store, validation_url(store, config, provider)
                )
                result_status = result.status
                if result.valid:
                    final = StoreValidation(
                        store, "VALIDATED", True, True, True,
                        "geracao_e_link_validados",
                        masked_values=initial.masked_values,
                    )
                    generation_status = "disponivel"
                else:
                    final = StoreValidation(
                        store, "VALIDATION_FAILED", True, False, False,
                        result.error or "falha_na_geracao",
                        masked_values=initial.masked_values,
                    )
            session = (
                mercado_livre_session_status()
                if store == "Mercado Livre" else ""
            )
            row = asdict(final)
            row.update({
                "session_status": session,
                "generation": generation_status,
                "generation_result": result_status,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "config_audit": {
                    "env_file_found": self.config.env_file_found,
                    "env_path": str(self.config.env_path),
                    "map_present": bool(config.mapping),
                    "template_present": bool(config.template),
                    "map_empty": not bool(config.mapping.strip()),
                    "template_empty": not bool(config.template.strip()),
                    "placeholder_detected": any(is_placeholder(value) for value in (
                        config.affiliate_id, config.associate_tag,
                        config.api_token, config.template, config.api_url,
                    ) if value),
                    "configuration_valid": initial.status == "CONFIGURED",
                    "adapter": provider.__class__.__name__,
                    "manager_status": (
                        "AVAILABLE_FOR_MAPPED_PRODUCTS"
                        if mapping_only and initial.generation_available
                        else "AVAILABLE" if final.validated else "BLOCKED"
                    ),
                },
            })
            rows.append(row)
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "stores": rows,
            "summary": {
                "configured": sum(row["configured"] for row in rows),
                "validated": sum(row["validated"] for row in rows),
                "blocked": sum(not row["validated"] for row in rows),
            },
        }

    def close(self):
        if self.owns_manager:
            self.manager.close()


def write_validation_reports(report, directory="reports/affiliate_validation"):
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "affiliate_validation.json"
    csv_path = output / "affiliate_validation.csv"
    summary_path = output / "affiliate_validation_summary.txt"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows = [{
        "store": row["store"], "status": row["status"],
        "configured": row["configured"], "validated": row["validated"],
        "generation": row["generation"], "reason": row["reason"],
        "session_status": row["session_status"],
        "checked_at": row["checked_at"],
    } for row in report["stores"]]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ["PROMOBOT - VALIDACAO DE AFILIADOS", ""]
    for row in rows:
        lines.extend((
            row["store"], f"- configuracao: {row['status']}",
            f"- geracao: {row['generation']}",
            f"- sessao: {row['session_status'] or 'nao aplicavel'}",
            f"- motivo: {row['reason']}", "",
        ))
    summary = report["summary"]
    lines.extend((
        "Resumo", f"- lojas configuradas: {summary['configured']}",
        f"- lojas validadas: {summary['validated']}",
        f"- lojas bloqueadas: {summary['blocked']}",
    ))
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return (json_path, csv_path, summary_path)
