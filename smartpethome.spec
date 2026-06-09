# -*- mode: python ; coding: utf-8 -*-
# SmartPetHome PyInstaller spec
# Compatible with pyinstaller==6.20.0
# Entry point: launcher.py (opens browser, starts Flask + MQTT + Telegram)

block_cipher = None

import os
_here = os.path.dirname(os.path.abspath(SPEC))

# Collect data files that must ship alongside the exe
_datas = [
    (os.path.join(_here, 'templates'),    'templates'),
    (os.path.join(_here, 'static'),       'static'),
    (os.path.join(_here, '.env.example'), '.'),
]
# Include docs/ only if it exists
_docs = os.path.join(_here, 'docs')
if os.path.isdir(_docs):
    _datas.append((_docs, 'docs'))

a = Analysis(
    [os.path.join(_here, 'launcher.py')],
    pathex=[_here],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        # Flask ecosystem
        'flask', 'jinja2', 'jinja2.ext', 'werkzeug', 'werkzeug.serving',
        'werkzeug.middleware.proxy_fix', 'click',
        # Supabase / HTTP
        'supabase', 'gotrue', 'gotrue.models', 'httpx', 'httpcore',
        'postgrest', 'postgrest.utils', 'realtime', 'storage3',
        'hpack', 'h2', 'h11',
        # env / utils
        'dotenv', 'python_dotenv',
        # MQTT
        'paho', 'paho.mqtt', 'paho.mqtt.client',
        # Requests
        'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna',
        # App modules
        'app', 'config', 'utils',
        'auth', 'dashboard', 'pets', 'devices', 'feeder',
        'alerts', 'history', 'locations', 'api',
        'telemetry', 'telegram_bot', 'telegram_utils',
        'mqtt_client', 'telemetry_handlers', 'commands',
        # profile is a reserved name — imported via importlib in app.py
        'profile',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'test'],
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
    console=True,           # keep console so users can see logs / errors
    icon=os.path.join(_here, 'smartpet-icon.ico'),
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
