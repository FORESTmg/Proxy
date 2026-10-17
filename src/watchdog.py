# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Автономный надзор: режим ``--ensure`` и задача Планировщика заданий (GPL-3.0).

Для чего это нужно
------------------
Программа — служба, от которой зависит связь пользователя, но раньше её
живучесть зависела от того, кто её запустил: если супервизор закрыть, если он
упадёт или если умрёт родительский процесс (например, обновление среды, которое
сносит своё дерево процессов), поднять его было некому. Это противоречит
замыслу «полностью автоматически, без участия человека».

Решение — два независимых механизма:

1. ``--ensure`` — быстрый режим: проверить, жив ли супервизор ЭТОЙ установки
   (по своему файлу-маркеру и/или по живому процессу), и если его нет —
   запустить ``--run`` **отвязанно от вызывающего процесса** (DETACHED_PROCESS +
   CREATE_BREAKAWAY_FROM_JOB + своя группа процессов), после чего молча выйти.
   Если супервизор уже есть — ничего не делает и ему не мешает. Защита от
   второго экземпляра тройная: файл-маркер, скан процессов и атомарный захват
   маркера самим ``--run``.

2. Задача Планировщика заданий Windows ``ForestProxyUpdater-Watchdog`` —
   автономный надзор вместо автозапуска из реестра: триггер «при входе в
   систему» с повтором каждые 5 минут бесконечно, действие
   ``ForestProxyUpdater.exe --ensure``, скрытая, «не запускать новый экземпляр,
   если задача уже выполняется» (MultipleInstancesPolicy=IgnoreNew), от имени
   текущего пользователя. Окно не показывается никогда.

Всё, что видит пользователь, пишется ТОЛЬКО в лог: никаких окон и диалогов.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time

import instancelock as IL
import log

# ─────────────────────────────────────────────────────── константы ───
APP_EXE_NAME = "ForestProxyUpdater.exe"
TASK_NAME_DEFAULT = "ForestProxyUpdater-Watchdog"
# Замок супервизора. Имя историческое (маркер) — файл тот же, но теперь это
# НАСТОЯЩИЙ эксклюзивный замок ОС, а не файл-маркер с PID. Файл НЕ удаляется
# при выходе: замок снимает ядро ОС вместе с процессом, а удаление файла
# позволило бы двум экземплярам держать замки на разных (старом и новом) файлах.
MARKER_NAME = "supervisor.lock"
ENSURE_LOCK_NAME = "ensure.lock"
# Пометка «этот процесс и есть супервизор» — единое правило самоконтроля:
# ни один поток супервизора не имеет права поднимать вторую копию.
SELF_ENV = "FOREST_SUPERVISOR"
# Повтор триггера задачи по умолчанию (минуты) — требование замысла: 5 минут.
DEFAULT_INTERVAL_MIN = 5
# Pid процесса, который УЖЕ стал супервизором в этой своей жизни (см.
# claim_supervisor): не даёт одному процессу занять замок дважды.
_CLAIMED_PID = 0
# Замок супервизора, удерживаемый этим процессом (объект InstanceLock).
_SUP_LOCK = None
_SUP_LOCK_PATH = ""

_NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _cfg_flag(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def task_name(cfg: dict = None) -> str:
    """Имя задачи Планировщика.

    Приоритет: FOREST_TASK_NAME (тесты/песочница) -> ``watchdog.task_name`` из
    конфига -> встроенное имя по умолчанию.
    """
    env = _cfg_flag("FOREST_TASK_NAME")
    if env:
        return env
    if isinstance(cfg, dict):
        v = str((cfg.get("watchdog") or {}).get("task_name") or "").strip()
        if v:
            return v
    return TASK_NAME_DEFAULT


def settings(cfg: dict) -> dict:
    """Настройки надзора: {enabled, interval_min, task_name} (с дефолтами)."""
    w = dict((cfg or {}).get("watchdog") or {}) if isinstance(cfg, dict) else {}
    try:
        interval = int(w.get("interval_min") or DEFAULT_INTERVAL_MIN)
    except Exception:
        interval = DEFAULT_INTERVAL_MIN
    interval = max(1, min(1440, interval))
    name = task_name(cfg)
    return {"enabled": bool(w.get("enabled", True)),
            "interval_min": interval,
            "task_name": name}


def _interval_iso(minutes: int) -> str:
    m = max(1, int(minutes))
    return f"PT{m}M"


def our_exe(cfg: dict) -> str:
    """Путь к исполняемому файлу ЭТОЙ установки.

    Собранный onefile-процесс знает себя точно — берём ``sys.executable``
    (важно для отладочных сборок с другим именем и для сверки образа процесса).
    В режиме разработки это ``<root>/ForestProxyUpdater.exe``.
    """
    try:
        if getattr(sys, "frozen", False) and sys.executable:
            return os.path.abspath(sys.executable)
    except Exception:
        pass
    return os.path.join(cfg["paths"]["root"], APP_EXE_NAME)


# ══════════════════════════════════════════════ процессы ═══
def pid_alive(pid: int) -> bool:
    """Жив ли процесс с таким pid (Windows: OpenProcess/POSIX: os.kill(pid,0)).

    «Доступ запрещён» трактуем как «жив» — важно НЕ поднять второй супервизор
    из-за того, что чужой/защищённый процесс не дал о себе прочитать.
    """
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            err = k32.GetLastError()
            return err == 5          # ERROR_ACCESS_DENIED -> процесс есть
        try:
            code = ctypes.c_ulong(0)
            STILL_ACTIVE = 259
            if k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _win_image_path(pid: int) -> str:
    """Полный путь образа процесса (Windows) или '' — для сверки, что pid наш."""
    if os.name != "nt":
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value or ""
        return ""
    except Exception:
        return ""
    finally:
        k32.CloseHandle(h)


def _identity_tokens(cfg: dict) -> list:
    """Строки, по которым узнаём «свой» процесс супервизора ЭТОЙ установки.

    Корень установки закодирован в пути запуска, поэтому разные установки
    (рабочая и песочница) друг друга не путают.
    """
    toks = []
    exe = our_exe(cfg)
    if exe:
        toks.append(os.path.normcase(os.path.abspath(exe)))
    # режим разработки: супервизор запущен как python …\src\v2ray_updater.py --run
    toks.append(os.path.normcase(os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "v2ray_updater.py"))))
    return [t for t in toks if t]


def _proc_rows_win() -> list:
    """[(pid, ppid, exe_path, cmdline)] одним запросом CIM (Windows)."""
    ps = (
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|"
        "$($_.ExecutablePath)|$($_.CommandLine)\" }"
    )
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=30, text=True, encoding="utf-8",
            errors="replace", creationflags=_NOWINDOW)
        text = r.stdout or ""
    except Exception as e:
        log.get_logger().warn(f"watchdog: не удалось получить список процессов: {e}")
        return []
    rows = []
    for line in text.replace("\r", "").split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        try:
            pid = int(parts[0].strip())
            ppid = int(parts[1].strip())
        except Exception:
            continue
        rows.append((pid, ppid, (parts[2] or "").strip(), parts[3] or ""))
    return rows


def _proc_rows_posix() -> list:
    rows = []
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            pid = int(name)
            try:
                with open(f"/proc/{pid}/stat", "rb") as f:
                    stat = f.read().decode("utf-8", "replace")
                ppid = int(stat.rsplit(")", 1)[1].split()[1])
                exe = os.readlink(f"/proc/{pid}/exe")
            except Exception:
                ppid, exe = 0, ""
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmdline = f.read().replace(b"\x00", b" ").decode("utf-8", "replace")
            except Exception:
                cmdline = ""
            rows.append((pid, ppid, exe, cmdline))
    except Exception:
        pass
    return rows


def _self_family_pids(rows: list, cfg: dict) -> set:
    """Наши СОБСТВЕННЫЕ процессы: сам процесс и его предки с тем же .exe.

    PyInstaller-onefile — это ДВА процесса (bootloader-родитель и настоящий
    Python-потомок) с одинаковой командной строкой. Без этого исключения
    ``--run`` видел бы в списке собственного родителя и отказывался стартовать,
    считая, что супервизор уже работает.
    """
    me = os.getpid()
    out = {me}
    try:
        want = os.path.normcase(os.path.abspath(our_exe(cfg)))
    except Exception:
        return out
    by_pid = {p: (pp, exe) for (p, pp, exe, _c) in rows}
    cur = me
    for _ in range(8):
        row = by_pid.get(cur)
        if not row:
            break
        pp, exe = row
        if not pp or pp <= 0:
            break
        pexe = os.path.normcase(os.path.abspath(exe or ""))
        if pexe and pexe == want:
            out.add(pp)
            cur = pp
            continue
        break
    return out


def _install_markers(cfg: dict) -> list:
    """Строки, по которым процесс ОТНОСИТСЯ к ЭТОЙ установке (корень/конфиг).

    Нужны, чтобы установки (рабочая, песочница, автотест с временным корнем)
    не принимали чужие процессы за свои: путь `.exe` лежит ВНУТРИ корня
    установки, поэтому у настоящего супервизора корень всегда есть в командной
    строке, а у чужого — нет.
    """
    out = []
    try:
        root = os.path.normcase(os.path.abspath(cfg["paths"]["root"]))
        if root:
            out.append(root)
    except Exception:
        pass
    try:
        p = os.path.normcase(os.path.abspath(str(cfg.get("_config_path") or "")))
        if p:
            out.append(p)
    except Exception:
        pass
    return out


