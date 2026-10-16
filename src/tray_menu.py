# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Логика меню трея: команды, состояние, фильтры (GPL-3.0).

Здесь НЕТ графики и Win32 — только смысл пунктов меню, поэтому модуль
тестируется без окна. Всё, что видит пользователь, берётся из :mod:`i18n`.

Команды (идентификаторы пунктов меню)::

    CMD_TOGGLE_PROXY  — включить/выключить прокси ВРУЧНУЮ (флаг proxy_off.flag)
    CMD_STATUS        — показать состояние
    CMD_REFRESH       — обновить серверы сейчас (триггер refresh.flag)
    CMD_OPEN_LOG      — открыть лог
    CMD_EXIT          — выход
    CMD_FILTER_RU     — фильтр «РФ — напрямую» (watch.ru_direct)
    CMD_FILTER_CF     — фильтр «Cloudflare — обход» (blacklist.cloudflare_nodes)

Протокол команд — ТОТ ЖЕ, что уже используется в проекте, ничего нового:

  * ручное отключение — файл ``state/proxy_off.flag`` через
    ``clientwrite.proxy_off`` / ``clientwrite.set_proxy_off`` (единственный
    источник истины: и сторож, и трей смотрят на него);
  * «обновить сейчас» — файл-триггер ``state/refresh.flag`` в каталоге
    состояния (рядом с ``stop.flag`` супервизора). Читает его супервизор
    вызовом :func:`consume_refresh_trigger`;
  * настройки — ``config.json`` пишется АТОМАРНО существующей функцией
    ``clientwrite._write_json`` (tmp + os.replace);
  * применение «РФ — напрямую» к ядру — ШТАТНЫЙ путь
    ``clientwrite.ensure_balancer(..., force=True)``: он сам перегенерирует
    конфиг ядра и перезапустит его (``write_balancer_config`` + ``restart_core``).

Системный прокси и правки реестра WinINET здесь НЕ выполняются.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as CFG
import i18n as I
import log
import tray_status as TS

CMD_TOGGLE_PROXY = 101
CMD_STATUS = 102
CMD_REFRESH = 103
CMD_OPEN_LOG = 104
CMD_EXIT = 105
CMD_FILTER_RU = 106
CMD_FILTER_CF = 107

REFRESH_FLAG = "refresh.flag"
PROXY_OFF_FLAG = "proxy_off.flag"
STALE_S = 90.0            # сколько секунд без heartbeat считаем «сторож молчит»


def refresh_trigger_path(cfg: dict) -> str:
    return os.path.join(cfg["paths"]["state_dir"], REFRESH_FLAG)


def proxy_off_flag_path(cfg: dict) -> str:
    return os.path.join(cfg["paths"]["state_dir"], PROXY_OFF_FLAG)


def consume_refresh_trigger(cfg: dict) -> bool:
    """Супервизор зовёт это, чтобы узнать о запросе «обновить серверы сейчас».

    Возвращает True (и снимает флаг), если пользователь нажал пункт меню.
    """
    p = refresh_trigger_path(cfg)
    if os.path.isfile(p):
        try:
            os.remove(p)
        except Exception:
            pass
        return True
    return False


