# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/stamps', 'assets/stamps')],
    hiddenimports=['core', 'core.patterns', 'core.replacements', 'core.surnames', 'core.docx_cleaner', 'core.pdf_cleaner', 'core.ocr_utils', 'core.utils', 'core.auto_detect', 'core.cities_db', 'core.whitelist', 'core.xlsx_cleaner', 'core.english_pseudonyms', 'core.deanonymizer', 'core.database', 'pytesseract', 'customtkinter', 'darkdetect'],
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
    name='TitanCleaner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
