# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
"""Единый источник палитр: светлая и тёмная темы.

Тема нужна там, где мы рисуем сами: карточка уведомления, значок трея и цвет
состояния внутри него. Системная тема определяется автоматически:

* Windows — реестр ``HKCU\\...\\Themes\\Personalize`` → ``AppsUseLightTheme``;
* Linux   — ``gsettings get org.gnome.desktop.interface color-scheme``, затем
  ``GTK_THEME`` / ``COLORFGBG`` / ``FOREST_THEME`` как запасные пути.

Пользователь может переопределить выбор: ``ui.theme`` = ``auto`` | ``light`` |
``dark`` (и тумблер в меню трея).

Цвета состояний подобраны так, чтобы читаться и на светлой, и на тёмной панели
задач; в конце модуля есть ``contrast()`` и проверка ``state_contrasts()``,
которой подтверждается контраст по WCAG.
"""

from __future__ import annotations

import os
import sys

THEMES = ("light", "dark")

# ── палитры ─────────────────────────────────────────────────────────────────
# card_* — карточка уведомления; tray_* — значок трея; state_* — цвет состояния.
PALETTES = {
    "dark": {
        "card_bg": (32, 33, 36),
        "card_border": (60, 64, 67),
        "shadow": (0, 0, 0),
        "title": (241, 243, 244),
        "body": (189, 193, 198),
        "accent": (66, 133, 244),
        "state_ok": (57, 194, 109),
        "state_off": (150, 152, 160),
        "state_error": (229, 72, 77),
        "state_busy": (240, 196, 44),
        "tray_rim": (18, 18, 18),
        "tray_none": (120, 122, 128),
    },
    "light": {
        "card_bg": (250, 250, 250),
        "card_border": (200, 204, 208),
        "shadow": (60, 60, 60),
        "title": (24, 26, 28),
        "body": (70, 74, 78),
        "accent": (26, 115, 232),
        "state_ok": (24, 128, 56),
        "state_off": (108, 110, 116),
        "state_error": (193, 34, 33),
        "state_busy": (176, 122, 0),
        "tray_rim": (245, 246, 248),
        "tray_none": (140, 142, 148),
    },
}

# Панель задач: светлая тема Windows — светлая панель, тёмная — тёмная.
PANEL_BG = {"light": (243, 243, 243), "dark": (32, 32, 32)}

STATE_KEYS = {
    "ok": "state_ok",
    "off": "state_off",
    "error": "state_error",
    "busy": "state_busy",
    "info": "accent",
    # состояния эталона (v2ray-auto-updater): переключение, «нет данных»,
    # восстановление связи — цвета те же, что были у прежнего значка
    "switch": "state_busy",
    "noanswer": "state_busy",
    "restoring": "accent",
    "down": "state_error",
}


def contrast(rgb1, rgb2) -> float:
    """Коэффициент контраста WCAG (1..21)."""
    def lum(c):
        def ch(v):
            v = v / 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])
    a, b = lum(rgb1), lum(rgb2)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def relative_luminance(rgb) -> float:
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


# ── определение системной темы ──────────────────────────────────────────────
def _detect_windows() -> str:
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion"
                           r"\Themes\Personalize")
        try:
            v, _t = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return "light" if int(v) == 1 else "dark"
        finally:
            winreg.CloseKey(k)
    except Exception:
        return "dark"


def _detect_linux() -> str:
    env = os.environ.get("FOREST_THEME", "").lower()
    if env in THEMES:
        return env
    scheme = ""
    try:
        import subprocess
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface",
                            "color-scheme"], capture_output=True, text=True,
                           timeout=3)
        scheme = (r.stdout or "").strip().strip("'").lower()
    except Exception:
        scheme = ""
    if "dark" in scheme:
        return "dark"
    if "light" in scheme or "default" in scheme:
        return "light"
    for var in ("GTK_THEME", "QT_STYLE_OVERRIDE"):
        v = os.environ.get(var, "").lower()
        if "dark" in v:
            return "dark"
        if "light" in v:
            return "light"
    fgbg = os.environ.get("COLORFGBG", "")
    if fgbg:
        try:
            bg = int(fgbg.split(";")[-1])
            return "light" if bg >= 8 else "dark"
        except Exception:
            pass
    return "dark"


def detect() -> str:
    """Системная тема: 'light' | 'dark' (никогда не падает)."""
    try:
        if sys.platform.startswith("win"):
            return _detect_windows()
        return _detect_linux()
    except Exception:
        return "dark"


def choice(cfg: dict = None) -> str:
    """Тема по настройке: ``ui.theme`` = auto|light|dark."""
    try:
        v = str(((cfg or {}).get("ui") or {}).get("theme", "auto") or "auto").lower()
    except Exception:
        v = "auto"
    if v in THEMES:
        return v
    return detect()


def palette(cfg: dict = None) -> dict:
    return dict(PALETTES.get(choice(cfg), PALETTES["dark"]))


def state_color(cfg: dict, state: str):
    p = palette(cfg)
    return p.get(STATE_KEYS.get(state, "accent"), p["accent"])


def tray_ring(cfg: dict):
    p = palette(cfg)
    return p.get("tray_none", (120, 122, 128))


def state_contrasts() -> list:
    """Контраст цвета состояния к панели задач (для отчёта и тестов)."""
    out = []
    for t in THEMES:
        p = PALETTES[t]
        bg = PANEL_BG[t]
        for st, key in (("ok", "state_ok"), ("off", "state_off"),
                        ("error", "state_error"), ("busy", "state_busy")):
            out.append({"theme": t, "state": st, "color": p[key], "panel": bg,
                        "contrast": round(contrast(p[key], bg), 2)})
    return out


def min_contrast() -> float:
    return min(c["contrast"] for c in state_contrasts())


def set_windows_theme(value: str) -> bool:
    """Служебное: переключить AppsUseLightTheme (для проверок обеих тем)."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion"
                           r"\Themes\Personalize", 0, winreg.KEY_SET_VALUE)
        try:
            winreg.SetValueEx(k, "AppsUseLightTheme", 0, winreg.REG_DWORD,
                              1 if value == "light" else 0)
            return True
        finally:
            winreg.CloseKey(k)
    except Exception:
        return False


# ── Linux: уведомления через системную службу ───────────────────────────────
def linux_color_scheme_arg() -> str:
    """Что подставить в gsettings, если пользователь выбрал тему вручную."""
    return "prefer-dark" if choice() == "dark" else "prefer-light"
