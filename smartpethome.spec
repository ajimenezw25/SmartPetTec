# -*- mode: python ; coding: utf-8 -*-
# ============================================================
#  SmartPetHome — PyInstaller spec file
#
#  HOW FLASK RUNS INSIDE THE .EXE:
#  PyInstaller bundles Python, Flask, and all dependencies into
#  a single folder (dist/SmartPetHome/). The .exe unpacks them
#  into a temp directory at runtime and executes app.py.
#
#  IMPORTANT: Templates and static files are NOT Python modules,
#  so PyInstaller won't find them automatically. We add them
#  explicitly via the 'datas' list below.
#
#  LIMITATIONS:
#  - The app still runs as a local web server (localhost:5000).
#    The .exe is NOT a standalone desktop GUI; it opens a browser.
#  - The .env file must sit NEXT TO the .exe in the dist folder.
#  - Supabase still requires an internet connection.
#  - Debug mode is disabled in the packaged build.
# ============================================================

import os

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Include all HTML templates
        ('templates', 'templates'),
        # Include all static files (CSS, images, etc.)
        ('static', 'static'),
        # Include the .env.example so users know what's needed
        ('.env.example', '.'),
    ],
    hiddenimports=[
        # Supabase and its deps sometimes need explicit hints
        'supabase',
        'gotrue',
        'httpx',
        'postgrest',
        'realtime',
        'storage3',
        'dotenv',
        'flask',
        'jinja2',
        'werkzeug',
        # Blueprint modules
        'auth',
        'dashboard',
        'pets',
        'devices',
        'feeder',
        'alerts',
        'history',
        'profile',
        'locations',
        'config',
        'utils',
    ],
    hookspath=[],
    hooksconfig={},
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
    [],
    exclude_binaries=True,
    name='SmartPetHome',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,           # Keep console visible so users can see errors
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
    name='SmartPetHome',
)
