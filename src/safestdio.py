# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Безопасный стандартный вывод и глобальная защита от необработанных исключений.

Зачем это здесь
---------------
Оконная (windowed) сборка PyInstaller НЕ имеет консоли, а её «консольная
кодировка» на Windows — cp1251. Достаточно было одного символа вне cp1251
(например «✓», U+2713) в ``print()`` — и ``UnicodeEncodeError`` вылетал наружу,
а PyInstaller показывал на рабочем столе **модальное окно** «Unhandled exception
in script». Программа при этом не ломалась (ядро живёт отдельно), но окно —
прямое нарушение правила «никаких видимых окон».

Три уровня защиты, все без сторонних зависимостей:

1. :func:`safe_stdio` — ``sys.stdout``/``sys.stderr`` переводятся в режим
   ``utf-8`` + ``errors="replace"`` (а если потока нет вовсе — подставляется
   заглушка). Печать после этого НЕ может уронить программу;
2. :func:`say` — печать в stdout ТОЛЬКО ASCII (не-ASCII заменяется на ``?``).
   Человекочитаемые результаты пишутся в UTF-8-файлы (:func:`write_report`);
3. :func:`guarded` + :func:`install_excepthook` — ЛЮБОЕ необработанное исключение
   пишется трассировкой в файл журнала, процесс завершается ненулевым кодом.
   Модальных окон не бывает ни при каких обстоятельствах.
"""
from __future__ import annotations

import os
import sys
import time
import traceback

__all__ = ["safe_stdio", "say", "log_dir", "write_report", "crash_log",
           "install_excepthook", "guarded"]


class _NullWriter:
    """Заглушка потока: печать уходит в никуда (консоли нет — это нормально)."""

    encoding = "utf-8"
    errors = "replace"

    def write(self, s):
        try:
            return len(s)
        except Exception:
            return 0

    def flush(self):
        pass

    def isatty(self):
        return False

    def writable(self):
        return True

    def readable(self):
        return False

    def close(self):
        pass


_ORIG_ENCODING = "ascii"      # кодировка stdout ДО перевода в utf-8


def safe_stdio() -> None:
    """Переводит stdout/stderr в безопасный режим. Никогда не бросает.

    Кодировка, которая была ДО перевода, запоминается в :data:`_ORIG_ENCODING`:
    по ней :func:`say` решает, можно ли вообще печатать не-ASCII (на Linux-терминале
    в UTF-8 — да; на оконной сборке Windows с cp1251 — нет, там будет ``?``).
    """
    global _ORIG_ENCODING
    for name in ("stdout", "stderr"):
        try:
            st = getattr(sys, name, None)
            if st is None:
                setattr(sys, name, _NullWriter())
                continue
            if name == "stdout":
                try:
                    _ORIG_ENCODING = getattr(st, "encoding", None) or "ascii"
                except Exception:
                    _ORIG_ENCODING = "ascii"
            rc = getattr(st, "reconfigure", None)
            if callable(rc):
                rc(encoding="utf-8", errors="replace")
        except Exception:
            try:
                setattr(sys, name, _NullWriter())
            except Exception:
                pass


def say(text="") -> None:
    """Печать в stdout ТОЛЬКО ASCII. НИКОГДА не бросает исключения.

    В собранном приложении печатать не-ASCII в стандартный вывод нельзя: у
    оконной сборки консоли нет, а её «кодировка» на Windows — cp1251, и символ
    вне cp1251 (например «✓») давал UnicodeEncodeError с МОДАЛЬНЫМ ОКНОМ
    PyInstaller на рабочем столе. Здесь не-ASCII заменяется на ``?`` — упасть
    невозможно в принципе.

    Человекочитаемый текст (русский) пишется в UTF-8-ФАЙЛЫ:
    :func:`write_report`, ``state/status.txt``, ``state/ui_selftest.txt``,
    журнал программы.
    """
    try:
        line = str(text).encode("ascii", "replace").decode("ascii")
        out = getattr(sys, "stdout", None)
        if out is None:
            return
        out.write(line + "\n")
        out.flush()
    except Exception:
        pass


def log_dir() -> str:
    """Каталог журналов программы — без импорта config (он может не подняться).

    Windows: ``%LOCALAPPDATA%\\ForestProxyUpdater\\logs`` (или ``<FOREST_ROOT>
    \\logs``); POSIX: ``$XDG_STATE_HOME/forest-proxy-updater/logs``.
    """
    try:
        root = os.environ.get("FOREST_ROOT") or ""
        if root:
            return os.path.join(os.path.abspath(root), "logs")
        if os.name == "nt":
            la = (os.environ.get("LOCALAPPDATA")
                  or os.path.join(os.path.expanduser("~"), ".local", "share"))
            return os.path.join(la, "ForestProxyUpdater", "logs")
        xdg = os.environ.get("XDG_STATE_HOME")
        if not xdg or not os.path.isabs(xdg):
            xdg = os.path.join(os.path.expanduser("~"), ".local", "state")
        return os.path.join(xdg, "forest-proxy-updater", "logs")
    except Exception:
        import tempfile
        return tempfile.gettempdir()


def write_report(name: str, text: str) -> str:
    """Пишет отчёт в UTF-8 рядом с журналами. -> путь ('' — не удалось)."""
    for d in (log_dir(),):
        try:
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(text if text.endswith("\n") else text + "\n")
            return p
        except Exception:
            continue
    return ""


def crash_log(where: str, exc_text: str) -> str:
    """Пишет трассировку в файл (UTF-8) и в основной журнал. -> путь."""
    body = (f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} {where}: "
            f"НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ ===\n{exc_text}")
    p = write_report("crash.log", body)
    try:
        import log as LG
        LG.get_logger().error(f"{where}: необработанное исключение:\n{exc_text}")
    except Exception:
        pass
    # страховка: если журнал программы недоступен, пишем в temp
    if not p:
        try:
            import tempfile
            p = os.path.join(tempfile.gettempdir(), "forest-crash.log")
            with open(p, "a", encoding="utf-8") as f:
                f.write(body + "\n")
        except Exception:
            p = ""
    return p


def install_excepthook(where: str = "app") -> None:
    """Глобальный перехват: пишем трассировку в файл, окна не показываем."""

    def _hook(exc_type, exc, tb):
        try:
            crash_log(where, "".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        # никаких модальных окон: тихо завершаемся
        try:
            sys.exit(70)
        except SystemExit:
            raise

    try:
        sys.excepthook = _hook
    except Exception:
        pass
    try:
        import threading

        def _thook(args):
            try:
                crash_log(where, "".join(traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback)))
            except Exception:
                pass

        threading.excepthook = _thook
    except Exception:
        pass


def guarded(fn, where: str = "app", argv=None) -> int:
    """Обёртка вокруг точки входа: исключение -> журнал + ненулевой код.

    Модальное окно PyInstaller показывается только при НЕОБРАБОТАННОМ
    исключении из скрипта; здесь оно всегда обработано.
    """
    safe_stdio()
    install_excepthook(where)
    try:
        rc = fn(argv) if argv is not None else fn()
        return int(rc or 0)
    except SystemExit:
        raise
    except BaseException:
        try:
            crash_log(where, traceback.format_exc())
        except Exception:
            pass
        return 70
