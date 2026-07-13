# -*- mode: python ; coding: utf-8 -*-

from fukua_rpa.constants import ONEFILE_BUILD_NAME
from PyInstaller.utils.hooks import collect_dynamic_libs
from scripts.runtime_pruning import (
    PYINSTALLER_EXCLUDES,
    apply_runtime_pruning,
)


uia_binaries = [
    item
    for item in collect_dynamic_libs("uiautomation")
    if item[0].endswith("UIAutomationClient_VC140_X64.dll")
]

a = Analysis(
    ["fukuaRPA.py"],
    pathex=[],
    binaries=[("fukua_rpa_core.dll", "."), *uia_binaries],
    datas=[("assets/fukuaRPA.ico", "assets"), ("LICENSE", ".")],
    hiddenimports=["fukua_rpa.native_smoke", "pyautogui"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(PYINSTALLER_EXCLUDES),
    noarchive=False,
    optimize=0,
)
apply_runtime_pruning(a)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=ONEFILE_BUILD_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/fukuaRPA.ico",
    version="assets/version_info_onefile.txt",
)
