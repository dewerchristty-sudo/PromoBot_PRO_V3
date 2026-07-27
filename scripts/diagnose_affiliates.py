from src.affiliates.diagnostics import (
    AffiliateDiagnostics, write_validation_reports,
)


def main():
    diagnostics = AffiliateDiagnostics()
    try:
        report = diagnostics.run()
        paths = write_validation_reports(report)
    finally:
        diagnostics.close()
    for row in report["stores"]:
        print(f"\n{row['store']}")
        print(f"- configuracao: {row['status']}")
        if row["session_status"]:
            print(f"- sessao do coletor: {row['session_status']}")
        print(f"- geracao: {row['generation']}")
        print(f"- motivo: {row['reason']}")
        audit = row.get("config_audit", {})
        if audit:
            print("- env_file_found:", audit["env_file_found"])
            print("- env_path:", audit["env_path"])
            print("- map_present:", audit["map_present"])
            print("- template_present:", audit["template_present"])
            print("- placeholder_detected:", audit["placeholder_detected"])
            print("- configuration_valid:", audit["configuration_valid"])
            print("- adapter:", audit["adapter"])
            print("- manager_status:", audit["manager_status"])
        if row["missing"]:
            print(f"- faltando: {', '.join(row['missing'])}")
        if row["masked_values"]:
            print("- valores presentes:", ", ".join(
                f"{key}={value}"
                for key, value in row["masked_values"].items()
            ))
    print("\nResumo")
    print("- lojas configuradas:", report["summary"]["configured"])
    print("- lojas validadas:", report["summary"]["validated"])
    print("- lojas bloqueadas:", report["summary"]["blocked"])
    print("- relatorios:", ", ".join(str(path) for path in paths))
    return report


if __name__ == "__main__":
    main()
