"""Трей — задел на следующий этап (GPL-3.0).

FOREST's Proxy Auto-updater.

ВАЖНО: визуальный значок в системном трее (Win32 NotifyIcon через ctypes)
ПОКА НЕ РЕАЛИЗОВАН — это отдельный этап (см. README). Поток ``run_tray``
уже существует и является полноценным потребителем канала состояния
(``state/tray_status.json``): он следит за сменой состояния и пишет её в лог.
Когда появится визуальный значок, он подписывается на тот же канал — так что
связь «сторож -> значок» проверена уже сейчас, без графики.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import log
import tray_status as TS


def run_tray(cfg: dict, stop_event=None, poll_s: float = 2.0) -> int:
    """Поток-потребитель канала состояния (визуальный значок — следующий этап)."""
    lg = log.get_logger()
    lg.info("Трей: визуальный значок пока не реализован (следующий этап, "
            "Win32/ctypes). Поток следит за каналом state/tray_status.json.")
    last = None
    while not (stop_event is not None and stop_event.is_set()):
        try:
            st = TS.read_status(cfg)
            state = st.get("state")
            tip = st.get("tip")
            if (state, tip) != last and state is not None:
                last = (state, tip)
                lg.info(f"tray: состояние={state} | {tip}")
        except Exception as e:
            lg.warn(f"tray: чтение статуса: {e}")
        if stop_event is not None:
            stop_event.wait(poll_s)
        else:
            time.sleep(poll_s)
    return 0
