# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""i18n: Русский + English — ПОЛНЫЙ каталог пользовательских строк (GPL-3.0).

Продукт двуязычный. Здесь собраны ВСЕ строки, которые видит пользователь:
пункты меню трея, подсказки значка, заголовки/тело окна состояния, сообщения
установщика, основные ошибки и строки CLI. Строки внутреннего уровня (только
лог для диагностики) здесь НЕ переводятся — они и так дублируются в лог.

Язык берётся из ``ui.lang`` в config.json ("ru" | "en" | "auto"). ``auto`` (и
пустое значение) — по локали Windows; на не-Windows — по переменным LANG/LC_ALL.

Использование::

    import i18n
    i18n.set_lang("en")
    print(i18n.t("status.title"))         # "Status"
    print(i18n.tr("tray.state.ok"))       # "running"

Проверка полноты каталога (обе локали непусты и не теряют ключи):
    i18n.check_complete()   -> {"ru": [...], "en": [...], "missing": [...]}
"""
from __future__ import annotations

import os

RU = "ru"
EN = "en"

_LANG = RU

# key -> {ru, en}
_STRINGS = {
    "app.name": {"ru": "FOREST's Proxy Auto-updater", "en": "FOREST's Proxy Auto-updater"},
    "app.tagline": {"ru": "Автоматический подбор и переключение прокси-серверов",
                    "en": "Automatic selection and switching of proxy servers"},
    "cli.usage_hint": {"ru": "Запустите с --help для списка команд.",
                       "en": "Run with --help for the list of commands."},
    "status.title": {"ru": "Статус", "en": "Status"},
    "status.mode": {"ru": "Режим", "en": "Mode"},
    "status.core": {"ru": "Ядро Xray", "en": "Xray core"},
    "status.core_missing": {"ru": "не найдено (положите bin\\xray\\xray.exe рядом с программой)",
                            "en": "not found (place bin\\xray\\xray.exe next to the program)"},
    "status.core_found": {"ru": "найдено", "en": "found"},
    "status.pool": {"ru": "Серверов в пуле", "en": "Servers in pool"},
    "status.proxy": {"ru": "Системный прокси", "en": "System proxy"},
    "status.proxy_on": {"ru": "включён на", "en": "enabled on"},
    "status.proxy_off": {"ru": "выключен", "en": "disabled"},
    "status.link": {"ru": "Связь", "en": "Connectivity"},
    "status.link_ok": {"ru": "есть", "en": "ok"},
    "status.link_down": {"ru": "нет", "en": "down"},
    "status.core_running": {"ru": "Ядро запущено (pid)", "en": "Core running (pid)"},
    "status.core_stopped": {"ru": "Ядро не запущено", "en": "Core not running"},
    "install.title": {"ru": "Установка", "en": "Installation"},
    "install.done": {"ru": "Установка завершена.", "en": "Installation complete."},
    "install.uninstalled": {"ru": "Удаление завершено.", "en": "Uninstall complete."},
    "install.proxy_note": {"ru": "Системный прокси не изменялся на этом шаге.",
                           "en": "The system proxy was not modified at this step."},
    "selftest.passed": {"ru": "ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ", "en": "ALL CHECKS PASSED"},
    "selftest.failed": {"ru": "ПРОВАЛЕНО", "en": "FAILED"},
    "firstrun.created": {"ru": "Конфиг не найден — создан из config.example.json:",
                         "en": "No config found — created from config.example.json:"},

    # ───────────────────────────────── установщик (дополнение) ───
    "install.shortcut": {"ru": "Ярлык создан", "en": "Shortcut created"},
    "install.autostart_on": {"ru": "Автозапуск включён", "en": "Autostart enabled"},
    "install.autostart_off": {"ru": "Автозапуск убран", "en": "Autostart removed"},
    "install.core_missing": {"ru": "Ядро xray не найдено — положите bin\\xray\\xray.exe рядом с программой.",
                             "en": "Xray core not found — place bin\\xray\\xray.exe next to the program."},
    "install.done_hint": {"ru": "Готово. Запуск с ключом --run (значок в трее).",
                          "en": "Done. Start with --run (tray icon)."},

    # ─────────────────────────────────────── состояния значка ───
    "tray.state.ok": {"ru": "работает", "en": "running"},
    "tray.state.off": {"ru": "выключен вручную", "en": "manually disabled"},
    "tray.state.error": {"ru": "нет связи", "en": "no connectivity"},

    # ──────────────────────────────────────── подсказки значка ───
    "tray.tip.ok": {"ru": "FOREST: прокси работает", "en": "FOREST: proxy is running"},
    "tray.tip.off": {"ru": "FOREST: прокси выключен вручную",
                     "en": "FOREST: proxy manually disabled"},
    "tray.tip.error": {"ru": "FOREST: нет связи", "en": "FOREST: no connectivity"},
    "tray.tip.unknown": {"ru": "FOREST: нет данных о состоянии",
                         "en": "FOREST: no status data"},

    # ───────────────────────────────────────────── меню трея ───
    "tray.menu.toggle_off": {"ru": "Выключить прокси вручную",
                             "en": "Disable proxy (manual)"},
    "tray.menu.toggle_on": {"ru": "Включить прокси вручную",
                            "en": "Enable proxy (manual)"},
    "tray.menu.status": {"ru": "Состояние", "en": "Status"},
    "tray.menu.refresh": {"ru": "Обновить серверы сейчас",
                          "en": "Update servers now"},
    "tray.menu.open_log": {"ru": "Открыть лог", "en": "Open log"},
    "tray.menu.exit": {"ru": "Выход", "en": "Exit"},
    "tray.menu.filters": {"ru": "Фильтры", "en": "Filters"},
    "tray.menu.filter_ru": {"ru": "РФ — напрямую", "en": "RU direct"},
    "tray.menu.filter_cf": {"ru": "Cloudflare — обход", "en": "Cloudflare bypass"},

    # ───────────────────────────────────── подсказки о состоянии ───
    "tray.hint.on": {"ru": "включено", "en": "on"},
    "tray.hint.off": {"ru": "выключено", "en": "off"},
    "tray.hint.short_on": {"ru": "вкл", "en": "on"},
    "tray.hint.short_off": {"ru": "выкл", "en": "off"},

    # ────────────────────────────────────────── окно «Состояние» ───
    "tray.status.header": {"ru": "FOREST's Proxy Auto-updater — состояние",
                           "en": "FOREST's Proxy Auto-updater — status"},
    "tray.status.state": {"ru": "Состояние: {state}", "en": "State: {state}"},

    # ─────────────────────────────── сообщения меню (в лог/итог) ───
    "tray.msg.proxy_on": {"ru": "Прокси включён вручную — связь поднимается.",
                          "en": "Proxy enabled manually — bringing the link up."},
    "tray.msg.proxy_off": {"ru": "Прокси выключен вручную — автоподъём остановлен.",
                           "en": "Proxy disabled manually — auto-restore stopped."},
    "tray.msg.refresh": {"ru": "Запрошено обновление серверов.",
                         "en": "Server update requested."},
    "tray.msg.ru_on": {"ru": "РФ — напрямую: включено. Ядро перегенерировано и перезапущено.",
                       "en": "RU direct: on. Core config regenerated and restarted."},
    "tray.msg.ru_off": {"ru": "РФ — напрямую: выключено. Ядро перегенерировано и перезапущено.",
                        "en": "RU direct: off. Core config regenerated and restarted."},
    "tray.msg.ru_on_pending": {"ru": "РФ — напрямую: включено. Настройка сохранена и применится "
                                     "со следующего штатного цикла.",
                               "en": "RU direct: on. The setting is saved and applies from the "
                                     "next scheduled cycle."},
    "tray.msg.ru_off_pending": {"ru": "РФ — напрямую: выключено. Настройка сохранена и применится "
                                      "со следующего штатного цикла.",
                                "en": "RU direct: off. The setting is saved and applies from the "
                                      "next scheduled cycle."},
    "tray.msg.cf_on": {"ru": "Cloudflare — обход: включено. Применится со следующего подбора.",
                       "en": "Cloudflare bypass: on. Applies from the next selection."},
    "tray.msg.cf_off": {"ru": "Cloudflare — обход: выключено. Применится со следующего подбора.",
                        "en": "Cloudflare bypass: off. Applies from the next selection."},
    "tray.msg.no_log": {"ru": "Файл лога ещё не создан.", "en": "The log file does not exist yet."},

    # ───────────────────────────────────────────── ошибки ───
    "error.no_core": {"ru": "Ядро xray не найдено. Положите bin\\xray\\xray.exe рядом с программой "
                            "или установите xray в PATH.",
                      "en": "Xray core not found. Place bin\\xray\\xray.exe next to the program "
                            "or install xray into PATH."},
    "error.no_config": {"ru": "Конфиг не найден. Запустите установку (--install).",
                        "en": "Config not found. Run the installer (--install)."},
    "error.network": {"ru": "Нет сети или серверы недоступны.",
                      "en": "No network or servers are unreachable."},
    "error.proxy_change": {"ru": "Не удалось изменить системный прокси.",
                           "en": "Could not change the system proxy."},
    "error.generic": {"ru": "Ошибка: {err}", "en": "Error: {err}"},
}


def _windows_ui_lang() -> str:
    """Язык интерфейса Windows через GetUserDefaultUILanguage (только Windows)."""
    try:
        import ctypes
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        primary = langid & 0x3FF           # LANGID -> primary language id
        return EN if primary == 0x09 else RU    # 0x09 = English, иначе русский
    except Exception:
        return ""


def detect_lang(cfg: dict = None) -> str:
    """Язык из конфига (``ui.lang``), иначе по локали Windows, иначе ru.

    Значения ``ui.lang``: ``ru`` | ``en`` | ``auto`` (auto и пустое — по локали).
    """
    if isinstance(cfg, dict):
        lang = str((cfg.get("ui") or {}).get("lang") or "").strip().lower()
        if lang in (RU, EN):
            return lang
        # "auto" или "" -> автоопределение по локали системы
    if os.name == "nt":
        w = _windows_ui_lang()
        if w:
            return w
    loc = (os.environ.get("LANG") or os.environ.get("LC_ALL") or "").lower()
    if loc.startswith("en"):
        return EN
    return RU


def set_lang(lang: str) -> str:
    global _LANG
    _LANG = lang if lang in (RU, EN) else RU
    return _LANG


def get_lang() -> str:
    return _LANG


def t(key: str, **fmt) -> str:
    """Строка по ключу для текущего языка (с подстановкой ``{имя}``)."""
    entry = _STRINGS.get(key)
    if not entry:
        return key
    s = entry.get(_LANG) or entry.get(RU) or key
    if fmt:
        try:
            return s.format(**fmt)
        except Exception:
            return s
    return s


# короткий алиас (используется модулями трея)
tr = t


def all_keys() -> list:
    return sorted(_STRINGS)


def check_complete() -> dict:
    """Ключи с пустыми переводами (пустые списки = каталог полный)."""
    empty_ru = [k for k, v in _STRINGS.items() if not str(v.get("ru") or "").strip()]
    empty_en = [k for k, v in _STRINGS.items() if not str(v.get("en") or "").strip()]
    missing = sorted(set(empty_ru) | set(empty_en))
    return {"ru": sorted(empty_ru), "en": sorted(empty_en), "missing": missing}
