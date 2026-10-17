# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""posix_selftest.py — автотесты Linux-специфичной части (GPL-3.0).

Запуск:  python3 src/v2ray_updater.py --selftest
(сначала идут общие тесты src/selftest.py, затем эти).

Проверяется то, чего нет на Windows и что нельзя проверить общими тестами:
выбор POSIX-бэкенда и подмена примитивов, XDG-пути, работа с процессами через
/proc и os.kill, поиск гео-баз, рендер юнитов systemd, мягкая деградация
notify-send. Сеть и боевой порт НЕ занимаются: всё в отдельном временном корне.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time

_TMP = tempfile.mkdtemp(prefix="forest_posix_selftest_")
os.environ["FOREST_ROOT"] = _TMP
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
sys.path.insert(0, _HERE)

import clientwrite_posix as CW     # noqa: E402
import config as CFG               # noqa: E402
import log                         # noqa: E402
import posix_platform as PP        # noqa: E402

FAILED: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def main() -> int:
    log.reset_logger(os.path.join(_TMP, "logs"))
    print("=" * 64)
    print("P1. POSIX-бэкенд: подмена примитивов в общей сердцевине")
    print("=" * 64)
    import clientwrite as core
    check("clientwrite_posix импортируется на Linux", CW.IS_LINUX is True)
    check("_kill_pid подменён на POSIX", core._kill_pid is CW._posix_kill_pid)
    check("_pid_alive подменён на POSIX", core._pid_alive is CW._posix_pid_alive)
    check("_port_pid подменён на POSIX", core._port_pid is CW._posix_port_pid)
    check("_our_core_pids подменён на POSIX", core._our_core_pids is CW._posix_our_core_pids)
    check("geo_asset_dir подменён на POSIX", core.geo_asset_dir is CW._posix_geo_asset_dir)
    check("_sys_proxy_state подменён на POSIX",
          core._sys_proxy_state is CW._posix_sys_proxy_state)
    check("_mode_of подменён на POSIX (только standalone)",
          core._mode_of is CW._posix_mode_of and CW._mode_of({"mode": "v2rayn"}) == "standalone")
    check("имена с подчёркиванием доступны наружу (mirror)",
          hasattr(CW, "_sa_read_active_id") and hasattr(CW, "_is_v2rayn_path")
          and hasattr(CW, "_cfg_sha"))

    print()
    print("=" * 64)
    print("P2. XDG-пути (данные / конфиг / состояние)")
    print("=" * 64)
    os.environ.pop("FOREST_ROOT", None)
    check("данные: ~/.local/share/forest-proxy-updater",
          CFG.data_root().endswith(".local/share/forest-proxy-updater"), CFG.data_root())
    check("конфиг: ~/.config/forest-proxy-updater/config.json",
          CFG.default_config_path().endswith(".config/forest-proxy-updater/config.json"),
          CFG.default_config_path())
    check("состояние: ~/.local/state/forest-proxy-updater",
          CFG.default_state_dir().endswith(".local/state/forest-proxy-updater"),
          CFG.default_state_dir())
    check("постоянный каталог ядра: ~/.local/share/forest-proxy-updater/bin/xray",
          os.path.normcase(CFG.core_dir()) == os.path.normcase(
              os.path.join(CFG.data_root(), "bin", "xray")), CFG.core_dir())
    check("логи: <состояние>/logs", CFG.default_log_dir().endswith("logs"))
    os.environ["FOREST_ROOT"] = _TMP
    check("FOREST_ROOT перекрывает пути (песочница)",
          CFG.app_root() == os.path.abspath(_TMP))
    cfg = CFG.load_config(os.path.join(_TMP, "config.json"))
    check("load_config: root из FOREST_ROOT", cfg["paths"]["root"] == os.path.abspath(_TMP))
    check("load_config: ядро ищется как 'xray'",
          "xray" in CFG.core_binary_names() and "xray.exe" not in CFG.core_binary_names())

    print()
    print("=" * 64)
    print("P3. Процессы: /proc, os.kill, замер реального завершения")
    print("=" * 64)
    p = subprocess.Popen(["sleep", "120"])
    time.sleep(0.2)
    check("_pid_alive: живой процесс -> True", CW._pid_alive(p.pid) is True)
    t0 = time.time()
    ok_kill = CW._kill_pid(p.pid)
    dt = (time.time() - t0) * 1000.0
    check("_kill_pid: снял процесс по SIGTERM", ok_kill is True)
    check("_kill_pid: завершение быстрое (<1.5 с)", dt < 1500, f"{dt:.0f} мс")
    time.sleep(0.1)
    check("_pid_alive: мёртвый процесс -> False", CW._pid_alive(p.pid) is False)
    check("_pid_alive: чужой pid маловероятен -> False", CW._pid_alive(999999) is False)

    # порт занят реальным процессом — ищем его pid через /proc
    import socket
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    time.sleep(0.1)
    check("port_listening: порт сервера виден", CW.port_listening(port, timeout=1.0) is True)
    pid_found = CW._posix_port_pid(port)
    check("_port_pid: нашёл PID слушателя через /proc/ss",
          str(pid_found) == str(os.getpid()), f"найден {pid_found}, ожидался {os.getpid()}")
    srv.close()
    time.sleep(0.2)
    check("port_listening: закрытый порт -> False", CW.port_listening(port, timeout=0.3) is False)

    print()
    print("=" * 64)
    print("P4. Поиск гео-баз и ядра")
    print("=" * 64)
    check("geo_asset_dir вызывается без исключения",
          isinstance(CW.geo_asset_dir(None, cfg), str))
    core_p = CFG.find_core(cfg)
    check("find_core не падает (может вернуть None)", core_p is None or os.path.isfile(core_p),
          str(core_p))
    if core_p:
        adir = CW.geo_asset_dir(core_p, cfg)
        check("geo_asset_dir нашёл каталог рядом с ядром или системный",
              bool(adir), adir)
        print(f"       ядро: {core_p}")
        print(f"       гео:  {adir!r}")
    else:
        print("       ядро не найдено в PATH — проверка гео-баз пропущена")

    print()
    print("=" * 64)
    print("P5. Юниты systemd: рендер шаблонов без незаполненных подстановок")
    print("=" * 64)
    tdir = PP.unit_template_dir()
    check("каталог шаблонов найден", bool(tdir), tdir)
    rendered = PP.render_units("/usr/local/bin/forest-proxy-updater", "/root/dir",
                               "/home/u/.config/forest-proxy-updater/config.json")
    check("отрендерены все юниты", set(rendered) == set(PP.UNITS), str(list(rendered)))
    for name, text in rendered.items():
        check(f"{name}: нет незаполненных @…@", "@" not in text.replace("@ROOT@", ""),
              [ln for ln in text.splitlines() if "@" in ln][:2])
    check("служба: ExecStart с --run", "--run" in rendered[PP.UNIT_SERVICE])
    check("служба: Restart=always (повторные попытки)",
          "Restart=always" in rendered[PP.UNIT_SERVICE])
    check("служба: StartLimitIntervalSec=0 (без лимита перезапусков)",
          "StartLimitIntervalSec=0" in rendered[PP.UNIT_SERVICE])
    check("служба: KillMode=control-group (ядро не останется сиротой)",
          "KillMode=control-group" in rendered[PP.UNIT_SERVICE])
    check("служба: FOREST_ROOT передан явно",
          "Environment=FOREST_ROOT=" in rendered[PP.UNIT_SERVICE])
    check("таймер: указывает на refresh-службу и Persistent=true",
          "Unit=forest-proxy-updater-refresh.service" in rendered[PP.UNIT_TIMER]
          and "Persistent=true" in rendered[PP.UNIT_TIMER])
    check("refresh: oneshot + --once",
          "Type=oneshot" in rendered[PP.UNIT_REFRESH]
          and "--once" in rendered[PP.UNIT_REFRESH])

    print()
    print("=" * 64)
    print("P6. Индикация: файл состояния + мягкая деградация notify-send")
    print("=" * 64)
    check("notify_available() возвращает bool", isinstance(PP.notify_available(), bool))
    if not PP.notify_available():
        check("notify-send отсутствует -> notify() тихо возвращает False",
              PP.notify("t", "b") is False)
    else:
        check("notify-send найден -> notify_available True", True)
    ind = PP.indicator_path(cfg)
    PP._write_pulse(cfg, 11808, True)
    check("индикация: файл состояния записан", os.path.isfile(ind), ind)
    d = PP.read_indicator(cfg)
    check("индикация: state=ok и есть подсказка",
          d.get("state") == "ok" and bool(d.get("tip")), str(d))
    check("индикация: путь внутри каталога состояния",
          os.path.dirname(ind) == cfg["paths"]["state_dir"])

    print()
    print("=" * 64)
    print("P7. Проверка конфига ядром до остановки (бесшовность), POSIX")
    print("=" * 64)
    if core_p:
        # конфиг с заведомо свободным портом
        c = {"log": {"loglevel": "warning"},
             "inbounds": [{"tag": "socks-in", "port": 1, "listen": "127.0.0.1",
                           "protocol": "socks", "settings": {"udp": True, "auth": "noauth"}}],
             "outbounds": [{"tag": "direct", "protocol": "freedom"}]}
        ok_t, err_t = CW._test_config_by_core(core_p, c, cfg)
        check("_test_config_by_core принимает валидный конфиг", ok_t is True, str(err_t))
        bad = {"inbounds": [{"port": 1, "protocol": "no-such-protocol"}]}
        ok_b, err_b = CW._test_config_by_core(core_p, bad, cfg)
        check("_test_config_by_core отвергает невалидный конфиг", ok_b is False, str(err_b))
        print(f"       ошибка ядра (как её увидит лог): {err_b[:120]!r}")
    else:
        print("       ядро не найдено — проверка ядром пропущена")

    print()
    print("=" * 64)
    print("P8. Systemd: доступность и состояние службы")
    print("=" * 64)
    check("systemd_available() -> bool", isinstance(PP.systemd_available(), bool))
    st = PP.service_state()
    check("service_state() возвращает строку", isinstance(st, str) and bool(st), st)
    print(f"       состояние: {st}")

    print()
    print("=" * 64)
    if FAILED:
        print(f"POSIX-тесты НЕ пройдены: {len(FAILED)}")
        for f in FAILED:
            print(f"  - {f}")
        _cleanup()
        return 1
    print("POSIX-тесты пройдены.")
    print("=" * 64)
    _cleanup()
    return 0


def _cleanup():
    try:
        import shutil
        shutil.rmtree(_TMP, ignore_errors=True)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
