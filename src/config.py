# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Конфигурация + автоопределение режима и ядра (GPL-3.0).

FOREST's Proxy Auto-updater. Один конфиг — два режима (переключаются в
config.json, без правки кода):

  * ``client.mode = "standalone"`` (по умолчанию) — программа НЕ требует
    v2rayN: сама хранит список серверов (свой файл состояния), сама пишет
    конфиг ядра xray, сама запускает/останавливает процесс ``xray.exe`` и
    сама ставит/снимает системный прокси.
  * ``client.mode = "v2rayn"`` — поведение как в исходном проекте: работа
    через базу и ядро установленного v2rayN.

Каталог состояния/логов по умолчанию — %LOCALAPPDATA%\\ForestProxyUpdater
(переопределяется ``paths.root`` в конфиге или переменной FOREST_ROOT).
Каталог исходников при этом НЕ засоряется: state/, logs/, config.json в
репозиторий не пишутся.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess

import log

APP_NAME = "ForestProxyUpdater"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))        # .../src
PROJECT_DIR = os.path.dirname(BASE_DIR)                      # корень репозитория

DEFAULT_SOCKS_PORT = 10808
DEFAULT_TORRENT_PORT = 10820


# ─────────────────────────────────────────────────── каталоги ───
def app_root() -> str:
    """Корневой каталог программы (состояние/логи/конфиг по умолчанию)."""
    r = os.environ.get("FOREST_ROOT")
    if r:
        return os.path.abspath(r)
    la = os.environ.get("LOCALAPPDATA")
    if not la:
        la = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(la, APP_NAME)


def example_config_path():
    for c in (os.path.join(PROJECT_DIR, "config.example.json"),
              os.path.join(BASE_DIR, "config.example.json"),
              os.path.join(app_root(), "config.example.json")):
        if os.path.isfile(c):
            return c
    return None


def config_path() -> str:
    """Путь к рабочему config.json (существующий — иначе цель для создания)."""
    p = os.environ.get("FOREST_CONFIG")
    if p:
        return os.path.abspath(p)
    installed = os.path.join(app_root(), "config.json")
    dev = os.path.join(PROJECT_DIR, "config.json")
    if os.path.isfile(installed):
        return installed
    if os.path.isfile(dev):
        return dev
    return installed


# ─────────────────────────────────────────────────── значения по умолчанию ───
# Разумные ДЕФОЛТЫ для чужого пользователя (не личные настройки автора):
# без шлюза Cloudflare, кап подсети 1, минимум скорости 1000 КБ/с,
# «РФ напрямую» ВЫКЛЮЧЕНО (чтобы не ломать чужую маршрутизацию).
DEFAULTS = {
    "ui": {"lang": ""},
    "client": {
        "mode": "standalone",
        "socks_port": DEFAULT_SOCKS_PORT,
        "torrent_port": DEFAULT_TORRENT_PORT,
        "listen": "127.0.0.1",
        "manage_system_proxy": True,
        "core": "",
        # поля режима v2rayn
        "dir": "",
        "exe": "v2rayN.exe",
        "db_rel": "guiConfigs/guiNDB.db",
        "cfg_rel": "guiConfigs/guiNConfig.json",
        "core_rel": "bin/xray/xray.exe",
    },
    "cycle": {"full_refresh_hours": 0.5},
    "test": {
        "port_start": 10810, "workers": 8, "rtt_timeout": 6, "rtt_repeats": 2,
        "speed_timeout": 15, "speed_bytes": 5242880, "min_speed_kbps": 1000,
        "max_rtt_ms": 1500, "max_jitter_ms": 800, "top_for_speed": 60,
        "max_candidates": 400, "tcp_prefilter": True, "final_verify_top": 60,
        "min_pool": 60, "reserve_min": 30, "speed_rounds": 1,
        "gate_urls": [], "reserve_verify": 20,
    },
    "limits": {"max_servers": 100},
    "activation": {"prefer_current_if_healthy": True, "max_restart_wait_s": 40},
    "watch": {
        "check_interval_s": 10, "probe_timeout_s": 4, "max_strikes": 3,
        "hotcache_n": 20, "hotcache_ttl_s": 3600, "speed_min_kbps": 1500,
        "speed_check_every_s": 300, "balancer_pool_n": 10, "pool_refresh_s": 600,
        "balancer_mode": True, "probe_retries": 2, "strict_check_every_s": 300,
        "ru_direct": False, "pool_freeze_s": 10800, "min_speed_kbps": 200,
        "youtube_check_every_s": 300,
    },
    "diversity": {"per_subnet_cap": 1, "min_pool_after_cap": 12, "max_cap_relax": 4},
    "blacklist": {"cloudflare_nodes": True},
}


