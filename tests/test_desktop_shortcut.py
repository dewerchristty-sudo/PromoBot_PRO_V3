import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import main
from src.core import desktop_shortcut


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ensure_desktop_shortcut.ps1"


class DesktopShortcutConfigurationTest(TestCase):

    def test_development_configuration_uses_current_python_and_main(self):
        config = desktop_shortcut.launch_configuration()
        expected_python = Path(sys.executable).resolve()
        pythonw = expected_python.with_name("pythonw.exe")
        if sys.platform == "win32" and pythonw.is_file():
            expected_python = pythonw
        self.assertEqual(config["target"], str(expected_python))
        self.assertEqual(
            config["arguments"],
            f'"{(ROOT / "main.py").resolve()}"',
        )
        self.assertEqual(config["working_directory"], str(ROOT))

    @patch("src.core.desktop_shortcut.subprocess.run")
    def test_non_blocking_failure_is_reported(self, run):
        run.side_effect = OSError("PowerShell indisponível")
        self.assertEqual(
            desktop_shortcut.ensure_desktop_shortcut(),
            "falha não bloqueante",
        )

    @patch("src.core.desktop_shortcut.subprocess.run")
    def test_valid_result_is_returned(self, run):
        run.return_value = Mock(
            returncode=0,
            stdout="atualizado\r\n",
            stderr="",
        )
        self.assertEqual(
            desktop_shortcut.ensure_desktop_shortcut(),
            "atualizado",
        )

    def test_main_checks_shortcut_before_opening_application(self):
        events = []
        fake_app = Mock()
        fake_app.run.side_effect = lambda: events.append("app")
        with (
            patch.object(
                main,
                "ensure_desktop_shortcut",
                side_effect=lambda: events.append("shortcut"),
            ),
            patch.object(main, "PromoBot", return_value=fake_app),
        ):
            main.main()
        self.assertEqual(events, ["shortcut", "app"])


class DesktopShortcutPowerShellTest(TestCase):

    def run_script(self, desktop, target, working):
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                "-TargetPath",
                str(target),
                "-Arguments",
                f'"{ROOT / "main.py"}"',
                "-WorkingDirectory",
                str(working),
                "-IconLocation",
                f"{target},0",
                "-DesktopPath",
                str(desktop),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip().splitlines()[-1]

    def shortcut_data(self, shortcut):
        command = (
            "$s=(New-Object -ComObject WScript.Shell)"
            f".CreateShortcut('{shortcut}');"
            "[pscustomobject]@{Target=$s.TargetPath;Arguments=$s.Arguments;"
            "WorkingDirectory=$s.WorkingDirectory;Icon=$s.IconLocation}"
            "|ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def test_create_idempotency_and_configuration(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            root = Path(directory)
            desktop = root / "Desktop"
            desktop.mkdir()
            target = root / "python.exe"
            target.touch()

            self.assertEqual(
                self.run_script(desktop, target, ROOT),
                "criado",
            )
            self.assertEqual(
                self.run_script(desktop, target, ROOT),
                "inalterado",
            )
            shortcut = desktop / "PromoBot_PRO_V3.lnk"
            self.assertTrue(shortcut.is_file())
            data = self.shortcut_data(shortcut)
            self.assertEqual(
                Path(data["Target"]).resolve(),
                target.resolve(),
            )
            self.assertEqual(
                Path(data["WorkingDirectory"]).resolve(),
                ROOT.resolve(),
            )
            self.assertEqual(data["Arguments"], f'"{ROOT / "main.py"}"')

    def test_migrates_owned_legacy_and_preserves_unrelated_shortcut(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            root = Path(directory)
            desktop = root / "Desktop"
            desktop.mkdir()
            target = root / "PromoBot_PRO_V3.exe"
            target.touch()
            unrelated_target = root / "outro.exe"
            unrelated_target.touch()

            self.run_script(desktop, target, root)
            official = desktop / "PromoBot_PRO_V3.lnk"
            legacy = desktop / "PromoBot PRO V3.lnk"
            official.replace(legacy)

            create_unrelated = (
                "$s=(New-Object -ComObject WScript.Shell)"
                f".CreateShortcut('{desktop / 'Meu Atalho.lnk'}');"
                f"$s.TargetPath='{unrelated_target}';"
                "$s.Description='Outro aplicativo';$s.Save()"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", create_unrelated],
                check=True,
            )

            self.assertEqual(
                self.run_script(desktop, target, root),
                "atualizado",
            )
            self.assertTrue(official.is_file())
            self.assertFalse(legacy.exists())
            self.assertTrue((desktop / "Meu Atalho.lnk").is_file())

            shutil.copyfile(official, legacy)
            self.assertEqual(
                self.run_script(desktop, target, root),
                "atualizado",
            )
            self.assertTrue(official.is_file())
            self.assertFalse(legacy.exists())
            self.assertTrue((desktop / "Meu Atalho.lnk").is_file())
