# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

playwright_root = Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"
browser_data = []
for pattern in ("chromium_headless_shell-*", "ffmpeg-*"):
    matches = sorted(playwright_root.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"Componente Playwright ausente: {pattern}. Execute playwright install chromium."
        )
    source = matches[-1]
    browser_data.append((str(source), f"ms-playwright/{source.name}"))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # CustomTkinter carrega temas, fontes e icones em tempo de execucao.
    # Esses arquivos nao entram apenas com hiddenimports.
    datas=browser_data + collect_data_files("customtkinter"),
    hiddenimports=[
        'customtkinter',
        'PIL',
        'playwright',
        'bs4',
        'lxml',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['src/runtime_playwright.py'],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# O hook oficial do Playwright coleta tambem .local-browsers. O PromoBot usa
# exclusivamente o Chromium portatil em _internal/ms-playwright, configurado
# por src/runtime_playwright.py; manter os dois adicionava cerca de 688 MB.
a.datas = [
    item for item in a.datas
    if ".local-browsers" not in str(item[0]).replace("\\", "/")
]
a.binaries = [
    item for item in a.binaries
    if ".local-browsers" not in str(item[0]).replace("\\", "/")
]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PromoBot_PRO_V3',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PromoBot_PRO_V3',
)
