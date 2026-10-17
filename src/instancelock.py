# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Настоящий одноэкземплярный замок: эксклюзивная блокировка файла на всё время жизни.

Зачем это отдельным модулем
---------------------------
Раньше «защита от второго экземпляра» была файлом-маркером с PID внутри:
решение «супервизор уже работает?» принималось по эвристике — жив ли записанный
PID и есть ли в списке процессов подходящая командная строка. Эвристика врёт в
обе стороны, и это проверено на живой машине:

* два одновременных запуска видели в списке процессов ДРУГ ДРУГА и оба
  отказывались стартовать — не выживал никто;
* после ручного снятия процесса маркер с мёртвым PID «забирался» новым
  запуском, а старый экземпляр продолжал работать — получались ДВЕ пары
  (две программы и два помощника, два значка в трее).

Здесь вместо эвристики — блокировка, которую держит САМА операционная система:

  Windows: ``msvcrt.locking(fd, LK_NBLCK, 1)`` (LockFile);
  POSIX:   ``fcntl.lockf(fd, LOCK_EX | LOCK_NB)``.

Замок неблокирующий: вторая попытка сразу получает отказ. Главное свойство —
замок снимает ядро ОС при завершении процесса (в том числе при аварийном
убийстве), поэтому «мёртвых замков» не бывает и устаревшие PID не мешают.
Дополнительно в файл пишется JSON с PID/путями — но ТОЛЬКО для диагностики:
решения принимаются по замку, а не по содержимому.

Правило использования (единое для всей программы):

    живой замок = экземпляр уже работает -> второй НЕ поднимаем и тихо выходим.

Модуль без внешних зависимостей, работает и на Windows, и на Linux.
"""
from __future__ import annotations

import json
import os
import time

IS_WIN = os.name == "nt"

try:
    if IS_WIN:
        import msvcrt
    else:
        import fcntl
except Exception:                                     # pragma: no cover
    msvcrt = None
    fcntl = None

# Байт-«якорь» замка. Windows не даёт писать в заблокированный байт даже
# владельцу, поэтому замок берётся далеко за данными: JSON диагностики
# пишется в начало файла и по размеру до якоря не дотягивается.
ANCHOR = 8192
INFO_MAX = 4096


def _open(path: str) -> int:
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return os.open(path, flags, 0o644)


def _try_lock(fd: int) -> bool:
    """Пытается взять эксклюзивный замок на дескрипторе. False — занято.

    Любая ошибка платформенного вызова трактуется как «занято»: лучше не
    поднять второй экземпляр, чем поднять его поверх живого.
    """
    try:
        if IS_WIN:
            if msvcrt is None:
                return False
            os.lseek(fd, ANCHOR, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        if fcntl is None:
            return False
        # flock (BSD-замок) — замок на ОТКРЫТОМ ОПИСАНИИ файла: новая попытка
        # даже внутри того же процесса видит занятость, как в Windows.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _unlock(fd: int) -> None:
    try:
        if IS_WIN:
            if msvcrt is None:
                return
            os.lseek(fd, ANCHOR, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        elif fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except Exception:
        pass


def read_info(path: str) -> dict:
    """Содержимое файла замка (диагностика: pid/ts/exe/root/argv). {} — нет/битый."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


class InstanceLock:
    """Эксклюзивный замок файла, удерживаемый всё время жизни процесса.

    Типичное использование::

        lock = InstanceLock(path)
        if not lock.acquire({"pid": os.getpid()}):
            return 0                     # экземпляр уже работает — молча выходим
        ...                              # работаем; замок живёт сколько живём мы
        lock.release()                   # (необязательно: ОС снимет сама)

    ``acquire`` идемпотентен: повторный вызов в том же объекте — True.
    """

    def __init__(self, path: str, tag: str = ""):
        self.path = path or ""
        self.tag = tag
        self._fd = None
        self._degraded = False

    # ── состояние ───────────────────────────────────────────────────────
    @property
    def held(self) -> bool:
        return self._fd is not None

    @property
    def degraded(self) -> bool:
        """True — замок не работает (нет файла/ФС); работаем по старой логике."""
        return self._degraded

    def read_info(self) -> dict:
        return read_info(self.path)

    # ── захват/освобождение ─────────────────────────────────────────────
    def acquire(self, info: dict = None) -> bool:
        """Захватить замок неблокирующе. True — мы владелец (или деградация)."""
        if self._fd is not None:
            return True
        if not self.path:
            self._degraded = True
            return True
        try:
            fd = _open(self.path)
        except Exception:
            # Файл замка недоступен (нет прав/каталога) — не мешаем программе
            # работать: считаем себя владельцем, но помечаем деградацию.
            self._degraded = True
            return True
        if not _try_lock(fd):
            try:
                os.close(fd)
            except Exception:
                pass
            return False
        self._fd = fd
        if info is not None:
            self.write_info(info)
        return True

    def write_info(self, info: dict) -> None:
        """Пишет JSON с данными владельца (только владелец; для диагностики)."""
        if self._fd is None:
            return
        try:
            body = json.dumps(info, ensure_ascii=False).encode("utf-8")[:INFO_MAX - 1]
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, body)
            os.ftruncate(self._fd, len(body))
            os.lseek(self._fd, 0, os.SEEK_SET)
        except Exception:
            pass

    def release(self, unlink: bool = True) -> None:
        """Снять замок и (по умолчанию) убрать файл. Безопасно вызывать всегда.

        Файл убирается ТОЛЬКО если мы действительно владели замком: удалять
        чужой файл замка нельзя (иначе у второго владельца останется замок на
        уже удалённом файле, а новый файл никто не держит — эксклюзивность
        сломается). Обычно файл замка вообще не удаляют: ОС снимает сам замок
        при завершении процесса.
        """
        fd = self._fd
        was_held = fd is not None
        self._fd = None
        if fd is not None:
            _unlock(fd)
            try:
                os.close(fd)
            except Exception:
                pass
        if unlink and was_held and self.path:
            try:
                os.unlink(self.path)
            except Exception:
                pass

    # ── контекстный менеджер (для коротких замков вроде «идёт --ensure») ──
    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_exc):
        self.release()
        return False


