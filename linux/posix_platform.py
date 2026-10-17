# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""posix_platform.py — всё, что на Windows делает WinAPI, а на Linux — XDG.

FOREST's Proxy Auto-updater (GPL-3.0).

Что здесь живёт (полный Linux-эквивалент Windows-специфичных участков
``v2ray_updater.py``):

  установка    --install  -> раскладка в ~/.local/share/forest-proxy-updater
                             (бинарь + bin/xray/{xray,geoip.dat,geosite.dat}),
                             конфиг в ~/.config/forest-proxy-updater/config.json,
                             состояние/логи в ~/.local/state/forest-proxy-updater,
                             юниты systemd --user (+enable-linger) и первый цикл;
  удаление     --uninstall -> снять юниты, ядро, вернуть системный прокси,
                             удалить данные/состояние/конфиг;
  индикация    вместо WinAPI-трея — файл состояния state/tray_status.json
                             (его же читает ``--status``) плюс notify-send,
                             если он есть в PATH. Без notify-send программа
                             работает как обычно (мягкая деградация): события
                             остаются в логе;
  статус       --status   -> состояние юнита systemd --user.

Windows не затрагивается: модуль импортируется только при ``os.name != "nt"``
(см. ``v2ray_updater.posix_platform()``).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import log

APP = "forest-proxy-updater"
UNIT_SERVICE = APP + ".service"
UNIT_REFRESH = APP + "-refresh.service"
UNIT_TIMER = APP + ".timer"
UNITS = (UNIT_SERVICE, UNIT_REFRESH, UNIT_TIMER)

SERVICE_NAME = APP            # для systemctl is-active
CORE_SUBDIR = os.path.join("bin", "xray")


# ══════════════════════════════════════════ каталоги (XDG) ═══
def _xdg(env: str, default_rel: str) -> str:
    v = os.environ.get(env)
    if v and os.path.isabs(v):
        return v
    return os.path.join(os.path.expanduser("~"), *default_rel.split("/"))


def data_dir() -> str:
    """~/.local/share/forest-proxy-updater — бинарь, ядро, гео-базы."""
    return os.path.join(_xdg("XDG_DATA_HOME", ".local/share"), APP)


def config_dir() -> str:
    return os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), APP)


def config_file() -> str:
    return os.path.join(config_dir(), "config.json")


def state_dir() -> str:
    return os.path.join(_xdg("XDG_STATE_HOME", ".local/state"), APP)


def systemd_user_dir() -> str:
    return os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "systemd", "user")


def unit_template_dir() -> str:
    """Каталог с шаблонами юнитов: репозиторий, бандл (_MEIPASS), каталог установки."""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [
        os.path.join(here, "systemd"),
        os.path.join(data_dir(), "systemd"),
        os.path.join(getattr(sys, "_MEIPASS", "") or "", "linux", "systemd"),
    ]
    for d in cands:
        if d and os.path.isdir(d):
            return d
    return ""


# ══════════════════════════════════════════ systemd --user ═══
def systemd_available() -> bool:
    return os.path.isdir("/run/systemd/system")


def _systemctl(args: list, timeout: int = 60, check: bool = False) -> tuple:
    """``systemctl --user ...`` -> (ok, вывод)."""
    try:
        r = subprocess.run(["systemctl", "--user"] + args, capture_output=True,
                           text=True, timeout=timeout)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return (r.returncode == 0), out
    except FileNotFoundError:
        return False, "systemctl не найден"
    except Exception as e:
        return False, str(e)


def service_state() -> str:
    """Строка состояния для --status: active/inactive/failed/нет systemd."""
    if not systemd_available():
        return "systemd недоступен (нет /run/systemd/system)"
    if not user_manager_ok()[0]:
        return ("менеджер пользователя не отвечает "
                "(systemctl --user недоступен)")
    ok_a, act = _systemctl(["is-active", SERVICE_NAME], timeout=15)
    ok_e, en = _systemctl(["is-enabled", SERVICE_NAME], timeout=15)
    act = act.splitlines()[0] if act else "unknown"
    en = en.splitlines()[0] if en else "unknown"
    ok_t, tmr = _systemctl(["is-active", UNIT_TIMER], timeout=15)
    tmr = tmr.splitlines()[0] if tmr else "unknown"
    return (f"{SERVICE_NAME}: {act} / {en}; таймер {UNIT_TIMER}: {tmr}")


