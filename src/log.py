"""Логирование: файл в utf-8 + безопасный вывод в консоль (cp1251-safe).

FOREST's Proxy Auto-updater (GPL-3.0).
Логи по умолчанию пишутся в каталог программы
(%LOCALAPPDATA%\\ForestProxyUpdater\\logs), а не рядом с кодом — чтобы
установленная программа не зависела от прав на каталог исходников и не
засоряла репозиторий.
"""
import os
import sys
import datetime


_BASE = os.path.dirname(os.path.abspath(__file__))


def default_log_dir() -> str:
    """Каталог логов по умолчанию: %LOCALAPPDATA%\\ForestProxyUpdater\\logs.

    Переопределяется переменной окружения FOREST_ROOT (используется тестами и
    установщиком, чтобы писать в отдельный каталог состояния).
    """
    root = os.environ.get("FOREST_ROOT")
    if not root:
        la = os.environ.get("LOCALAPPDATA")
        if not la:
            la = os.path.join(os.path.expanduser("~"), ".local", "share")
        root = os.path.join(la, "ForestProxyUpdater")
    return os.path.join(root, "logs")


def _resolve_dir(log_dir: str) -> str:
    r"""Абсолютный каталог логов: относительный путь считается от каталога кода.

    Иначе при запуске из планировщика (cwd = C:\Windows\System32) путь "logs"
    упирался в PermissionError и процесс падал до первой строки лога.
    """
    if not log_dir:
        return default_log_dir()
    d = log_dir
    if not os.path.isabs(d):
        d = os.path.join(_BASE, d)
    return d


class Logger:
    def __init__(self, log_dir: str = None):
        self.dir = _resolve_dir(log_dir)
        candidates = [self.dir]
        # страховка: каталог кода, затем временный — лог важнее места
        candidates.append(os.path.join(_BASE, "logs"))
        tmp = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or _BASE
        candidates.append(os.path.join(tmp, "ForestProxyUpdater", "logs"))
        self.path = os.path.join(self.dir, "main.log")
        self._fh = None
        for c in candidates:
            try:
                os.makedirs(c, exist_ok=True)
                fh = open(os.path.join(c, "main.log"), "a", encoding="utf-8")
            except Exception:
                continue
            self.dir, self.path, self._fh = c, os.path.join(c, "main.log"), fh
            break

    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        try:
            print(line, flush=True)
        except Exception:
            # cp1251 fallback для unattended stdout
            enc = sys.stdout.encoding or "utf-8"
            try:
                print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)
            except Exception:
                pass
        try:
            if self._fh is not None:
                self._fh.write(line + "\n")
                self._fh.flush()
        except Exception:
            pass

    def info(self, msg: str):
        self.log("INFO  " + msg)

    def warn(self, msg: str):
        self.log("WARN  " + msg)

    def error(self, msg: str):
        self.log("ERROR " + msg)

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass


_instance = None


def get_logger(log_dir: str = None) -> Logger:
    global _instance
    if _instance is None:
        _instance = Logger(log_dir)
    return _instance


def reset_logger(log_dir: str = None):
    """Пересоздать логгер (нужно тестам и смене каталога состояния)."""
    global _instance
    try:
        if _instance is not None:
            _instance.close()
    except Exception:
        pass
    _instance = Logger(log_dir)
    return _instance
