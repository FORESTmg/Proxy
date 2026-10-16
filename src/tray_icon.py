# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Иконки трея — ЧИСТЫЙ Python (только stdlib), без PIL и сторонних пакетов.

Значок рисуется кодом (суперсэмплинг) и упаковывается в валидный ``.ico``
вручную: ``ICONDIR`` + ``ICONDIRENTRY`` + ``BITMAPINFOHEADER`` + XOR-растр
(BGRA, снизу вверх) + AND-маска (нули — прозрачность задаёт альфа-канал).
Никаких временных файлов: те же байты отдаются Windows через
``CreateIconFromResourceEx`` — HICON создаётся прямо в памяти, поэтому модуль
работает и внутри собранного ``.exe``.

Три состояния значка, по два размера (16x16 для панели задач и 32x32 для
меню/масштабирования):

  * ``ok``    — зелёный  : прокси работает;
  * ``off``   — серый    : прокси выключен вручную;
  * ``error`` — красный  : нет связи.

Публичный интерфейс::

    make_ico([(w, h, pixels_bgra), ...])      -> bytes   # валидный .ico
    ico_image_payload(ico_bytes, size)        -> bytes|None
    state_ico("ok", sizes=(16, 32))           -> bytes
    all_state_icos()                          -> {"ok":...,"off":...,"error":...}
    save_ico(path, data)                      -> bool
    make_hicon(ico_bytes, size)               -> (HICON|None, err)
    destroy_hicon(hicon)                      -> None
    render_state(size, ring_rgb, dot_rgb)     -> bytes   # BGRA, top-down