def _deep_merge(dst: dict, src: dict) -> dict:
    """Дополняет dst значениями src (рекурсивно), не затирая уже заданные."""
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


# ─────────────────────────────────────────────────── загрузка ───
def load_config(path: str = None) -> dict:
    """Читает config.json. Если файла нет — создаёт из config.example.json.

    Возвращает словарь с добавленным блоком ``paths`` (state_dir/backup_dir/
    log_dir). Первый запуск без настроек безопасен: дефолты из config.example
    не содержат личных адресов и «РФ напрямую» выключено.
    """
    p = path or config_path()
    data: dict = {}
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    else:
        ex = example_config_path()
        if ex:
            try:
                with open(ex, encoding="utf-8") as f:
                    data = json.load(f)
                os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                tmp = p + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, p)
                log.get_logger().info("Конфиг не найден — создан из "
                                      "config.example.json: %s" % p)
            except Exception as e:
                log.get_logger().warn("первый запуск: создать конфиг не удалось "
                                      "(%s) — работаю на дефолтах" % e)
                data = {}

    cfg = _deep_merge(copy.deepcopy(DEFAULTS), data)

    root = (cfg.get("paths", {}) or {}).get("root") or app_root()
    root = os.path.abspath(root)
    cfg["paths"] = {
        "root": root,
        "state_dir": os.path.join(root, "state"),
        "backup_dir": os.path.join(root, "state", "backups"),
        "log_dir": os.path.join(root, "logs"),
    }
    for d in (cfg["paths"]["state_dir"], cfg["paths"]["backup_dir"],
              cfg["paths"]["log_dir"]):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
    cfg["_config_path"] = p
    return cfg


# ─────────────────────────────────────────────────── поиск ядра ───
def find_core(cfg: dict):
    """Путь к бинарю ядра xray (standalone): рядом с программой -> PATH.

    Порядок: явный путь из конфига -> bin\\xray\\xray.exe рядом с программой
    -> каталог программы -> PATH. Возвращает None, если ядро не найдено —
    вызывающий код предложит скачать официальный релиз Xray-core.
    """
    cl = cfg.get("client", {})
    for key in ("core", "core_rel"):
        explicit = cl.get(key)
        if explicit and os.path.isfile(explicit):
            return explicit
    names = ("xray.exe", "xray")
    dirs = (os.path.join(BASE_DIR, "bin", "xray"),
            os.path.join(PROJECT_DIR, "bin", "xray"),
            os.path.join(app_root(), "bin", "xray"),
            BASE_DIR, PROJECT_DIR, app_root())
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    for n in ("xray", "xray.exe"):
        p = shutil.which(n)
        if p:
            return p
    return None


def core_pid_path(cfg: dict) -> str:
    return os.path.join(cfg["paths"]["state_dir"], "core.pid")


def core_running(cfg: dict) -> bool:
    """Запущено ли НАШЕ ядро (по pid-файлу)."""
    p = core_pid_path(cfg)
    try:
        pid = int(open(p, encoding="utf-8").read().strip())
    except Exception:
        return False
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong(0)
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259       # STILL_ACTIVE
    except Exception:
        # не-Windows / нет прав — считаем живым по факту наличия pid
        return True


# ─────────────────────────────────────────────────── поиск клиента ───
def find_client(cfg: dict) -> dict:
    """Возвращает словарь клиента, зависящий от ``client.mode``.

    Общие поля: dir, exe, core, cfg (конфиг ядра), db (база/стор серверов),
    running, socks_port, mode. В standalone добавляется torrent_port.
    """
    mode = str(cfg.get("client", {}).get("mode") or "standalone").lower()
    if mode == "v2rayn":
        info = _find_client_v2rayn(cfg)
    else:
        info = _find_client_standalone(cfg)
    info["mode"] = mode
    return info