def user_manager_ok() -> tuple:
    """Отвечает ли менеджер пользователя (systemctl --user).

    Наличие ``/run/systemd/system`` ещё не значит, что пользовательский
    менеджер жив: в контейнерах и в WSL он регулярно не поднимается
    («Failed to connect to user scope bus»). Без него юниты включить нельзя,
    и молчать об этом нельзя — иначе установка «пройдёт», а автозапуска не
    будет.
    """
    ok, out = _systemctl(["is-system-running"], timeout=15)
    low = (out or "").lower()
    if "failed to connect" in low or "no such file or directory" in low:
        return False, out.strip()
    if "offline" in low:
        return False, "менеджер пользователя в состоянии offline"
    return True, out.strip()


def user_manager_hint() -> str:
    """Что делать, если менеджер пользователя не поднялся."""
    return ("Автозапуск не настроен: systemctl --user недоступен.\n"
            "  В WSL включите systemd в /etc/wsl.conf ([boot] systemd=true),\n"
            "  перезапустите WSL (wsl --shutdown), затем:\n"
            "    loginctl enable-linger \"$USER\"\n"
            "  Если менеджер не отвечает и дальше — в системе остались старые\n"
            "  процессы 'systemd --user'; перезапустите его (нужен root):\n"
            "    sudo systemctl restart user@$(id -u).service")