"""
from __future__ import annotations

import math
import struct

# ────────────────────────────────────────────── упаковка .ico ───
_HEADER = struct.Struct("<HHH")            # reserved, type, count
_ENTRY = struct.Struct("<BBBBHHII")        # w,h,colors,res,planes,bpp,size,offset
_BMIH = struct.Struct("<IiiHHIIiiII")      # BITMAPINFOHEADER (40 байт)


def _dib_payload(pixels: bytes, w: int, h: int) -> bytes:
    """BITMAPINFOHEADER + XOR-растр (BGRA, снизу вверх) + AND-маска (нули)."""
    stride = w * 4
    xor = bytearray(stride * h)
    for y in range(h):                     # BMP/ICO хранят строки снизу вверх
        src = (h - 1 - y) * stride
        xor[y * stride:(y + 1) * stride] = pixels[src:src + stride]
    mask_row = ((w + 31) // 32) * 4        # 1 бит/пиксель, строки выровнены на 4
    mask = bytes(mask_row * h)             # все нули: прозрачность по альфе
    size_image = len(xor) + len(mask)
    hdr = _BMIH.pack(40, w, h * 2, 1, 32, 0, size_image, 0, 0, 0, 0)
    return hdr + bytes(xor) + mask


def make_ico(images: list) -> bytes:
    """Собирает валидный ``.ico`` из списка ``(w, h, pixels_bgra)``.

    ``pixels_bgra`` — ``w*h*4`` байт BGRA, строки СВЕРХУ ВНИЗ (как удобно при
    рисовании); в файл они кладутся в порядке BMP снизу вверх.
    """
    if not images:
        raise ValueError("make_ico: пустой список изображений")
    out = bytearray(_HEADER.pack(0, 1, len(images)))
    offset = 6 + 16 * len(images)
    entries, payloads = [], []
    for w, h, px in images:
        if len(px) != w * h * 4:
            raise ValueError(f"make_ico: ожидалось {w * h * 4} байт на {w}x{h}, "
                             f"получено {len(px)}")
        pl = _dib_payload(px, w, h)
        payloads.append(pl)
        bw = 0 if w >= 256 else w           # 0 = 256 в формате ICO
        bh = 0 if h >= 256 else h
        entries.append(_ENTRY.pack(bw, bh, 0, 0, 1, 32, len(pl), offset))
        offset += len(pl)
    out += b"".join(entries)
    out += b"".join(payloads)
    return bytes(out)


def ico_images(ico: bytes) -> list:
    """Разбирает ``.ico``: список ``(w, h, offset, size)`` (0 -> 256)."""
    if len(ico) < 6:
        return []
    _res, _typ, count = _HEADER.unpack_from(ico, 0)
    out = []
    for i in range(count):
        off = 6 + 16 * i
        if off + 16 > len(ico):
            break
        bw, bh, _c, _r, _p, _bpp, size, data_off = _ENTRY.unpack_from(ico, off)
        out.append((bw or 256, bh or 256, data_off, size))
    return out


def ico_image_payload(ico: bytes, size: int):
    """Байты RT_ICON-ресурса нужного размера (BITMAPINFOHEADER + XOR + mask)."""
    for w, _h, off, size_b in ico_images(ico):
        if w == size and 0 <= off and off + size_b <= len(ico):
            return ico[off:off + size_b]
    return None


def save_ico(path: str, data: bytes) -> bool:
    try:
        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


# ──────────────────────────────────────────── рисование значков ───
# (кольцо, точка) в RGB; альфа кольца чуть ниже — мягче выглядит на тёмной панели
STATES = {
    "ok":    ((34, 160, 80), (57, 194, 109)),    # зелёный — работает
    "off":   ((110, 112, 120), (150, 152, 160)),  # серый   — выключено вручную
    "error": ((198, 64, 64), (229, 72, 77)),      # красный — обрыв связи
}
_RING_A = 205          # непрозрачность кольца (0..255)
_DOT_A = 255           # точка полностью непрозрачна
_SS = 4                # суперсэмплинг 4x4 — сглаживает края без GDI


def render_state(size: int, ring_rgb, dot_rgb,
                 ring_a: int = _RING_A, dot_a: int = _DOT_A,
                 ss: int = _SS) -> bytes:
    """Рисует значок (кольцо + точка) в буфер BGRA ``size*size`` (сверху вниз)."""
    c = (size - 1) / 2.0
    r_out = size * 0.44
    thick = max(1.4, size * 0.11)
    r_in = max(0.0, r_out - thick)
    r_dot = size * 0.155
    ra = ring_a / 255.0
    da = dot_a / 255.0
    inv = 1.0 / (ss * ss)
    px = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            a_ring = a_dot = 0.0
            for sy in range(ss):
                fy = y + (sy + 0.5) / ss
                for sx in range(ss):
                    fx = x + (sx + 0.5) / ss
                    d = math.hypot(fx - c, fy - c)
                    if r_in <= d <= r_out:
                        a_ring += 1.0
                    if d <= r_dot:
                        a_dot += 1.0
            a_ring *= inv * ra
            a_dot *= inv * da
            alpha = a_dot + a_ring * (1.0 - a_dot)
            if alpha <= 0.001:
                continue
            # композит: точка поверх кольца (straight-alpha)
            r = (dot_rgb[0] * a_dot + ring_rgb[0] * a_ring * (1 - a_dot)) / alpha
            g = (dot_rgb[1] * a_dot + ring_rgb[1] * a_ring * (1 - a_dot)) / alpha
            b = (dot_rgb[2] * a_dot + ring_rgb[2] * a_ring * (1 - a_dot)) / alpha
            i = (y * size + x) * 4
            px[i] = max(0, min(255, int(round(b))))
            px[i + 1] = max(0, min(255, int(round(g))))
            px[i + 2] = max(0, min(255, int(round(r))))
            px[i + 3] = max(0, min(255, int(round(alpha * 255))))
    return bytes(px)


def state_ico(state: str, sizes=(16, 32)) -> bytes:
    """``.ico`` для состояния: ``ok`` | ``off`` | ``error`` (16 и 32 по умолчанию)."""
    ring, dot = STATES.get(state, STATES["off"])
    imgs = [(s, s, render_state(s, ring, dot)) for s in sizes]
    return make_ico(imgs)


def all_state_icos(sizes=(16, 32)) -> dict:
    return {name: state_ico(name, sizes) for name in STATES}


# ─────────────────────────────────────────── HICON в памяти (Win32) ───
_DWVER_ICON = 0x00030000


def make_hicon(ico: bytes, size: int):
    """``CreateIconFromResourceEx`` по байтам RT_ICON -> (HICON|None, err)."""
    payload = ico_image_payload(ico, size)
    if payload is None:
        return None, f"нет изображения размера {size}x{size} в .ico"
    try:
        import ctypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        fn = user32.CreateIconFromResourceEx
        fn.restype = ctypes.c_void_p
        fn.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                       ctypes.c_uint32, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        buf = ctypes.create_string_buffer(payload, len(payload))
        h = fn(ctypes.cast(buf, ctypes.c_void_p), len(payload), 1,
               _DWVER_ICON, size, size, 0)
        if not h:
            return None, f"CreateIconFromResourceEx: ошибка {ctypes.get_last_error()}"
        return h, ""
    except Exception as e:
        return None, f"CreateIconFromResourceEx: {e}"


def destroy_hicon(hicon) -> None:
    if not hicon:
        return
    try:
        import ctypes
        ctypes.WinDLL("user32", use_last_error=True).DestroyIcon(
            ctypes.c_void_p(hicon))
    except Exception:
        pass


if __name__ == "__main__":          # ручная проверка: иконки -> файлы рядом
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for name, data in all_state_icos().items():
        p = os.path.join(here, f"state_{name}.ico")
        print(f"{name}: {len(data)} байт, размеры "
              f"{[w for w, _h, _o, _s in ico_images(data)]} -> {'OK' if save_ico(p, data) else 'FAIL'} ({p})")
