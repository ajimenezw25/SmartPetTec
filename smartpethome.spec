# -*- mode: python ; coding: utf-8 -*-
# SmartPetHome PyInstaller spec — updated for Sprint 2

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates',       'templates'),
        ('static',          'static'),
        ('docs',            'docs'),
        ('.env.example',    '.'),
    ],
    hiddenimports=[
        'supabase', 'gotrue', 'httpx', 'postgrest', 'realtime', 'storage3',
        'dotenv', 'flask', 'jinja2', 'werkzeug',
        'paho', 'paho.mqtt', 'paho.mqtt.client',
        'requests',
        'auth', 'dashboard', 'pets', 'devices', 'feeder',
        'alerts', 'history', 'profile', 'locations',
        'api', 'config', 'utils',
        'mqtt_client', 'telemetry_handlers', 'commands', 'telegram_utils',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='SmartPetHome',
    debug=False,
    console=True,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name='SmartPetHome',
)
