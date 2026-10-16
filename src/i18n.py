"""Минимальный i18n: Русский + English (GPL-3.0).

Продукт двуязычный. Здесь — фундамент: словарь строк, выбор языка из
`ui.lang` в config.json либо по локали системы. Полное покрытие всех
сообщений — задача следующих этапов; сейчас переведены строки CLI
(статус, установка, самотест, баннеры), а сообщения длинных циклов пока
на русском (они и так дублируются в лог для диагностики).

Использование:
    import i18n
    i18n.set_lang("en")
    print(i18n.t("status.title"))
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
}


def detect_lang(cfg: dict = None) -> str:
    """Язык из конфига (ui.lang), иначе из локали системы. По умолчанию ru."""
    if isinstance(cfg, dict):
        lang = str((cfg.get("ui") or {}).get("lang") or "").strip().lower()
        if lang in (RU, EN):
            return lang
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
