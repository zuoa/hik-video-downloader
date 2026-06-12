# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

hidden_imports = [
    "hik_video_download",
    "hik_video_download.app",
    "hik_video_download.isapi",
    "hik_video_download.models",
    "hik_video_download.workers",
    "hik_video_download.ui_compat",
    "PySide6.QtWidgets",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtNetwork",
    "PySide6.QtXml",
]

# PySide6-Fluent-Widgets is optional
try:
    hidden_imports += collect_submodules("qfluentwidgets")
    datas = collect_data_files("qfluentwidgets")
except ImportError:
    datas = []

a = Analysis(
    ["src/hik_video_download/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
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
    name="hik-video-download",
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
    name="hik-video-download",
)

# macOS .app bundle
app = BUNDLE(
    coll,
    name="hik-video-download.app",
    icon=None,
    bundle_identifier="com.hik-video-download.app",
    version="0.1.0",
    info_plist={
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
    },
)
