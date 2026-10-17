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
    mark_state(px, w, h, rgb, rim)            -> (pixels, доля метки)
    user_state_ico(ico, state, sizes, mark)   -> bytes   # рисунок + метка
    artwork_share(state_ico, app_ico, size)   -> float   # доказательство по пикселям
    badge_color_share(state_ico, rgb, size)   -> float

Значок трея — РИСУНОК ПОЛЬЗОВАТЕЛЯ (``app.ico``) без единого изменённого
пикселя; состояние связи показывает метка-кружок в правом нижнем углу
(:func:`mark_state`), а не перекраска всего рисунка.
"""
from __future__ import annotations

import math
import os
import struct
import sys

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
    "busy":  ((198, 150, 22), (240, 196, 44)),    # жёлтый  — идёт переключение/проверка
    # состояния ЭТАЛОНА (v2ray-auto-updater, tray.ps1) — цвета оттуда же
    "switch": ((198, 150, 34), (240, 180, 41)),    # переключение сервера
    "noanswer": ((198, 150, 34), (240, 180, 41)),  # сторож молчит (нет данных)
    "restoring": ((58, 108, 214), (79, 140, 255)),  # восстановление связи
    "down": ((198, 64, 64), (229, 72, 77)),        # НЕТ СВЯЗИ (синоним error)
}
# Имена, для которых рисуется значок: четыре «рабочих» состояния программы
# плюс три состояния эталона, которые показывает помощник интерфейса.
STATE_NAMES = ("ok", "busy", "off", "error", "switch", "noanswer", "restoring",
               "down")


def _darken(rgb, k: float = 0.72):
    return tuple(max(0, min(255, int(round(c * k)))) for c in rgb)


def states(cfg: dict = None) -> dict:
    """Цвета состояний из палитры темы (светлая/тёмная).

    Для состояний эталона (switch/noanswer/restoring/down) берём цвета из
    :mod:`status_info` — они перенесены из прежней надстройки дословно.
    """
    try:
        import theme
        out = {}
        for name in STATE_NAMES:
            c = theme.state_color(cfg, name)
            out[name] = (_darken(c), c)
        try:
            import status_info as SI
            for name in ("switch", "noanswer", "restoring", "down"):
                if name in SI.STATES:
                    c = SI.STATES[name]["rgb"]
                    out[name] = (_darken(c), c)
        except Exception:
            pass
        return out
    except Exception:
        return {k: v for k, v in STATES.items()}


def state_color(state: str, cfg: dict = None):
    try:
        import theme
        return theme.state_color(cfg, state)
    except Exception:
        return STATES.get(state, STATES["off"])[1]
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


# ═══════════════════════════ иконка ПОЛЬЗОВАТЕЛЯ + метка состояния ═══
# Значок трея — рисунок пользователя (app.ico) БЕЗ ЕДИНОГО ИЗМЕНЁННОГО ПИКСЕЛЯ;
# состояние связи показывает отдельная метка-кружок в правом нижнем углу
# (mark_state) цветом состояния. Прежний вариант заливал рисунок цветом
# состояния на 90 % — значок превращался в одноцветную плитку и переставал быть
# иконкой пользователя.
# Если файла нет/он битый — молча откатываемся на нарисованный значок.
_APP_ICO_CACHE = {"key": None, "data": b""}


def find_app_ico(cfg: dict = None) -> str:
    """Где лежит app.ico: рядом с .exe -> в бандле -> в каталоге данных -> в репо."""
    cands = []
    try:
        if sys.executable:
            cands.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                                      "app.ico"))
    except Exception:
        pass
    try:
        mp = getattr(sys, "_MEIPASS", "") or ""
        if mp:
            cands.append(os.path.join(mp, "app.ico"))
    except Exception:
        pass
    try:
        root = ((cfg or {}).get("paths") or {}).get("root") or ""
        if root:
            cands.append(os.path.join(root, "app.ico"))
        import config as CFG
        cands.append(os.path.join(CFG.PROJECT_DIR, "app.ico"))
        cands.append(os.path.join(CFG.PROJECT_DIR, "packaging", "app.ico"))
        cands.append(os.path.join(CFG.BASE_DIR, "app.ico"))
        cands.append(os.path.join(os.path.dirname(CFG.BASE_DIR), "packaging", "app.ico"))
    except Exception:
        pass
    for c in cands:
        try:
            if c and os.path.isfile(c):
                return c
        except Exception:
            continue
    return ""


def load_app_ico(cfg: dict = None) -> bytes:
    """Байты app.ico пользователя (кэш по пути+mtime). b'' — нет/битый."""
    p = find_app_ico(cfg)
    if not p:
        return b""
    try:
        key = (p, os.path.getmtime(p))
    except Exception:
        key = (p, 0)
    if _APP_ICO_CACHE.get("key") == key:
        return _APP_ICO_CACHE.get("data") or b""
    data = b""
    try:
        with open(p, "rb") as f:
            data = f.read()
        if not ico_images(data):        # битый/не .ico
            data = b""
    except Exception:
        data = b""
    _APP_ICO_CACHE["key"], _APP_ICO_CACHE["data"] = key, data
    return data


def _png_to_rgba(data: bytes):
    """Минимальный PNG-декодер (8 бит, color type 2/6, без интерлейса).

    Нужен потому, что современные .ico (в т. ч. иконка пользователя) хранят
    изображения как PNG-потоки, а не как DIB. -> (w, h, RGBA top-down) | None
    """
    try:
        import zlib
        if not data or data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        i, w, h, ct, bd = 8, 0, 0, 0, 0
        idat = bytearray()
        while i + 8 <= len(data):
            ln = struct.unpack_from(">I", data, i)[0]
            tag = data[i + 4:i + 8]
            body = data[i + 8:i + 8 + ln]
            if tag == b"IHDR":
                w, h, bd, ct = struct.unpack_from(">IIBB", body, 0)
                if body[12] != 0:          # interlace
                    return None
            elif tag == b"IDAT":
                idat += body
            elif tag == b"IEND":
                break
            i += 12 + ln
        if not w or not h or bd != 8 or ct not in (2, 6):
            return None
        ch = 4 if ct == 6 else 3
        raw = zlib.decompress(bytes(idat))
        stride = w * ch
        out = bytearray(w * h * 4)
        prev = bytearray(stride)
        pos = 0
        for y in range(h):
            ft = raw[pos]; pos += 1
            line = bytearray(raw[pos:pos + stride]); pos += stride
            if len(line) < stride:
                return None
            if ft == 1:                    # Sub
                for x in range(ch, stride):
                    line[x] = (line[x] + line[x - ch]) & 0xFF
            elif ft == 2:                  # Up
                for x in range(stride):
                    line[x] = (line[x] + prev[x]) & 0xFF
            elif ft == 3:                  # Average
                for x in range(stride):
                    a = line[x - ch] if x >= ch else 0
                    line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xFF
            elif ft == 4:                  # Paeth
                for x in range(stride):
                    a = line[x - ch] if x >= ch else 0
                    b = prev[x]
                    c = prev[x - ch] if x >= ch else 0
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    line[x] = (line[x] + pr) & 0xFF
            elif ft != 0:
                return None
            prev = line
            for x in range(w):
                si = x * ch
                di = (y * w + x) * 4
                out[di] = line[si]
                out[di + 1] = line[si + 1]
                out[di + 2] = line[si + 2]
                out[di + 3] = line[si + 3] if ch == 4 else 255
        return w, h, bytes(out)
    except Exception:
        return None


def _dib_to_pixels(payload: bytes):
    """RT_ICON (DIB или PNG-поток) -> (w, h, pixels BGRA top-down) или None."""
    if not payload:
        return None
    # современные .ico хранят изображения как PNG — декодируем и переводим в BGRA
    if payload[:8] == b"\x89PNG\r\n\x1a\n":
        r = _png_to_rgba(payload)
        if not r:
            return None
        w, h, rgba = r
        out = bytearray(w * h * 4)
        for i in range(0, len(rgba), 4):
            out[i] = rgba[i + 2]        # B
            out[i + 1] = rgba[i + 1]    # G
            out[i + 2] = rgba[i]        # R
            out[i + 3] = rgba[i + 3]
        return w, h, bytes(out)
    if len(payload) < 40:
        return None
    try:
        _sz, w, h2, _pl, bpp, _cmp, _isz, _x, _y, _cu, _ci = _BMIH.unpack_from(payload, 0)
        h = h2 // 2
        if w <= 0 or h <= 0 or bpp != 32 or w > 512 or h > 512:
            return None
        need = w * h * 4
        raw = payload[40:40 + need]
        if len(raw) < need:
            return None
        out = bytearray(need)
        stride = w * 4
        for y in range(h):              # в файле снизу вверх -> разворачиваем
            src = (h - 1 - y) * stride
            out[y * stride:(y + 1) * stride] = raw[src:src + stride]
        return w, h, bytes(out)
    except Exception:
        return None


def mark_state(px: bytes, w: int, h: int, rgb, rim=None, radius_frac: float = 0.26,
               ss: int = _SS):
    """Рисует ЗНАЧОК СОСТОЯНИЯ (кружок в правом нижнем углу), НЕ портя рисунок.

    Прежняя версия заливала рисунок пользователя цветом состояния на 90 % — и
    значок трея превращался в одноцветную плитку, теряя сам рисунок. Теперь
    рисунок остаётся КАК ЕСТЬ, а состояние показывает отдельная метка-кружок
    поверх него (как значки-наложения Windows): цвет состояния + тонкая тёмная
    обводка, чтобы читалось и на светлой, и на тёмной панели задач.

    -> (pixels, доля пикселей метки от всех пикселей значка 0..1)
    """
    out = bytearray(px)
    if not rgb:
        return bytes(out), 0.0
    r = max(2.0, radius_frac * w)
    cx = cy = (w - 1) - r * 0.78          # правый нижний угол, чуть внутрь
    ring = max(1.0, w * 0.045)            # тёмная обводка метки
    rc = rim or (16, 16, 18)
    inv = 1.0 / (ss * ss)
    hit = 0
    r2 = r * r
    r_in2 = (r - ring) * (r - ring)
    for y in range(h):
        for x in range(w):
            a_core = a_ring = 0.0
            for sy in range(ss):
                fy = y + (sy + 0.5) / ss
                for sx in range(ss):
                    fx = x + (sx + 0.5) / ss
                    dx, dy = fx - cx, fy - cy
                    d2 = dx * dx + dy * dy
                    if d2 <= r2:
                        a_ring += 1.0
                        if d2 <= r_in2:
                            a_core += 1.0
            a_core *= inv
            a_ring *= inv
            if a_ring <= 0.002:
                continue
            # цвет метки = состояние (ядро) поверх тёмной обводки (кольцо)
            t = (a_core / a_ring) if a_ring else 0.0
            mr = rc[0] + (rgb[0] - rc[0]) * t
            mg = rc[1] + (rgb[1] - rc[1]) * t
            mb = rc[2] + (rgb[2] - rc[2]) * t
            i = (y * w + x) * 4
            for ci, cc in ((2, mr), (1, mg), (0, mb)):
                out[i + ci] = max(0, min(255, int(round(
                    out[i + ci] * (1.0 - a_ring) + cc * a_ring))))
            out[i + 3] = max(out[i + 3], int(round(255 * a_ring)))
            hit += 1
    return bytes(out), (hit / (w * h) if w * h else 0.0)


def user_state_ico(ico: bytes, state: str, sizes=(16, 32), mark: bool = True,
                   cfg: dict = None):
    """``.ico`` состояния из иконки пользователя (b'' — если собрать нельзя).

    Рисунок пользователя переносится БЕЗ ИЗМЕНЕНИЙ (ни одного перекрашенного
    пикселя); состояние показывает метка-кружок в правом нижнем углу
    (:func:`mark_state`). Так значок трея остаётся иконкой пользователя, а не
    цветной заливкой.
    """
    st = states(cfg)
    ring, dot = st.get(state, st["off"])
    try:
        import theme
        rim = theme.palette(cfg).get("tray_rim")
    except Exception:
        rim = (18, 18, 18)
    imgs = []
    for s in sizes:
        pay = ico_image_payload(ico, s)
        d = _dib_to_pixels(pay) if pay else None
        if not d:
            continue
        w, h, px = d
        if mark:
            px, _frac = mark_state(px, w, h, dot, rim=rim)
        imgs.append((w, h, px))
    if not imgs:
        return b""
    return make_ico(imgs)


def state_mark_enabled(cfg: dict = None) -> bool:
    """Показывать ли цвет состояния (``ui.tray_state_mark``, по умолчанию ДА)."""
    try:
        v = ((cfg or {}).get("ui") or {}).get("tray_state_mark", True)
        return bool(v)
    except Exception:
        return True


# ── доказательства по пикселям (для проверок) ──────────────────────────────
def artwork_share(state_ico: bytes, app_ico: bytes, size: int = 32) -> float:
    """Доля пикселей значка состояния, СОВПАДАЮЩИХ с рисунком пользователя.

    Сравниваем растр значка состояния и исходной иконки пиксель-в-пиксель.
    1.0 — значок не отличается от рисунка; меньше 1.0 ровно на площадь метки
    состояния. Так проверка доказывает, что значок трея — РИСУНОК ПОЛЬЗОВАТЕЛЯ,
    а не одноцветная заливка.
    """
    try:
        a = ico_image_payload(state_ico, size)
        b = ico_image_payload(app_ico, size)
        pa = _dib_to_pixels(a) if a else None
        pb = _dib_to_pixels(b) if b else None
        if not pa or not pb:
            return 0.0
        _w, _h, x = pa
        _w2, _h2, y = pb
        n = min(len(x), len(y)) // 4
        if not n:
            return 0.0
        same = 0
        for i in range(0, n * 4, 4):
            if x[i:i + 3] == y[i:i + 3]:
                same += 1
        return same / n
    except Exception:
        return 0.0


def badge_center(state_ico: bytes, size: int = 32):
    """Центр метки состояния (x, y) в растре значка размера ``size``."""
    r = max(2.0, 0.26 * size)
    c = int(round((size - 1) - r * 0.78))
    return c, c


def badge_color_share(state_ico: bytes, rgb, size: int = 32,
                      tol: int = 90, half: int = 2) -> float:
    """Доля пикселей вокруг центра метки, близких к цвету состояния ``rgb``."""
    try:
        pay = ico_image_payload(state_ico, size)
        d = _dib_to_pixels(pay) if pay else None
        if not d:
            return 0.0
        w, h, px = d
        cx, cy = badge_center(state_ico, size)
        hit = tot = 0
        for dy in range(-half, half + 1):
            for dx in range(-half, half + 1):
                x, y = cx + dx, cy + dy
                if not (0 <= x < w and 0 <= y < h):
                    continue
                i = (y * w + x) * 4
                b, g, r = px[i], px[i + 1], px[i + 2]
                tot += 1
                if abs(r - rgb[0]) + abs(g - rgb[1]) + abs(b - rgb[2]) < tol:
                    hit += 1
        return (hit / tot) if tot else 0.0
    except Exception:
        return 0.0


def state_ico(state: str, sizes=(16, 32), cfg: dict = None) -> bytes:
    """``.ico`` для состояния: ``ok`` | ``busy`` | ``off`` | ``error``.

    Приоритет — иконка пользователя (app.ico) с цветом состояния ВНУТРИ; если
    её нет или она битая — прежний нарисованный значок (кольцо + точка).
    """
    ico = load_app_ico(cfg)
    if ico:
        data = user_state_ico(ico, state, sizes, mark=state_mark_enabled(cfg), cfg=cfg)
        if data:
            return data
    st = states(cfg)
    ring, dot = st.get(state, st["off"])
    imgs = [(s, s, render_state(s, ring, dot)) for s in sizes]
    return make_ico(imgs)


def all_state_icos(sizes=(16, 32), cfg: dict = None) -> dict:
    return {name: state_ico(name, sizes, cfg) for name in STATES}


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
