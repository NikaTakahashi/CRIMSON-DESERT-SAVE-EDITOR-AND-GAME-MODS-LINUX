# -*- mode: python ; coding: utf-8 -*-

import os
import sys

# Native modules are per-platform. Bundle the build host's binary, and only if
# the file exists, so Linux/macOS builds do not hard-fail on a Windows .pyd.
if sys.platform.startswith("win"):
    _dmm_binaries = [('dmm_parser/dmm_parser.pyd', 'dmm_parser')]
else:
    _dmm_binaries = [('dmm_parser/dmm_parser.abi3.so', 'dmm_parser')]
_dmm_binaries = [
    (src, dst) for src, dst in _dmm_binaries
    if os.path.isfile(os.path.join(SPECPATH, src))
]

_parc_name = ("parc_parser.dll" if sys.platform.startswith("win")
             else "libparc_parser.dylib" if sys.platform == "darwin"
             else "libparc_parser.so")
_parc_datas = [(name, ".") for name in (_parc_name,)
               if os.path.isfile(os.path.join(SPECPATH, name))]

a = Analysis(
    ['simple_launcher.py'],
    pathex=[],
    binaries=_dmm_binaries,
    datas=[('crimson_rs', 'crimson_rs'), ('dmm_parser', 'dmm_parser'), ('crimson_data.db.gz', '.'), *_parc_datas],
    hiddenimports=[
        'lz4', 'lz4.block',
        'dmm_parser', 'dmm_parser.dmm_parser', 'dmm_parser.enums',
        'crimson_rs', 'crimson_rs.enums', 'crimson_rs.create_pack', 'crimson_rs.pack_mod',
        'crimson_rs.validate_game_dir',
        'paz_patcher', 'paz_parse', 'pabgb_field_parsers', 'data_db',
        'item_creator', 'iteminfo_parser', 'iteminfo_reader',
        'equipslotinfo_parser', 'shared_state', 'overlay_coordinator',
        'models',
        'inventory_parser_108', 'characterinfo_full_parser',
        'platform_paths',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5'],
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
    name='CrimsonGameModsSimple',
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
    icon='app_icon.ico',
    codesign_identity=None,
    entitlements_file=None,
)