def probe(path: str) -> dict:
    """Кто-то держит замок прямо сейчас?

    -> {"held": bool, "info": {...}, "degraded": bool}

    Проверка честная: открываем ВТОРОЙ дескриптор и пробуем взять тот же замок.
    Удалось — никто не держит (сразу отпускаем и закрываем). Не удалось — держат.
    """
    out = {"held": False, "info": {}, "degraded": False}
    if not path:
        out["degraded"] = True
        return out
    try:
        fd = _open(path)
    except Exception:
        out["degraded"] = True
        return out
    try:
        if _try_lock(fd):
            _unlock(fd)
            out["held"] = False
        else:
            out["held"] = True
    finally:
        try:
            os.close(fd)
        except Exception:
            pass
    if out["held"]:
        out["info"] = read_info(path)
    return out


def held(path: str) -> bool:
    """Короткая форма probe(): True — замок занят живым экземпляром."""
    return bool(probe(path).get("held"))


def holder_pid(path: str) -> int:
    """PID владельца замка по данным диагностики (0 — неизвестен)."""
    try:
        return int(read_info(path).get("pid") or 0)
    except Exception:
        return 0


def exclusivity_check(path: str) -> tuple:
    """Самопроверка замка: независимая попытка обязана получить отказ.

    Механизм «независимой попытки» выбирается по платформе:

    * POSIX — ``os.fork()``: потомок пробует взять тот же замок и сообщает
      результат кодом выхода (независимый процесс, а не дескриптор);
    * Windows (или нет fork) — второй дескриптор в том же процессе: LockFile
      не пускает и свой процесс, поэтому попытка обязана провалиться.

    -> (ok: bool, detail: str)
    """
    lk = InstanceLock(path)
    if not lk.acquire({"pid": os.getpid(), "ts": time.time(), "selftest": True}):
        return False, "не удалось захватить замок для проверки"
    try:
        if lk.degraded:
            return False, "замок деградирован (файл недоступен)"
        if os.name != "nt" and hasattr(os, "fork"):
            try:
                pid = os.fork()
            except Exception:
                pid = None
            if pid is not None:
                if pid == 0:                       # потомок
                    child = InstanceLock(path)
                    got = child.acquire()
                    try:
                        if got:
                            child.release(unlink=False)
                    except Exception:
                        pass
                    os._exit(0 if got else 7)      # 7 = отказ (то, что ждём)
                try:
                    _, status = os.waitpid(pid, 0)
                    code = os.waitstatus_to_exitcode(status)
                except Exception as e:
                    return False, f"waitpid: {e}"
                if code == 7:
                    return True, "потомок (fork) получил отказ — замок эксклюзивен"
                return False, (f"потомок (fork) взял замок (код {code}) — "
                               "замок не эксклюзивен")
        second = InstanceLock(path)
        got = second.acquire()
        if got:
            second.release(unlink=False)
            return False, "второй дескриптор взял замок — замок не эксклюзивен"
        return True, "второй дескриптор получил отказ — замок эксклюзивен"
    finally:
        lk.release()


def try_spawn_lock(path: str):
    """Короткий замок на «я сейчас запускаю экземпляр» (сериализация запусков).

    Возвращает InstanceLock (уже захваченный) либо None, если такой запуск уже
    идёт. Если прежний владелец умер, ОС снимает замок сама — устаревшие файлы
    замков не мешают.
    """
    lk = InstanceLock(path)
    if lk.acquire({"pid": os.getpid(), "ts": time.time(), "kind": "spawn"}):
        return lk
    return None
