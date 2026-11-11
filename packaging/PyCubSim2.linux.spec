# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(SPECPATH).parent
DATA_FILES = [
    (str(PROJECT_ROOT / "assets"), "assets"),
    (str(PROJECT_ROOT / "actions"), "actions"),
    (
        str(PROJECT_ROOT / "layouts" / "default_scene.json"),
        "layouts",
    ),
    (str(PROJECT_ROOT / "examples" / "agents"), "examples/agents"),
    (str(PROJECT_ROOT / "LICENSE"), "."),
    (str(PROJECT_ROOT / "README.md"), "."),
    (str(PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]

a = Analysis(
    [str(PROJECT_ROOT / "run_sim.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=DATA_FILES,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pybullet_data"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

gui_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PyCubSim2",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
cli_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PyCubSim2-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    gui_exe,
    cli_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PyCubSim2",
)