class TrayActions:
    """Действия меню трея (без Win32) — хранит cfg, пишет лог и конфиг."""

    def __init__(self, cfg: dict, client: dict = None, on_refresh=None,
                 on_exit=None):
        self.cfg = cfg or {}
        self.client = client
        self.on_refresh = on_refresh
        self.on_exit = on_exit
        self.lg = log.get_logger()

    # ─────────────────────────────────────────────── состояние ───
    def proxy_off(self) -> bool:
        try:
            return os.path.isfile(proxy_off_flag_path(self.cfg))
        except Exception:
            return False

    def _status(self) -> dict:
        try:
            return TS.read_status(self.cfg) or {}
        except Exception:
            return {}

    def icon_state(self) -> str:
        """``ok`` | ``off`` | ``error`` для значка и подсказки."""
        if self.proxy_off():
            return "off"
        st = self._status()
        if not st:
            return "error"
        ts = st.get("ts")
        if ts is not None and (time.time() - float(ts)) > STALE_S:
            return "error"
        s = str(st.get("state") or "").lower()
        if s in ("down", "error"):
            return "error"
        if s == "off":
            return "off"
        if s in ("ok", "switch", "restoring"):
            return "ok"
        return "error"

    def tip(self) -> str:
        """Подсказка значка (<=63 символа — лимит Windows) с текущим состоянием."""
        icon = self.icon_state()
        base = I.tr("tray.tip." + icon)
        ru = I.tr("tray.hint.short_on") if self.ru_direct() else I.tr("tray.hint.short_off")
        cf = I.tr("tray.hint.short_on") if self.cloudflare() else I.tr("tray.hint.short_off")
        return f"{base} | RU:{ru} CF:{cf}"[:63]

    def status_text(self) -> str:
        icon = self.icon_state()
        st = self._status()
        tip = str(st.get("tip") or "").strip()
        lines = [I.tr("tray.status.header"), "",
                 I.tr("tray.status.state", state=I.tr("tray.state." + icon))]
        if tip:
            lines.append(tip)
        lines.append(f'{I.tr("tray.menu.filter_ru")}: '
                     f'{I.tr("tray.hint.on") if self.ru_direct() else I.tr("tray.hint.off")}')
        lines.append(f'{I.tr("tray.menu.filter_cf")}: '
                     f'{I.tr("tray.hint.on") if self.cloudflare() else I.tr("tray.hint.off")}')
        return "\n".join(lines)

    # ──────────────────────────────────────────────── фильтры ───
    def ru_direct(self) -> bool:
        return bool((self.cfg.get("watch") or {}).get("ru_direct", False))

    def cloudflare(self) -> bool:
        return bool((self.cfg.get("blacklist") or {}).get("cloudflare_nodes", True))

    def _config_path(self) -> str:
        return self.cfg.get("_config_path") or CFG.config_path()

    def _set_config(self, keys: list, value) -> bool:
        """Пишет ключ в config.json АТОМАРНО и обновляет in-memory копию cfg."""
        p = self._config_path()
        data = {}
        try:
            if p and os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
        except Exception as e:
            self.lg.warn(f"трей: чтение config.json ({p}): {e}")
            data = {}
        if not isinstance(data, dict):
            data = {}
        node = data
        for k in keys[:-1]:
            if not isinstance(node.get(k), dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = value
        try:
            import clientwrite as CW
            ok = bool(CW._write_json(p, data))
        except Exception as e:
            self.lg.warn(f"трей: запись config.json ({p}): {e}")
            ok = False
        node2 = self.cfg
        for k in keys[:-1]:
            if not isinstance(node2.get(k), dict):
                node2[k] = {}
            node2 = node2[k]
        node2[keys[-1]] = value
        return ok

    # ─────────────────────────────────────────────── команды ───
    def menu_labels(self) -> dict:
        on, off = I.tr("tray.hint.on"), I.tr("tray.hint.off")
        return {
            "toggle": I.tr("tray.menu.toggle_on") if self.proxy_off()
                      else I.tr("tray.menu.toggle_off"),
            "status": I.tr("tray.menu.status"),
            "refresh": I.tr("tray.menu.refresh"),
            "open_log": I.tr("tray.menu.open_log"),
            "exit": I.tr("tray.menu.exit"),
            "filters": I.tr("tray.menu.filters"),
            "filter_ru": f'{I.tr("tray.menu.filter_ru")} — {on if self.ru_direct() else off}',
            "filter_cf": f'{I.tr("tray.menu.filter_cf")} — {on if self.cloudflare() else off}',
        }

    def toggle_proxy(self) -> str:
        try:
            import clientwrite as CW
            client = self.client or CFG.find_client(self.cfg)
            if self.proxy_off():
                CW.set_proxy_off(self.cfg, False, client, why="tray")
                return I.tr("tray.msg.proxy_on")
            CW.set_proxy_off(self.cfg, True, client, why="tray")
            return I.tr("tray.msg.proxy_off")
        except Exception as e:
            self.lg.warn(f"трей: переключение прокси: {e}")
            return I.tr("error.generic", err=e)

    def request_refresh(self) -> str:
        """«Обновить серверы сейчас»: ставит триггер, который читает супервизор."""
        try:
            p = refresh_trigger_path(self.cfg)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "by": "tray"},
                                   ensure_ascii=False))
            self.lg.info("меню трея: запрошено обновление серверов (state/refresh.flag)")
            if callable(self.on_refresh):
                try:
                    self.on_refresh()
                except Exception as e:
                    self.lg.warn(f"трей on_refresh: {e}")
        except Exception as e:
            self.lg.warn(f"трей: refresh.flag: {e}")
        return I.tr("tray.msg.refresh")

    def toggle_ru_direct(self) -> str:
        """«РФ — напрямую»: меняет watch.ru_direct, перегенерирует ядро и перезапускает."""
        new = not self.ru_direct()
        self._set_config(["watch", "ru_direct"], new)
        self.lg.warn("меню трея: РФ — напрямую = %s — перегенерирую конфиг ядра "
                     "и перезапускаю ядро" % ("включено" if new else "выключено"))
        applied = self._apply_ru_direct()
        if applied:
            return I.tr("tray.msg.ru_on" if new else "tray.msg.ru_off")
        # ядро применить не удалось — настройка сохранена и применится со
        # следующего штатного цикла; НЕ рапортуем ложный успех.
        return I.tr("tray.msg.ru_on_pending" if new else "tray.msg.ru_off_pending")

    def _apply_ru_direct(self) -> bool:
        """Штатный путь применения: ensure_balancer сам пишет конфиг и перезапускает ядро.

        True — конфиг ядра перегенерирован и ядро перезапущено; False — в любом
        сбое (ядро/связь недоступны, ensure_balancer вернул ложь/исключение).
        """
        try:
            import clientwrite as CW
            client = self.client or CFG.find_client(self.cfg)
            n = int((self.cfg.get("watch") or {}).get("balancer_pool_n", 10) or 10)
            ok = bool(CW.ensure_balancer(client, self.cfg, n=n, force=True))
            self.lg.info(f"меню трея: ядро применено после смены РФ-напрямую (ok={ok})")
            return ok
        except Exception as e:
            # связь/ядро может быть недоступно — настройка всё равно сохранена и
            # применится со следующего штатного цикла
            self.lg.warn(f"меню трея: применение РФ-напрямую: {e}")
            return False

    def toggle_cloudflare(self) -> str:
        """«Cloudflare — обход»: меняет blacklist.cloudflare_nodes (со следующего подбора)."""
        new = not self.cloudflare()
        self._set_config(["blacklist", "cloudflare_nodes"], new)
        self.lg.warn("меню трея: Cloudflare — обход = %s — применится со следующего "
                     "цикла подбора (принудительный цикл не запускаю)"
                     % ("включено" if new else "выключено"))
        return I.tr("tray.msg.cf_on" if new else "tray.msg.cf_off")

    # ─────────────────────────────────────────── лог / выход ───
    def log_path(self) -> str:
        try:
            return log.get_logger().path
        except Exception:
            return os.path.join(self.cfg.get("paths", {}).get("log_dir", ""), "main.log")

    def open_log(self) -> str:
        p = self.log_path()
        if not p or not os.path.isfile(p):
            return I.tr("tray.msg.no_log")
        try:
            os.startfile(p)                     # noqa: S606 (Windows-only, без консоли)
        except Exception as e:
            return I.tr("error.generic", err=e)
        return ""

    def request_exit(self) -> str:
        if callable(self.on_exit):
            try:
                self.on_exit()
            except Exception as e:
                self.lg.warn(f"трей on_exit: {e}")
        return ""
