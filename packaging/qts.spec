# PyInstaller spec for QTS Trading System Desktop — one-click Windows launch
# Build from repo root: pip install pyinstaller && pyinstaller packaging/qts.spec --clean --noconfirm
# Output: dist/QTS.exe
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
block_cipher = None
# Resolve relative to spec file location (packaging/)
try:
    ROOT = Path(__file__).parent.parent.resolve()
except NameError:
    ROOT = Path.cwd()
a = Analysis(
    [str(ROOT / 'src' / 'qts' / 'desktop' / 'launcher.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=[
        (str(ROOT / 'src' / 'qts' / 'desktop' / 'ui'), 'qts/desktop/ui'),
        (str(ROOT / 'configs'), 'configs'),
    ],
    hiddenimports=[
        'qts.api.server',
        'qts.desktop.health',
        'qts.desktop.state',
        'qts.config.settings',
        'qts.risk.demo_limits',
        'qts.lifecycle.demo_gate',
        'qts.lifecycle.live_gate',
        'qts.execution.demo_comparison',
        'qts.execution.reality',
        'qts.observability.forward_observatory',
        'qts.regime.observatory',
        'qts.data.provider',
        'qts.data.inventory',
        'qts.data.store',
        'uvicorn',
        'fastapi',
        'pydantic',
        'pandas',
        'numpy',
        'pyarrow',
        'scipy',
        'click',
        'yaml',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='QTS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=str(ROOT / 'assets' / 'qts.ico') if (ROOT / 'assets' / 'qts.ico').exists() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='QTS'
)
