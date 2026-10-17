# -*- mode: python ; coding: utf-8 -*-
# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
"""PyInstaller-спек: один самодостаточный ForestProxyUpdater.exe.

onefile (библиотеки/данные кладутся прямо в EXE, без COLLECT), БЕЗ консольного
окна (``console=False``), с иконкой и ресурсом версии.

Внутрь пакета попадает:
  * весь код из репозиторного ``src/`` (компилируется в PYZ; ``src`` добавлен в
    ``pathex``, потому что модули импортируются по «плоским» именам:
    ``import config``, ``import clientwrite``, …);
  * ядро и гео-базы как ``bin/xray/{xray.exe,geoip.dat,geosite.dat,LICENSE}``.
    Ядро запускается НЕ отсюда: при первом запуске оно (вместе с обеими
    гео-базами) копируется в постоянный каталог данных
    (``config.ensure_core_installed`` -> ``%LOCALAPPDATA%\\ForestProxyUpdater\\
    bin\\xray``), и только оттуда — иначе живое ядро держало бы файл в
    распакованном каталоге _MEIxxxx, уборщик PyInstaller не смог бы его снести
    и показал бы модальное окно «Failed to remove temporary directory»;
  * ``config.example.json`` в корень пакета, чтобы первый запуск без конфига
    и проверка ``example_config_path()`` работали из одного .exe.

Запуск — только через build.ps1/build.bat (они гарантируют, что ядро и иконка
на месте и что PyInstaller установлен).
"""
import os

# SPECPATH задаёт сам PyInstaller при выполнении спеки.
try:
    _HERE = os.path.abspath(SPECPATH)                       # noqa: F821
except NameError:                                          # pragma: no cover
    _HERE = os.path.dirname(os.path.abspath(__file__))

_REPO = os.path.dirname(_HERE)
_SRC = os.path.join(_REPO, "src")
_VENDOR = os.path.join(_HERE, "vendor", "bin", "xray")
_ICON = os.path.join(_HERE, "app.ico")
_VERSION = os.path.join(_HERE, "version_info.txt")
_EXAMPLE = os.path.join(_REPO, "config.example.json")

# ── обязательные входы: падаем рано и понятно, а не «странным» exe ──
_required = {
    "src/v2ray_updater.py": os.path.join(_SRC, "v2ray_updater.py"),
    "config.example.json": _EXAMPLE,
    "app.ico (python make_icon.py)": _ICON,
    "version_info.txt": _VERSION,
}
for _f in ("xray.exe", "geoip.dat", "geosite.dat", "LICENSE"):
    _required["vendor/bin/xray/" + _f + "  (python fetch_core.py)"] = \
        os.path.join(_VENDOR, _f)

_missing = [k for k, v in _required.items() if not os.path.isfile(v)]
if _missing:
    raise SystemExit("Не хватает входных файлов для сборки:\n  - "
                     + "\n  - ".join(_missing))

# «Плоские» модули src/: собираем явно, т.к. часть из них импортируется лениво
# (import watch внутри функции, import selftest, import tray, …).
HIDDEN = [
    "clientwrite", "clientwrite_posix", "clientwrite_v2rayn",
    "config", "i18n", "log", "netfilters", "parser", "selftest",
    "sources", "tray", "tray_status", "v2ray_updater", "watch", "xraytest",
]

# данные, которые должны лежать рядом с exe ВНУТРИ onefile-пакета
DATAS = [(os.path.join(_VENDOR, f), "bin/xray")
         for f in ("xray.exe", "geoip.dat", "geosite.dat", "LICENSE")]
DATAS.append((_EXAMPLE, "."))

a = Analysis(
    [os.path.join(_SRC, "v2ray_updater.py")],
    pathex=[_SRC],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PIL", "numpy", "matplotlib", "pandas", "scipy",
              "pydoc_data", "test"],
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
    name="ForestProxyUpdater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,              # без консольного окна (pythonw-семантика)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICON,
    version=_VERSION,
)
