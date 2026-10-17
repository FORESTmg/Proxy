# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
"""Мост «помощник интерфейса ↔ программа»: команды через файл в каталоге состояния.

Зачем именно так
----------------
Помощник интерфейса (``forest-ui``, Qt) рисует значок, меню и уведомления, но
**ядром не управляет**. Он кладёт команду в ``state/ui_cmd.json``, а супервизор
(единственный хозяин ядра) её читает и выполняет штатными средствами:

  * ``refresh``          — триггер ``state/refresh.flag`` (``tray_menu``);
  * ``toggle_proxy``     — ручное включение/выключение (``clientwrite``);
  * ``watchdog_on/off``  — задача автономного надзора (``watchdog``);
  * ``notify_on/off``    — ``notify.enabled`` в ``config.json``;
  * ``theme_*``          — ``ui.theme`` (auto|light|dark);
  * ``filter_ru_on/off`` — фильтр «РФ — напрямую» (``watch.ru_direct``);
  * ``filter_cf_on/off`` — фильтр «Cloudflare — обход»
    (``blacklist.cloudflare_nodes``);
  * ``exit``             — штатная остановка (``state/stop.flag``).

Так у программы остаётся РОВНО один хозяин состояния: помощник может упасть,
быть не установленным или не запущенным — программа работает как обычно.

Файл результата ``state/ui_cmd_result.json`` — чтобы помощник мог показать
пользователю, чем закончилась команда (и чтобы проверки могли это подтвердить).

Модуль без внешних зависимостей, работает и на Windows, и на Linux.
"""
from __future__ import annotations

import json
import os
import time

CMD_FILE = "ui_cmd.json"
RESULT_FILE = "ui_cmd_result.json"
PING_FILE = "ui_helper.json"       # помощник пишет сюда: «я жив, вот мой pid»

# команды, которые понимает супервизор (имена — часть протокола, не менять)
COMMANDS = (
    "ping",         # «ты жив?» — супервизор отвечает, ядро не трогаем
    "status",       # показать состояние (ничего не меняет)
    "refresh",      # обновить серверы сейчас
    "toggle_proxy", # включить/выключить прокси вручную
    "watchdog_on",
    "watchdog_off",
    "notify_on",
    "notify_off",
    "theme_auto",
    "theme_light",
    "theme_dark",
    "filter_ru_on",   # фильтр «РФ — напрямую»: включить
    "filter_ru_off",  # фильтр «РФ — напрямую»: выключить
    "filter_cf_on",   # фильтр «Cloudflare — обход»: включить
    "filter_cf_off",  # фильтр «Cloudflare — обход»: выключить
    "exit",
)

STALE_S = 120.0        # команда старше этого возраста не выполняется (устарела)


def _dir(cfg: dict) -> str:
    try:
        return (cfg.get("paths") or {}).get("state_dir") or ""
    except Exception:
        return ""


def cmd_path(cfg: dict) -> str:
    d = _dir(cfg)
    return os.path.join(d, CMD_FILE) if d else ""


def result_path(cfg: dict) -> str:
    d = _dir(cfg)
    return os.path.join(d, RESULT_FILE) if d else ""


def ping_path(cfg: dict) -> str:
    d = _dir(cfg)
    return os.path.join(d, PING_FILE) if d else ""


def _write_json(path: str, data: dict) -> bool:
    if not path:
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# ── сторона помощника интерфейса ────────────────────────────────────────────
def write_cmd(cfg: dict, cmd: str, value=None) -> bool:
    """Помощник кладёт команду. Супервизор её прочитает и выполнит."""
    if cmd not in COMMANDS:
        return False
    rec = {"ts": time.time(), "cmd": cmd, "by": "ui"}
    if value is not None:
        rec["value"] = value
    return _write_json(cmd_path(cfg), rec)


def read_result(cfg: dict) -> dict:
    return _read_json(result_path(cfg))


def helper_alive(cfg: dict, max_age_s: float = 15.0) -> bool:
    """Жив ли помощник (пишет пульс в state/ui_helper.json)."""
    d = _read_json(ping_path(cfg))
    try:
        return (time.time() - float(d.get("ts", 0) or 0)) < max_age_s
    except Exception:
        return False


