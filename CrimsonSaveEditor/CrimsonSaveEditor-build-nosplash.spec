import os

_SPEC_DIR = SPECPATH

# The native parser backend ships as a platform-specific shared object; package
# whichever build exists beside the spec file.
_NATIVE_BACKENDS = [
    name for name in ('parc_parser.dll', 'libparc_parser.so', 'parc_parser.dylib')
    if os.path.isfile(os.path.join(_SPEC_DIR, name))
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        *((name, '.') for name in _NATIVE_BACKENDS),
        ('item_names.json', '.'),
        ('store_names.json', '.'),
        ('item_templates.json', '.'),
        ('master_templates.json', '.'),
        ('item_limits.json', '.'),
        ('item_category_map.json', '.'),
        ('max_enchant_map.json', '.'),
        ('waypoint_templates_community.json', '.'),
        ('abyss_gimmick_templates.json', '.'),
        ('knowledge_keys_all.json', '.'),
        ('community_knowledge_keys.json', '.'),
        ('quest_names.json', '.'),
        ('quest_database.json', '.'),
        ('mission_names.json', '.'),
        ('quest_stage_map.json', '.'),
        ('stage_names.json', '.'),
        ('gimmick_respawn_timers.json', '.'),
        ('quest_chains.json', '.'),
        ('dye_slot_counts.json', '.'),
        ('buff_skill_descriptions.json', '.'),
        ('game_map.json', '.'),
        ('localizationstring_eng_items.tsv', '.'),
        ('locale', 'locale'),
        ('knowledge_packs', 'knowledge_packs'),
    ],
    hiddenimports=[
        'lz4',
        'lz4.block',
        'cryptography',
        'cryptography.hazmat.primitives.ciphers',
        'cryptography.hazmat.primitives.ciphers.algorithms',
        'iteminfo_parser',
        'parc_inserter3',
        'parc_inserter2',
        'parc_serializer',
        'save_parser',
        'save_pet_rename',
        'quest_deep_parser',
        'questinfo_parser',
        'item_template_db',
        'native_backend',
        'platform_paths',
        'app_version',
        'startup_splash',
        'theme_support',
        'ben_save_decrypt',
        'crimson_rs',
        'crimson_rs.enums',
        'crimson_rs.create_pack',
        'crimson_rs.pack_mod',
        'crimson_rs.validate_game_dir',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # This edition is intentionally unable to make network connections.  Keep
    # network-capable Qt and Python modules out of the packaged executable, not
    # merely unused or hidden behind disabled controls.
    excludes=[
        'PyQt5',
        'PySide6.QtNetwork',
        'PySide6.QtNetworkAuth',
        'PySide6.QtWebChannel',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtWebSockets',
        'PySide6.QtHttpServer',
        'urllib.request',
        'urllib.response',
        'http.client',
        'http.server',
        'ftplib',
        'ssl',
        '_ssl',
        'socket',
        '_socket',
    ],
    noarchive=False,
    optimize=0,
)

# Qt's GUI hook discovers optional PDF and virtual-keyboard plugins.  Those
# plugins pull QtNetwork back in as a native library even when QtNetwork's
# Python module is excluded.  The editor uses none of them, so strip that whole
# dependency chain from the package; the shared objects are .dll on Windows,
# .so on Linux and .dylib on macOS.
_blocked_qt_binaries = {
    'qpdf',
    'qtvirtualkeyboardplugin',
    'qtuiotouchplugin',
    'qt6pdf',
    'qt6virtualkeyboard',
    'qt6network',
    'qt6quick',
    'qt6qml',
    'qt6qmlmeta',
    'qt6qmlmodels',
    'qt6qmlworkerscript',
}


def _is_blocked_binary(name: str) -> bool:
    stem = str(name).replace('\\', '/').rsplit('/', 1)[-1].lower()
    for suffix in ('.dll', '.so', '.dylib'):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    if stem.startswith('lib'):
        stem = stem[3:]
    return stem in _blocked_qt_binaries


a.binaries = [entry for entry in a.binaries if not _is_blocked_binary(entry[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CrimsonSaveEditorStandalone-Offline-2_01',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # Avoid executable packing, which frequently causes false-positive AV alerts.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon='app_icon.ico',
    codesign_identity=None,
    entitlements_file=None,
)