def _find_client_standalone(cfg: dict) -> dict:
    lg = log.get_logger()
    cl = cfg.get("client", {})
    socks_port = int(cl.get("socks_port", DEFAULT_SOCKS_PORT))
    torrent_port = int(cl.get("torrent_port", DEFAULT_TORRENT_PORT))
    state_dir = cfg["paths"]["state_dir"]
    core = find_core(cfg)
    info = {
        "mode": "standalone",
        "service": None,
        "dir": os.path.dirname(core) if core else None,
        "core": core,
        "exe": core or "xray.exe",
        "cfg": os.path.join(state_dir, "xray_config.json"),
        "db": os.path.join(state_dir, "servers.json"),
        "bin_cfg": os.path.join(state_dir, "xray_config.json"),
        "running": core_running(cfg),
        "socks_port": socks_port,
        "torrent_port": torrent_port,
    }
    if not core:
        lg.error("Ядро Xray не найдено. Положите bin\\xray\\xray.exe рядом с "
                 "программой или установите xray в PATH. Скачать официальный "
                 "релиз: https://github.com/XTLS/Xray-core/releases")
    return info


def _find_client_v2rayn(cfg: dict) -> dict:
    """Определение установки v2rayN (режим совместимости)."""
    lg = log.get_logger()
    cl = cfg.get("client", {})
    exe_name = cl.get("exe", "v2rayN.exe")
    socks_port = int(cl.get("socks_port", DEFAULT_SOCKS_PORT))

    dir_ = None
    running = False
    for p in _proc_paths_by_name(os.path.splitext(exe_name)[0]):
        d = os.path.dirname(p)
        if os.path.isfile(os.path.join(d, exe_name)):
            dir_, running = d, True
            break
    if dir_ is None and cl.get("dir"):
        d = cl["dir"]
        if os.path.isfile(os.path.join(d, exe_name)):
            dir_ = d
    if dir_ is None:
        for cand in _autodiscover():
            if os.path.isfile(os.path.join(cand, exe_name)):
                dir_ = cand
                break

    info = {"dir": dir_, "running": running, "socks_port": socks_port,
            "is_running_proc": running}
    if not dir_:
        lg.error("v2rayN не найден. Укажите client.dir в config.json")
        return info
    info["exe"] = os.path.join(dir_, exe_name)
    info["db"] = os.path.join(dir_, cl.get("db_rel", "guiConfigs/guiNDB.db"))
    info["cfg"] = os.path.join(dir_, cl.get("cfg_rel", "guiConfigs/guiNConfig.json"))
    core = os.path.join(dir_, cl.get("core_rel", "bin/xray/xray.exe"))
    info["core"] = core if os.path.isfile(core) else None
    try:
        with open(info["cfg"], encoding="utf-8") as f:
            cc = json.load(f)
        for i in cc.get("Inbound", []):
            if i.get("Protocol") in ("socks", "http") and i.get("LocalPort"):
                info["socks_port"] = int(i["LocalPort"])
                break
    except Exception:
        pass
    return info


def _proc_paths_by_name(name: str) -> list:
    """Пути запущенных процессов по имени exe (без администратора)."""
    out = []
    try:
        ps = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"Get-Process -Name {name} -ErrorAction SilentlyContinue | "
             "ForEach-Object { $_.Path }"],
            capture_output=True, text=True, errors="replace", timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for line in ps.stdout.splitlines():
            line = line.strip()
            if line:
                out.append(line)
    except Exception:
        pass
    return out


def _autodiscover() -> list:
    candidates = []
    try:
        ps = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-ChildItem -Path C:\\\\,D:\\\\ -Depth 3 -Filter v2rayN.exe "
             "-ErrorAction SilentlyContinue -Force | Select-Object -ExpandProperty FullName"],
            capture_output=True, text=True, errors="replace", timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for line in ps.stdout.splitlines():
            line = line.strip()
            if line:
                candidates.append(os.path.dirname(line))
    except Exception:
        pass
    return candidates


def proxy_for_fetch(cfg: dict) -> list:
    """Цепочка прокси для загрузки подписок: живой socks, затем напрямую.

    Можно задать явно через ``client.fetch_proxies`` (список строк, где
    "direct" — прямое соединение).
    """
    cl = cfg.get("client", {})
    if cl.get("fetch_proxies"):
        return list(cl["fetch_proxies"])
    socks = int(cl.get("socks_port", DEFAULT_SOCKS_PORT))
    return [f"http://127.0.0.1:{socks}", "direct"]
