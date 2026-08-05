from pathlib import Path


def installer_script():
    return Path("installer/PromoBot_PRO_V3.iss").read_text(encoding="utf-8")


def test_installer_uses_only_official_dist():
    active = "\n".join(
        line for line in installer_script().splitlines()
        if not line.lstrip().startswith(";")
    )
    assert "dist_veloz" not in active
    assert '..\\dist\\PromoBot_PRO_V3\\PromoBot_PRO_V3.exe' in active
    assert '..\\dist\\PromoBot_PRO_V3\\_internal\\*' in active


def test_installer_version_and_isolated_output_are_current():
    text = installer_script()
    assert '#define AppVersion "3.1.0"' in text
    assert "OutputDir=..\\installer_output\\v3.1.0-ui-fix" in text
    assert "OutputBaseFilename=Instalar_PromoBot_PRO_V3_3.1.0_ui_fix" in text