def _scan_our_supervisors(cfg: dict) -> list:
    """Pid процессов ``--run`` ЭТОЙ установки (без своих), по списку процессов.

    Нужен как СТРАХОВКА/диагностика: у старой версии нет замка, а также когда
    замок деградирован. Ничего не трогает — только читает список. Решение о
    запуске второго экземпляра по этому скану НЕ принимается (см.
    claim_supervisor): скан неатомарен и именно он раньше приводил к двум
    экземплярам и к «не выживает никто».
    """
    toks = _identity_tokens(cfg)
    marks = _install_markers(cfg)
    rows = _proc_rows_win() if os.name == "nt" else _proc_rows_posix()
    if not rows:
        return []
    skip = _self_family_pids(rows, cfg)
    out = []
    for pid, _pp, path, cmdline in rows:
        if pid in skip:
            continue
        cmd = os.path.normcase(cmdline)
        pth = os.path.normcase(path)
        if "--run" not in cmd:
            continue
        if not (any(t in cmd for t in toks) or (pth and any(t == pth for t in toks))):
            continue
        # принадлежность установке: корень (или путь конфига) обязан быть виден
        if marks and not any(m in cmd for m in marks):
            continue
        out.append(pid)
    return out


# ══════════════════════════════════════════════ маркер супервизора ═══
def marker_path(cfg: dict) -> str:
    return os.path.join(cfg["paths"]["state_dir"], MARKER_NAME)


