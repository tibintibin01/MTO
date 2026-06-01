# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['clients\\desktop\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('locales', 'locales'), ('clients/desktop/theme_manager.py', '.'), ('api_clients', 'api_clients'), ('ui', 'ui')],
    hiddenimports=['requests', 'customtkinter', 'PIL', 'pandas', 'openpyxl'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MTO Treasury Debug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\official\\app_icon.ico'],
)