def write_ping(cfg: dict, pid: int, note: str = "") -> bool:
    return _write_json(ping_path(cfg), {"ts": time.time(), "pid": int(pid),
                                        "note": note})


def clear_ping(cfg: dict) -> None:
    for p in (ping_path(cfg), cmd_path(cfg)):
        try:
            if p and os.path.isfile(p):
                os.unlink(p)
        except Exception:
            pass


# ── сторона супервизора ─────────────────────────────────────────────────────
def consume(cfg: dict) -> dict:
    """Читает и снимает команду. -> {} если команды нет/она устарела."""
    p = cmd_path(cfg)
    rec = _read_json(p)
    if not rec:
        return {}
    try:
        if p:
            os.unlink(p)
    except Exception:
        pass
    if rec.get("cmd") not in COMMANDS:
        return {}
    try:
        if (time.time() - float(rec.get("ts", 0) or 0)) > STALE_S:
            _write_result(cfg, rec, False, "команда устарела")
            return {}
    except Exception:
        pass
    return rec


def _write_result(cfg: dict, rec: dict, ok: bool, msg: str) -> None:
    _write_json(result_path(cfg), {"ts": time.time(), "cmd": rec.get("cmd", ""),
                                   "ok": bool(ok), "msg": msg})


def apply(cfg: dict, rec: dict) -> tuple:
    """Выполняет команду ШТАТНЫМИ средствами программы. -> (ok, сообщение).

    Ничего своего не придумываем: те же функции, что у пунктов встроенного
    меню трея, поэтому поведение одинаково с обоих путей.
    """
    import log as LG
    import tray_menu as TM
    lg = LG.get_logger()
    cmd = (rec or {}).get("cmd", "")
    if not cmd:
        return False, "нет команды"
    try:
        actions = _actions(cfg)
    except Exception as e:
        _write_result(cfg, rec, False, f"меню недоступно: {e}")
        return False, f"меню недоступно: {e}"
    ok, msg = True, ""
    try:
        if cmd == "ping":
            msg = "помощник на связи"
        elif cmd == "status":
            msg = actions.status_text() if hasattr(actions, "status_text") else "состояние"
        elif cmd == "refresh":
            msg = actions.request_refresh()
        elif cmd == "toggle_proxy":
            msg = actions.toggle_proxy()
        elif cmd in ("watchdog_on", "watchdog_off"):
            msg = actions.set_watchdog(cmd == "watchdog_on")
        elif cmd in ("notify_on", "notify_off"):
            msg = actions.set_notify(cmd == "notify_on")
        elif cmd in ("theme_auto", "theme_light", "theme_dark"):
            msg = actions.set_theme(cmd.split("_", 1)[1])
        elif cmd in ("filter_ru_on", "filter_ru_off"):
            msg = actions.set_ru_direct(cmd.endswith("_on"))
        elif cmd in ("filter_cf_on", "filter_cf_off"):
            msg = actions.set_cloudflare(cmd.endswith("_on"))
        elif cmd == "exit":
            msg = _request_exit(cfg)
        else:
            ok, msg = False, f"неизвестная команда: {cmd}"
    except Exception as e:
        ok, msg = False, f"{cmd}: {e}"
    lg.info(f"помощник интерфейса -> команда «{cmd}»: "
            f"{'OK' if ok else 'ОШИБКА'} {msg}")
    _write_result(cfg, rec, ok, msg)
    return ok, msg


def _actions(cfg: dict):
    import tray_menu as TM
    return TM.TrayActions(cfg)


def _request_exit(cfg: dict) -> str:
    """Штатная остановка: тот же файл-флаг, что и у встроенного меню трея."""
    import i18n as I
    d = _dir(cfg)
    if not d:
        return "нет каталога состояния"
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "stop.flag"), "w", encoding="utf-8") as f:
            f.write("exit from ui helper")
        return I.t("tray.msg.exit_sent")
    except Exception as e:
        return I.t("error.generic", err=e)