def read_marker(cfg: dict) -> dict:
    try:
        with open(marker_path(cfg), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _marker_matches(d: dict, cfg: dict) -> bool:
    """Маркер относится к ЭТОЙ установке и этому корню?"""
    try:
        root = os.path.normcase(os.path.abspath(cfg["paths"]["root"]))
        mroot = os.path.normcase(os.path.abspath(str(d.get("root") or "")))
        if mroot and mroot != root:
            return False
        mex = os.path.normcase(os.path.abspath(str(d.get("exe") or "")))
        if mex:
            want = os.path.normcase(os.path.abspath(our_exe(cfg)))
            if mex != want:
                return False
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════ замок супервизора ═══
def supervisor_lock(cfg: dict) -> IL.InstanceLock:
    """Замок супервизора этой установки (один объект на процесс, до выхода).

    Файл тот же, что был у маркера (``state/supervisor.lock``), поэтому и
    документация, и каталог состояния остаются привычными. Но теперь это
    НАСТОЯЩИЙ замок: его держит ядро ОС, пока жив процесс.
    """
    global _SUP_LOCK, _SUP_LOCK_PATH
    p = marker_path(cfg)
    if _SUP_LOCK is None or _SUP_LOCK_PATH != p:
        _SUP_LOCK = IL.InstanceLock(p, tag="supervisor")
        _SUP_LOCK_PATH = p
    return _SUP_LOCK


def we_are_supervisor() -> bool:
    """Этот процесс УЖЕ супервизор? Единое правило самоконтроля."""
    return (_CLAIMED_PID == os.getpid()
            or os.environ.get(SELF_ENV) == "1")


def supervisor_lock_held(cfg: dict) -> bool:
    """Занят ли замок супервизора (нами или другим живым экземпляром)."""
    if we_are_supervisor() and _SUP_LOCK is not None and _SUP_LOCK.held:
        return True
    return IL.held(marker_path(cfg))


def _info_for_marker(cfg: dict, argv=None) -> dict:
    """Данные владельца замка — ТОЛЬКО для диагностики (решения — по замку)."""
    return {
        "pid": os.getpid(),
        "ts": time.time(),
        "exe": our_exe(cfg),
        "root": cfg["paths"]["root"],
        "argv": list(argv if argv is not None else sys.argv[1:]),
        "frozen": bool(getattr(sys, "frozen", False)),
        "lock": True,
    }


def _marker_live_pid(cfg: dict) -> int:
    """Pid живого супервизора ЭТОЙ установки, иначе 0.

    Источник истины — замок: занят, значит экземпляр жив (ОС снимает замок
    ровно тогда, когда процесс кончился). PID берём из диагностики; если её
    нет — 0 (вызывающий сам решает, что делать: см. find_live_supervisor).
    """
    if supervisor_lock_held(cfg):
        d = IL.read_info(marker_path(cfg))
        if d and _marker_matches(d, cfg) is False:
            return 0
        try:
            pid = int(d.get("pid") or 0)
        except Exception:
            pid = 0
        return pid if pid > 0 else 0
    return _legacy_marker_pid(cfg)


def _legacy_marker_pid(cfg: dict) -> int:
    """Старый признак (маркер без замка) — только для перехода и отчётов.

    Нужен, чтобы ``--status``/``--watchdog status`` честно показывали экземпляр
    прежней версии, который замка ещё не держит. Решение о запуске второй копии
    по этому признаку НЕ принимается.
    """
    d = read_marker(cfg)
    if not d or not _marker_matches(d, cfg):
        return 0
    try:
        pid = int(d.get("pid") or 0)
    except Exception:
        return 0
    if not pid_alive(pid):
        return 0
    # сверка образа (Windows, только для собранного .exe): защита от
    # переиспользования pid. В режиме разработки образ — это python.exe,
    # поэтому сверять его с нашим путём нельзя.
    if os.name == "nt" and getattr(sys, "frozen", False):
        img = _win_image_path(pid)
        if img:
            want = os.path.normcase(os.path.abspath(our_exe(cfg)))
            if os.path.normcase(os.path.abspath(img)) != want:
                return 0
    return pid


def write_marker(cfg: dict, argv=None) -> None:
    """Пишет диагностику владельца замка (JSON). Замок это не заменяет.

    Если замок у нас — пишем в его файл; если нет (проверки/переход) — просто
    пишем файл, как раньше, чтобы отчёты и тесты читали те же данные.
    """
    p = marker_path(cfg)
    d = _info_for_marker(cfg, argv)
    lk = _SUP_LOCK
    if lk is not None and lk.held and lk.path == p:
        lk.write_info(d)
        return
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception as e:
        log.get_logger().warn(f"watchdog: маркер не записан: {e}")


def clear_marker(cfg: dict) -> None:
    """Убирает файл замка — только у СВОЕГО процесса (иначе чужой замок цел).

    В обычной работе файл замка не удаляется: ОС снимает сам замок при выходе
    процесса, а удаление файла могло бы «разъехаться» с замком (см.
    instancelock.InstanceLock.release). Здесь — для проверок и явного сброса.
    """
    lk = _SUP_LOCK
    try:
        if lk is not None and lk.held and lk.path == marker_path(cfg):
            lk.release()
            return
        d = read_marker(cfg)
        if d and int(d.get("pid") or 0) == os.getpid():
            os.unlink(marker_path(cfg))
    except Exception:
        pass


# ══════════════════════════════════════════════ поиск живого супервизора ═══
def find_live_supervisor(cfg: dict, exclude=()) -> int:
    """Pid живого супервизора ЭТОЙ установки, иначе 0. Ничего не меняет.

    Источник истины — ЗАМОК. Скан процессов нужен только чтобы НАЗВАТЬ pid,
    когда замок занят, а данных владельца ещё нет. Решение о запуске второй
    копии по этому признаку не принимается (см. claim_supervisor/ensure).
    """
    ex = set(int(x) for x in (exclude or ()))
    pid = _marker_live_pid(cfg)
    if pid:
        return pid if pid not in ex else 0
    if supervisor_lock_held(cfg) or we_are_supervisor():
        # замок занят/держим нами, а pid неизвестен — уточняем сканом
        for p in _scan_our_supervisors(cfg):
            if p not in ex:
                return p
        return 0
    # переход: экземпляр прежней версии (замка ещё нет)
    for p in _scan_our_supervisors(cfg):
        if p not in ex:
            return p
    return 0


def claim_supervisor(cfg: dict) -> bool:
    """Стать супервизором. False — живой супервизор уже есть (второй не нужен).

    Проверка РОВНО одна и она атомарна: эксклюзивный замок файла, который
    держит ядро ОС всё время жизни процесса. Гонки на старте нет: при
    одновременном запуске замок достаётся ровно одному — второй видит живой
    замок и тихо выходит. Список процессов для этого решения НЕ используется:
    он неатомарен и раньше приводил и к двум экземплярам, и к тому, что не
    выживал никто.
    """
    global _CLAIMED_PID
    lg = log.get_logger()
    me = os.getpid()
    if we_are_supervisor():
        return False            # этот процесс уже супервизор
    lk = supervisor_lock(cfg)
    if not lk.acquire(_info_for_marker(cfg)):
        d = lk.read_info()
        try:
            owner = int(d.get("pid") or 0)
        except Exception:
            owner = 0
        lg.info("watchdog: супервизор уже работает (pid %s; замок %s) — "
                "второй не запускаю" % (owner or "?", marker_path(cfg)))
        return False
    _CLAIMED_PID = me
    os.environ[SELF_ENV] = "1"
    if lk.degraded:
        lg.warn("watchdog: замок супервизора деградирован (файл недоступен) — "
                "работаю без него")
    lg.info(f"watchdog: замок супервизора занят (pid {me}, {marker_path(cfg)})")
    return True


def release_supervisor(cfg: dict) -> None:
    """Отпускает замок. Файл не удаляем — замок снимает ОС вместе с процессом."""
    global _CLAIMED_PID
    _CLAIMED_PID = 0
    try:
        os.environ.pop(SELF_ENV, None)
    except Exception:
        pass
    lk = _SUP_LOCK
    if lk is not None and lk.held:
        lk.release(unlink=False)
    try:
        with open(marker_path(cfg), "w", encoding="utf-8") as f:
            json.dump({"pid": 0, "ts": time.time(), "released": True,
                       "root": cfg["paths"]["root"], "exe": our_exe(cfg)}, f)
    except Exception:
        pass


# ══════════════════════════════════════════════ --ensure ═══
def _ensure_lock_path(cfg: dict) -> str:
    return os.path.join(cfg["paths"]["state_dir"], ENSURE_LOCK_NAME)


def _acquire_ensure_lock(cfg: dict):
    """Короткий замок «сейчас идёт запуск супервизора». None — запуск уже идёт.

    Замок эксклюзивный и снимается ядром ОС вместе с процессом, поэтому
    «зависших» замков не бывает и ждать/чистить устаревшие файлы не нужно
    (в отличие от прежнего файла-маркера с проверкой возраста).
    """
    return IL.try_spawn_lock(_ensure_lock_path(cfg))


def _release_ensure_lock(lock) -> None:
    if lock is not None:
        lock.release(unlink=False)


def launch_command(cfg: dict) -> list:
    """Команда запуска супервизора: [exe|pythonw, (script,) '--run', '--config', path]."""
    cfg_path = cfg.get("_config_path") or ""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        py = sys.executable
        if os.name == "nt" and os.path.basename(py).lower() == "python.exe":
            alt = os.path.join(os.path.dirname(py), "pythonw.exe")
            if os.path.isfile(alt):
                py = alt
        cmd = [py, os.path.join(os.path.dirname(os.path.abspath(__file__)), "v2ray_updater.py")]
    cmd.append("--run")
    if cfg_path:
        cmd += ["--config", cfg_path]
    return cmd


# Переменные окружения PyInstaller-onefile. Из-за них запущенная нами КОПИЯ
# СЕБЯ переиспользует НАШ каталог распаковки (_MEI) вместо своего: тогда наш
# уборщик не может удалить _MEI (файлы заняты живым потомком) и пользователю
# показывается модальное окно «Failed to remove temporary directory».
_PYI_VARS = ("_PYI_APPLICATION_HOME_DIR", "_PYI_PARENT_PROCESS_LEVEL",
             "_PYI_ARCHIVE_FILE", "_MEIPASS2", "_PYI_SPLASH_IPC")


def sanitize_child_env(env: dict) -> dict:
    """Готовит окружение ПОТОМКА так, чтобы он распаковывался в свой _MEI.

    Убираем переменные PyInstaller и ставим PYINSTALLER_RESET_ENVIRONMENT=1:
    потомок считается «верхним» процессом — распаковывается в СВОЙ каталог и
    сам же его убирает при выходе. Без этого отвязанный ``--run`` держал бы
    файлы из _MEI родителя, и при выходе родителя всплывало окно ошибки.
    """
    for k in _PYI_VARS:
        env.pop(k, None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _spawn_detached(cmd: list, root: str, cfg: dict) -> tuple:
    """Запускает процесс ОТВЯЗАННО от вызывающего. -> (ok, pid|0).

    Windows: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
    (последний, чтобы смерть дерева процессов родителя — например, обновление
    среды — не уносила супервизор). Если job не даёт breakaway — повтор без него.
    POSIX: setsid (новая сессия), без управляющего терминала.

    Единое правило самоконтроля: процесс, который САМ является супервизором,
    не поднимает вторую копию ни при каких обстоятельствах.
    """
    if we_are_supervisor():
        log.get_logger().error("watchdog: отказ от запуска — этот процесс сам "
                               "супервизор (второй копии быть не должно)")
        return False, 0
    env = dict(os.environ)
    env["FOREST_ROOT"] = cfg["paths"]["root"]
    if cfg.get("_config_path"):
        env["FOREST_CONFIG"] = cfg["_config_path"]
    # Потомок обязан распаковаться в СВОЙ каталог _MEI (иначе наш уборщик не
    # сможет снести _MEI и покажет модальное окно — см. sanitize_child_env).
    env = sanitize_child_env(env)
    try:
        os.makedirs(root, exist_ok=True)
    except Exception:
        pass
    devnull = subprocess.DEVNULL
    if os.name == "nt":
        flags_base = (getattr(subprocess, "DETACHED_PROCESS", 0)
                      | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                      | _NOWINDOW)
        brk = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        for flags in (flags_base | brk, flags_base):
            try:
                p = subprocess.Popen(cmd, cwd=root or None, env=env,
                                     stdin=devnull, stdout=devnull, stderr=devnull,
                                     close_fds=True, creationflags=flags)
                return True, p.pid
            except OSError:
                continue
            except Exception as e:
                log.get_logger().error(f"watchdog: запуск не удался: {e}")
                return False, 0
        return False, 0
    try:
        p = subprocess.Popen(cmd, cwd=root or None, env=env,
                             stdin=devnull, stdout=devnull, stderr=devnull,
                             close_fds=True, start_new_session=True)
        return True, p.pid
    except Exception as e:
        log.get_logger().error(f"watchdog: запуск не удался: {e}")
        return False, 0


def _wait_supervisor(cfg: dict, timeout_s: float = 12.0) -> int:
    """Ждёт появления ЖИВОГО замка супервизора. -> pid|0. Только для сверки."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if supervisor_lock_held(cfg):
            return find_live_supervisor(cfg, exclude=(os.getpid(),))
        time.sleep(0.25)
    return 0


def ensure(cfg: dict, spawn: bool = True) -> int:
    """``--ensure``: поднять супервизор, если его нет. Тихий, быстрый.

    Вывод — только в лог. Возврат: 0 — всё в порядке (супервизор есть или
    поднят), 1 — поднять не удалось.

    Правила (одинаковые для задачи Планировщика, ручного вызова и любых
    внутренних проверок):

    1. живой замок супервизора -> НИЧЕГО не делаем (лишний тик/вызов безвреден);
    2. этот процесс сам супервизор -> вторую копию не поднимаем никогда;
    3. запуск сериализован коротким замком «идёт запуск» (гонка двух --ensure).
    """
    lg = log.get_logger()
    if we_are_supervisor():
        lg.info("watchdog: я и есть супервизор — вторую копию не поднимаю")
        return 0
    if supervisor_lock_held(cfg):
        pid = find_live_supervisor(cfg, exclude=(os.getpid(),))
        lg.info("watchdog: супервизор жив (pid %s; замок занят) — ничего не делаю"
                % (pid or "?"))
        return 0
    spawn_lock = _acquire_ensure_lock(cfg)
    if spawn_lock is None:
        lg.info("watchdog: другой --ensure/запуск уже идёт — выхожу")
        return 0
    try:
        if supervisor_lock_held(cfg):      # перепроверка уже под замком запуска
            lg.info("watchdog: супервизор появился, пока брал замок запуска — "
                    "ничего не делаю")
            return 0
        cmd = launch_command(cfg)
        lg.info("watchdog: супервизора нет — запускаю отвязанно: %s" % " ".join(cmd))
        if not spawn:
            lg.info("watchdog: (пробный режим — запуск не выполняется)")
            return 0
        ok, new_pid = _spawn_detached(cmd, cfg["paths"]["root"], cfg)
        if not ok:
            lg.error("watchdog: супервизор поднять не удалось")
            return 1
        lg.info(f"watchdog: супервизор запущен (pid {new_pid})")
        got = _wait_supervisor(cfg)
        if got or supervisor_lock_held(cfg):
            pid = got or find_live_supervisor(cfg, exclude=(os.getpid(),))
            lg.info("watchdog: замок супервизора подтверждён" +
                    (f" (pid {pid})" if pid else ""))
        else:
            lg.warn("watchdog: замок супервизора не появился за отведённое время "
                    "(супервизор мог ещё стартовать)")
        return 0
    finally:
        _release_ensure_lock(spawn_lock)


# ══════════════════════════════════════════════ задача Планировщика ═══
def current_user() -> str:
    """Текущий пользователь в виде DOMAIN\\user (для задачи)."""
    for k in ("USERDOMAIN", "USERDNSDOMAIN"):
        d = (os.environ.get(k) or "").strip()
        u = (os.environ.get("USERNAME") or "").strip()
        if d and u:
            return f"{d}\\{u}"
    try:
        r = subprocess.run(["whoami"], capture_output=True, text=True, timeout=15,
                           creationflags=_NOWINDOW)
        v = (r.stdout or "").strip()
        if v:
            return v
    except Exception:
        pass
    return (os.environ.get("USERNAME") or "").strip()


def task_xml(exe: str, args: str, workdir: str, user: str,
             description: str = "", interval_min: int = 5) -> str:
    """XML задачи (чистая функция — проверяется автотестами без системы).

    Триггеры: «при входе в систему» (LogonTrigger) и повтор каждые
    ``interval_min`` минут БЕЗ ограничения длительности (TimeTrigger с
    StartBoundary в прошлом = «повторять бесконечно», задача работает сразу
    после установки, не дожидаясь следующего входа). Скрытая задача, IgnoreNew
    (не запускать новый экземпляр, если задача уже выполняется), интерактивный
    токен текущего пользователя, StartWhenAvailable.
    """
    def esc(s: str) -> str:
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))
    desc = description or ("FOREST's Proxy Auto-updater — автономный надзор: "
                           "поднимает супервизор, если он не работает")
    interval = _interval_iso(interval_min)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{esc(desc)}</Description>
    <Author>FOREST's Proxy Auto-updater</Author>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>2020-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>{interval}</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{esc(user)}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{esc(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{esc(exe)}</Command>
      <Arguments>{esc(args)}</Arguments>
      <WorkingDirectory>{esc(workdir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _schtasks(args: list, timeout: int = 60) -> tuple:
    try:
        r = subprocess.run(["schtasks.exe"] + args, capture_output=True, timeout=timeout,
                           text=True, errors="replace", creationflags=_NOWINDOW)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return 1, str(e)


def query_task(name: str = None, cfg: dict = None) -> str:
    """XML задачи или '' (не создана/недоступна)."""
    rc, out = _schtasks(["/Query", "/TN", name or task_name(cfg), "/XML"])
    if rc == 0 and "<Task" in out:
        return out
    return ""


def task_exists(name: str = None, cfg: dict = None) -> bool:
    return bool(query_task(name, cfg))


def create_watchdog_task(exe: str, args: str, workdir: str,
                         cfg: dict = None, name: str = None,
                         interval_min: int = None) -> tuple:
    """Создаёт/перезаписывает задачу надзора. -> (ok, сообщение)."""
    import tempfile
    st = settings(cfg)
    nm = name or st["task_name"]
    iv = st["interval_min"] if interval_min is None else int(interval_min)
    xml = task_xml(exe, args, workdir, current_user(), interval_min=iv)
    try:
        fd, path = tempfile.mkstemp(prefix="forest_task_", suffix=".xml")
        with os.fdopen(fd, "wb") as f:
            f.write(xml.encode("utf-16"))          # BOM + UTF-16 LE — как ждёт schtasks
    except Exception as e:
        return False, f"XML не записан: {e}"
    try:
        rc, out = _schtasks(["/Create", "/TN", nm, "/XML", path, "/F"])
        if rc != 0:
            return False, out or f"schtasks код {rc}"
        if not query_task(nm):
            return False, "задача создана, но не читается обратно"
        return True, f"задача создана и включена: {nm}"
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def delete_task(name: str = None, cfg: dict = None) -> tuple:
    """Удаляет задачу. Отсутствие задачи — не ошибка. -> (ok, сообщение)."""
    nm = name or task_name(cfg)
    if not task_exists(nm):
        return True, f"задачи нет: {nm}"
    rc, out = _schtasks(["/Delete", "/TN", nm, "/F"])
    if rc != 0:
        return False, out or f"schtasks код {rc}"
    if task_exists(nm):
        return False, "задача всё ещё читается после удаления"
    return True, f"задача удалена: {nm}"


def set_task_enabled(enabled: bool, name: str = None, cfg: dict = None) -> tuple:
    """Включить/выключить задачу, не удаляя её. -> (ok, сообщение)."""
    nm = name or task_name(cfg)
    flag = "/ENABLE" if enabled else "/DISABLE"
    rc, out = _schtasks(["/Change", "/TN", nm, flag])
    return (rc == 0), (out or f"schtasks код {rc}")


def task_action(name: str = None, cfg: dict = None) -> str:
    """Строка «что запускает задача» (из XML — язык системы не мешает)."""
    xml = query_task(name, cfg)
    if not xml:
        return ""
    try:
        import re
        cmd = re.search(r"<Command>(.*?)</Command>", xml, re.S)
        arg = re.search(r"<Arguments>(.*?)</Arguments>", xml, re.S)
        c = (cmd.group(1).strip() if cmd else "")
        a = (arg.group(1).strip() if arg else "")
        return (c + " " + a).strip()
    except Exception:
        return ""


def task_status(cfg: dict = None, name: str = None) -> dict:
    """Честное состояние задачи: есть ли, включена ли, когда запускалась.

    Данные берём из PowerShell (Get-ScheduledTask/Get-ScheduledTaskInfo) —
    свойства там на английском и не зависят от языка системы.
    """
    st = settings(cfg)
    nm = name or st["task_name"]
    out = {"task_name": nm, "exists": False, "state": "absent", "enabled": False,
           "last_run": "", "next_run": "", "last_result": "", "action": ""}
    if os.name != "nt":
        out["state"] = "недоступно (не Windows)"
        return out
    ps = (
        f"$n='{nm.replace(chr(39), chr(39) * 2)}';"
        "$t=Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue;"
        "if($t){"
        "  $i=Get-ScheduledTaskInfo -TaskName $n -ErrorAction SilentlyContinue;"
        "  Write-Output ('EXISTS|' + $t.State + '|' + "
        "($i.LastRunTime) + '|' + ($i.NextRunTime) + '|' + ($i.LastTaskResult))"
        "} else { Write-Output 'ABSENT' }"
    )
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=30, text=True, errors="replace",
            creationflags=_NOWINDOW)
        text = (r.stdout or "").strip()
    except Exception as e:
        out["state"] = f"ошибка запроса: {e}"
        return out
    if not text or text.startswith("ABSENT"):
        return out
    parts = text.split("|")
    if len(parts) >= 5:
        out["exists"] = True
        out["state"] = parts[1].strip() or "Unknown"
        out["enabled"] = out["state"].lower() == "ready"
        out["last_run"] = parts[2].strip()
        out["next_run"] = parts[3].strip()
        out["last_result"] = parts[4].strip()
        out["action"] = task_action(nm, cfg)
    return out


# ══════════════════════════════════════════════ применение настройки ═══
def install_args(cfg: dict) -> str:
    """Аргументы задачи: ``--ensure`` (+ ``--config`` — фиксируем нужный конфиг)."""
    args = "--ensure"
    p = cfg.get("_config_path") or ""
    if p:
        args += f' --config "{p}"'
    return args


def apply_watchdog(cfg: dict, log_msg: bool = True) -> dict:
    """Приводит задачу в соответствие настройке ``watchdog``.

    enabled=True  -> создать/перезаписать задачу (действие --ensure);
    enabled=False -> удалить задачу, если была.
    -> {"ok", "action": "created"|"removed"|"unchanged"|"failed", "detail"}
    """
    lg = log.get_logger()
    st = settings(cfg)
    if os.name != "nt":
        res = {"ok": True, "action": "unchanged",
               "detail": "надзор на Linux обеспечивает systemd (Restart=always + таймер)"}
        if log_msg:
            lg.info(f"watchdog: {res['detail']}")
        return res
    nm = st["task_name"]
    if not st["enabled"]:
        if task_exists(nm):
            ok, detail = delete_task(nm)
            res = {"ok": ok, "action": "removed" if ok else "failed", "detail": detail}
        else:
            res = {"ok": True, "action": "unchanged", "detail": f"надзор выключен, задачи нет: {nm}"}
        if log_msg:
            lg.info(f"watchdog: {res['detail']}")
        return res
    exe = sys.executable if getattr(sys, "frozen", False) else our_exe(cfg)
    if not getattr(sys, "frozen", False):
        # режим разработки: задача указывает на pythonw + скрипт
        py = sys.executable
        if os.path.basename(py).lower() == "python.exe":
            alt = os.path.join(os.path.dirname(py), "pythonw.exe")
            if os.path.isfile(alt):
                py = alt
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v2ray_updater.py")
        exe = py
        args = f'"{script}" {install_args(cfg)}'
    else:
        args = install_args(cfg)
    ok, detail = create_watchdog_task(exe, args, cfg["paths"]["root"], cfg=cfg)
    res = {"ok": ok, "action": "created" if ok else "failed", "detail": detail}
    if log_msg:
        (lg.info if ok else lg.error)(f"watchdog: {detail}")
    return res


def watchdog_report(cfg: dict) -> dict:
    """Сводка для ``--watchdog status`` / ``--status`` (без побочных эффектов).

    «Работает ли программа» решает ЗАМОК (он не врёт: его снимает ядро ОС
    вместе с процессом), а pid из диагностики замка/скана — только для показа.
    """
    st = settings(cfg)
    pid = find_live_supervisor(cfg, exclude=(os.getpid(),))
    rep = {"settings": st, "task": task_status(cfg), "supervisor_pid": pid}
    rep["supervisor_alive"] = bool(pid) or supervisor_lock_held(cfg)
    return rep