def enable_linger() -> tuple:
    """Разрешить службам пользователя работать без входа в систему."""
    try:
        r = subprocess.run(["loginctl", "enable-linger", os.environ.get("USER")
                            or os.path.expanduser("~").rsplit("/", 1)[-1]],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            return True, "enable-linger выполнен"
        return False, ((r.stderr or r.stdout or "").strip()
                       or "нужны права (sudo loginctl enable-linger $USER)")
    except Exception as e:
        return False, str(e)


# ══════════════════════════════════════════ уведомления ═══
_NOTIFY = None


def notify_available() -> bool:
    global _NOTIFY
    if _NOTIFY is None:
        _NOTIFY = bool(shutil.which("notify-send"))
    return bool(_NOTIFY)


def notify(title: str, body: str, urgency: str = "normal") -> bool:
    """Уведомление рабочего стола через notify-send (нет утилиты — тихо мимо)."""
    if not notify_available():
        return False
    try:
        subprocess.Popen(["notify-send", "-a", "FOREST Proxy", "-u", urgency,
                          title, body], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


# ══════════════════════════════════════════ индикация (замена трея) ═══
def indicator_path(cfg: dict) -> str:
    """Файл индикации состояния (тот же формат, что писал трей на Windows)."""
    return os.path.join(cfg["paths"]["state_dir"], "tray_status.json")


def read_indicator(cfg: dict) -> dict:
    try:
        with open(indicator_path(cfg), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def indicators_loop(cfg: dict, stop_event, poll_s: float = 3.0) -> None:
    """Поток индикации вместо WinAPI-трея (без окон, только файл + notify-send).

    Задача потока: держать ``state/tray_status.json`` свежим даже когда сторож
    молчит (тогда видно, что процесс жив), и отправлять уведомление о СМЕНЕ
    состояния связи. Правду о состоянии по-прежнему знает сторож (tray_status
    пишет он) — здесь только «пульс» и переходы.
    """
    lg = log.get_logger()
    import clientwrite_posix as CW
    port = 0
    prev = None
    lg.info("Индикация: файл состояния %s%s" % (
        indicator_path(cfg),
        "" if notify_available() else " (notify-send не найден — только лог)"))
    while not stop_event.is_set():
        try:
            port = int(cfg.get("client", {}).get("socks_port") or 0)
            alive = CW.tcp_open("127.0.0.1", port) if port else False
            cur = "ok" if alive else "down"
            if prev is not None and cur != prev:
                if cur == "down":
                    lg.warn("Индикация: связь через прокси пропала")
                    notify("FOREST Proxy: связи нет",
                           f"Порт {port} не отвечает — идёт восстановление", "critical")
                else:
                    lg.info("Индикация: связь через прокси восстановлена")
                    notify("FOREST Proxy: связь восстановлена",
                           f"Прокси снова отвечает на 127.0.0.1:{port}")
            prev = cur
            # пульс: если сторож давно не писал, отмечаем это сами
            st = read_indicator(cfg)
            fresh = time.time() - float(st.get("ts", 0) or 0) < 60
            if not fresh:
                _write_pulse(cfg, port, alive)
        except Exception as e:
            lg.warn(f"индикация: {e}")
        stop_event.wait(poll_s)


def _write_pulse(cfg: dict, port: int, alive: bool) -> None:
    """Записать состояние, когда сторож молчит (процесс жив, но цикла не было)."""
    p = indicator_path(cfg)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "state": "ok" if alive else "down",
                       "tip": f"FOREST Proxy: {'работает' if alive else 'нет связи'} "
                              f"(127.0.0.1:{port})",
                       "source": "indicators_loop"}, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        pass


# ══════════════════════════════════════════ раскладка файлов ═══
def _installed_binary(cfg: dict) -> str:
    return os.path.join(cfg["paths"]["root"], APP)


def installed_entry() -> str:
    """Команда запуска установленной программы (frozen -> ELF, иначе python + .py)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(os.path.dirname(here), "src", "v2ray_updater.py")
    return f"{sys.executable} {src}"


def _copy_sources(dst_src: str) -> int:
    """Копирует .py программы в каталог установки (режим разработки)."""
    if getattr(sys, "frozen", False):
        return 0
    here = os.path.dirname(os.path.abspath(__file__))
    code_dir = os.path.join(os.path.dirname(here), "src")
    os.makedirs(dst_src, exist_ok=True)
    n = 0
    for fn in sorted(os.listdir(code_dir)):
        if fn.endswith(".py"):
            try:
                shutil.copy2(os.path.join(code_dir, fn), os.path.join(dst_src, fn))
                n += 1
            except Exception:
                pass
    return n


def _copy_core(cfg: dict, root: str) -> str:
    """Кладёт ядро и гео-базы в <root>/bin/xray (если нашлись поблизости)."""
    lg = log.get_logger()
    dst_dir = os.path.join(root, CORE_SUBDIR)
    os.makedirs(dst_dir, exist_ok=True)
    core = cfg.get("_core_src") or _find_core(cfg)
    copied = []
    if core and os.path.isfile(core):
        for name in ("xray", "geoip.dat", "geosite.dat", "LICENSE"):
            src = os.path.join(os.path.dirname(core), name)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(dst_dir, name)
            try:
                if os.path.abspath(src) == os.path.abspath(dst):
                    continue
                shutil.copy2(src, dst)
                copied.append(name)
            except Exception as e:
                lg.warn(f"  ядро: {name} не скопирован: {e}")
        # бит исполняемости обязателен: без него ядро не запустится
        try:
            os.chmod(os.path.join(dst_dir, "xray"), 0o755)
        except Exception:
            pass
    if copied:
        lg.info(f"  ядро и гео-базы в {dst_dir}: {', '.join(copied)}")
    elif not core:
        lg.warn("  ядро xray не найдено рядом с программой — установите его в "
                "/usr/bin/xray либо положите bin/xray/xray и повторите --install")
    return dst_dir


def _find_core(cfg: dict) -> str:
    try:
        import config as CFG
        return CFG.find_core(cfg)
    except Exception:
        return ""


# ══════════════════════════════════════════ юниты ═══
def render_units(exec_cmd: str, root: str, config_path: str) -> dict:
    """Подставляет пути в шаблоны юнитов -> {имя файла: содержимое}."""
    tdir = unit_template_dir()
    out = {}
    xdg_state = os.path.dirname(state_dir())
    for name in UNITS:
        src = os.path.join(tdir, name) if tdir else ""
        try:
            with open(src, encoding="utf-8") as f:
                text = f.read()
        except Exception:
            text = None
        if text is None:
            raise FileNotFoundError(f"шаблон юнита не найден: {src}")
        text = (text.replace("@EXEC@", exec_cmd)
                    .replace("@ROOT@", root)
                    .replace("@CONFIG@", config_path)
                    .replace("@XDG_STATE@", xdg_state))
        out[name] = text
    return out


def write_units(cfg: dict, exec_cmd: str) -> str:
    """Пишет юниты в ~/.config/systemd/user и делает daemon-reload."""
    lg = log.get_logger()
    d = systemd_user_dir()
    os.makedirs(d, exist_ok=True)
    conf = cfg.get("_config_path") or config_file()
    units = render_units(exec_cmd, cfg["paths"]["root"], conf)
    for name, text in units.items():
        p = os.path.join(d, name)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, p)
        lg.info(f"  юнит записан: {p}")
    ok, out = _systemctl(["daemon-reload"])
    lg.info(f"  systemctl --user daemon-reload: {'OK' if ok else 'ОШИБКА ' + out}")
    return d


# ══════════════════════════════════════════ установка / удаление ═══
def install(cfg: dict) -> int:
    """Linux-установка: файлы, конфиг, юниты systemd --user, первый цикл."""
    lg = log.get_logger()
    root = cfg["paths"]["root"]
    lg.info(f"Установка (Linux, systemd --user) в {root}")
    os.makedirs(root, exist_ok=True)

    # 1. сама программа
    entry = installed_entry()
    if getattr(sys, "frozen", False):
        dst = _installed_binary(cfg)
        try:
            if os.path.abspath(sys.executable) != os.path.abspath(dst):
                shutil.copy2(sys.executable, dst)
            os.chmod(dst, 0o755)
            lg.info(f"  бинарь установлен: {dst} ({os.path.getsize(dst)} байт)")
        except Exception as e:
            lg.error(f"  копирование бинаря не удалось: {e}")
            return 2
        exec_cmd = dst
    else:
        n = _copy_sources(os.path.join(root, "src"))
        lg.info(f"  режим разработки: исходников скопировано {n} -> {root}/src")
        exec_cmd = installed_entry()

    # 2. ядро и гео-базы
    _copy_core(cfg, root)

    # 3. конфиг (первый запуск). Ставим юниты на ТОТ конфиг, который реально
    #    используется сейчас (учитывает FOREST_CONFIG/--config), а не на
    #    «теоретический» XDG-путь.
    conf = cfg.get("_config_path") or config_file()
    if not os.path.isfile(conf):
        os.makedirs(os.path.dirname(conf) or ".", exist_ok=True)
        ex = ""
        try:
            import config as CFG
            ex = CFG.example_config_path() or ""
        except Exception:
            pass
        if ex and os.path.isfile(ex):
            try:
                shutil.copy2(ex, conf)
                lg.info(f"  конфиг создан: {conf}")
            except Exception as e:
                lg.warn(f"  конфиг не создан: {e}")
        else:
            lg.warn("  config.example.json не найден — конфиг будет создан при "
                    "первом запуске")
    else:
        lg.info(f"  конфиг уже есть: {conf}")

    # 4. юниты systemd --user
    if not systemd_available():
        lg.error("  systemd недоступен (/run/systemd/system отсутствует) — "
                 "автозапуск не будет настроен. В WSL включите его в /etc/wsl.conf "
                 "([boot] systemd=true) и перезапустите WSL.")
        return 3
    um_ok, um_msg = user_manager_ok()
    if not um_ok:
        lg.error(f"  менеджер пользователя не отвечает ({um_msg}) — "
                 "автозапуск настроить нельзя")
        for line in user_manager_hint().splitlines():
            lg.error("  " + line.strip())
        return 3
    try:
        write_units(cfg, exec_cmd)
    except Exception as e:
        lg.error(f"  юниты не записаны: {e}")
        return 4
    ok_e, out_e = _systemctl(["enable", "--now", UNIT_SERVICE, UNIT_TIMER])
    lg.info(f"  systemctl --user enable --now {UNIT_SERVICE} {UNIT_TIMER}: "
            f"{'OK' if ok_e else 'ОШИБКА ' + out_e}")
    ok_l, msg_l = enable_linger()
    lg.info(f"  автозапуск без входа в систему (linger): "
            f"{'включён' if ok_l else 'НЕ включён — ' + msg_l}")

    # 5. первый цикл (системный прокси на этом шаге НЕ трогается)
    if not os.environ.get("FOREST_SKIP_FIRST_CYCLE"):
        lg.info("  первый цикл (системный прокси не изменяется)...")
        try:
            import v2ray_updater as VU
            rc = VU.run_cycle(cfg, dry=False)
            if rc != 0:
                lg.warn(f"  первый цикл не дал связи (код {rc}): рабочих серверов "
                        "сейчас нет. Сторожевая петля повторит подбор автоматически.")
        except Exception as e:
            lg.warn(f"  первый цикл: {e}")

    print("Установка завершена (Linux).")
    print(f"  программа:  {exec_cmd}")
    print(f"  конфиг:     {conf}")
    print(f"  состояние:  {cfg['paths']['state_dir']}")
    print(f"  служба:     systemctl --user status {SERVICE_NAME}")
    print("  удаление:   forest-proxy-updater --uninstall")
    return 0


def uninstall(cfg: dict) -> int:
    """Linux-удаление: юниты, ядро, системный прокси, файлы и каталоги."""
    lg = log.get_logger()
    root = cfg["paths"]["root"]
    lg.info(f"Удаление (Linux) из {root}")

    # 1. снять юниты (сначала — иначе systemd перезапустит ядро)
    for unit in (UNIT_SERVICE, UNIT_TIMER, UNIT_REFRESH):
        ok_d, out_d = _systemctl(["disable", "--now", unit])
        lg.info(f"  systemctl --user disable --now {unit}: {'OK' if ok_d else '—'}")

    # 2. остановить наше ядро (только наше)
    try:
        import clientwrite_posix as CW
        CW.stop_core(cfg, why="uninstall")
    except Exception as e:
        lg.warn(f"  остановка ядра: {e}")

    # 3. вернуть системный прокси в исходное состояние
    try:
        import clientwrite_posix as CW
        CW.restore_system_proxy(cfg)
    except Exception as e:
        lg.warn(f"  восстановление прокси: {e}")

    # 4. удалить файлы юнитов
    for unit in UNITS:
        p = os.path.join(systemd_user_dir(), unit)
        try:
            if os.path.isfile(p):
                os.unlink(p)
                lg.info(f"  юнит удалён: {p}")
        except Exception as e:
            lg.warn(f"  юнит {p}: {e}")
    _systemctl(["daemon-reload"])

    # 5. снять флаг ручного отключения и удалить каталоги данных/состояния
    try:
        import clientwrite_posix as CW
        p = CW.proxy_off_path(cfg)
        if os.path.isfile(p):
            os.unlink(p)
    except Exception:
        pass
    try:
        log.get_logger().close()
    except Exception:
        pass
    # 6. убрать сам конфиг, с которым работали (может лежать вне XDG при
    #    FOREST_CONFIG/--config), затем стандартные каталоги
    try:
        cpath = cfg.get("_config_path") or ""
        if cpath and os.path.isfile(cpath):
            os.unlink(cpath)
            lg.info(f"  конфиг удалён: {cpath}")
            cdir = os.path.dirname(cpath)
            if os.path.isdir(cdir) and not os.listdir(cdir):
                os.rmdir(cdir)
                lg.info(f"  каталог конфига удалён: {cdir}")
    except Exception as e:
        lg.warn(f"  конфиг: {e}")
    for d, what in ((root, "данные программы"),
                    (data_dir(), "каталог данных XDG"),
                    (state_dir(), "состояние/логи"),
                    (config_dir(), "конфиг (XDG)")):
        try:
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                lg.info(f"  {what} удалён: {d}"
                        if not os.path.isdir(d) else
                        f"  {what} частично остался: {d}")
        except Exception as e:
            lg.warn(f"  {what} ({d}): {e}")
    print("Удаление завершено: юниты сняты, ядро остановлено, файлы удалены.")
    return 0
