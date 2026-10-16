# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
"""Генератор иконки приложения ``app.ico`` — на чистом Python (stdlib only).

Никакого PIL/ImageMagick: изображение рисуется вручную (суперсэмплинг 1024x1024
+ box-downscale), затем пакуется в настоящий multi-size ICO с 32-битными
DIB-записями (BITMAPINFOHEADER + BGRA + AND-маска) — такой формат понимают и
Windows Explorer, и PyInstaller.

Мотив: тёмно-зелёный «скруглённый квадрат» с силуэтом хвойного дерева —
FOREST. Контраст светлой кроны на тёмном фоне читается даже в 16x16.

Запуск:
    python make_icon.py [выходной_файл.ico]
По умолчанию пишет ``app.ico`` рядом со скриптом.
"""
from __future__ import annotations

import os
import struct
import sys

SIZES = [16, 24, 32, 48, 64, 128, 256]
SS = 1024            # размер мастер-изображения (суперсэмплинг)


# ────────────────────────────────────────── геометрия / цвет ───
def _in_round_rect(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= r * r


def _in_tri(px, py, ax, ay, bx, by, cx, cy):
    d1 = (px - bx) * (ay - by) - (ax - bx) * (py - by)
    d2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy)
    d3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def _mix(c1, c2, t):
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return (int(round(c1[0] + (c2[0] - c1[0]) * t)),
            int(round(c1[1] + (c2[1] - c1[1]) * t)),
            int(round(c1[2] + (c2[2] - c1[2]) * t)))


def _render_master(n=SS):
    """Рисует мастер-изображение. Возвращает bytearray RGBA (сверху вниз)."""
    buf = bytearray(n * n * 4)
    # фон: скруглённый квадрат, вертикальный градиент
    bg_top, bg_bot = (24, 104, 58), (7, 46, 27)
    # крона: светло-мятная сверху -> сочная зелёная снизу
    fg_top, fg_bot = (206, 250, 214), (104, 210, 138)
    trunk_top, trunk_bot = (104, 70, 36), (66, 42, 20)

    m = 0.045 * n
    r = 0.215 * n
    x0, y0, x1, y1 = m, m, n - m, n - m

    # три «яруса» ели: (apex_v, base_v, half_width)
    tiers = ((0.145, 0.400, 0.175),
             (0.300, 0.585, 0.245),
             (0.445, 0.745, 0.315))

    for py in range(n):
        v = (py + 0.5) / n
        row = py * n * 4
        for px in range(n):
            u = (px + 0.5) / n
            o = row + px * 4
            # ── фон ──
            if not _in_round_rect(u, v, x0 / n, y0 / n, x1 / n, y1 / n, r / n):
                buf[o:o + 4] = b"\x00\x00\x00\x00"
                continue
            g = _mix(bg_top, bg_bot, v)
            rr, gg, bb = g
            # лёгкий радиальный блик в левом верхнем углу
            d = ((u - 0.28) ** 2 + (v - 0.24) ** 2) ** 0.5
            sh = max(0.0, 1.0 - d / 0.62) ** 2 * 0.13
            rr = int(rr * (1 - sh) + 74 * sh)
            gg = int(gg * (1 - sh) + 168 * sh)
            bb = int(bb * (1 - sh) + 104 * sh)

            # ── ствол ──
            if 0.468 <= u <= 0.532 and 0.700 <= v <= 0.845:
                tc = _mix(trunk_top, trunk_bot, (v - 0.700) / 0.145)
                buf[o:o + 3] = bytes(tc)
                buf[o + 3] = 255
                continue

            # ── крона (ярусы рисуем снизу вверх) ──
            hit = False
            for (av, bv, hw) in reversed(tiers):
                if v < av or v > bv:
                    continue
                t = (v - av) / (bv - av)
                half = hw * t
                if abs(u - 0.5) <= half:
                    hit = True
                    break
            if hit:
                fc = _mix(fg_top, fg_bot, (v - 0.10) / 0.66)
                buf[o:o + 3] = bytes(fc)
                buf[o + 3] = 255
                continue

            buf[o] = rr
            buf[o + 1] = gg
            buf[o + 2] = bb
            buf[o + 3] = 255
    return buf


def _box_downscale(src, src_n, dst_n):
    """Усреднение блоков src_n x src_n -> dst_n x dst_n (RGBA, с альфой)."""
    out = bytearray(dst_n * dst_n * 4)
    block = src_n // dst_n
    if block < 1:
        block = 1
    area = block * block
    for dy in range(dst_n):
        for dx in range(dst_n):
            r = g = b = a = 0
            sy0, sx0 = dy * block, dx * block
            for sy in range(sy0, sy0 + block):
                ro = (sy * src_n + sx0) * 4
                for sx in range(block):
                    o = ro + sx * 4
                    al = src[o + 3]
                    if al:
                        r += src[o] * al
                        g += src[o + 1] * al
                        b += src[o + 2] * al
                        a += al
            o = (dy * dst_n + dx) * 4
            if a:
                out[o] = r // a
                out[o + 1] = g // a
                out[o + 2] = b // a
                out[o + 3] = a // area
    return out


def _dib(size, rgba):
    """32-битная DIB-запись ICO: BITMAPINFOHEADER + BGRA (снизу вверх) + AND-маска."""
    hdr = struct.pack("<IiiHHIIiiII",
                      40, size, size * 2, 1, 32, 0,
                      size * size * 4, 0, 0, 0, 0)
    xor = bytearray()
    for y in range(size - 1, -1, -1):
        base = y * size * 4
        for x in range(size):
            o = base + x * 4
            xor += bytes((rgba[o + 2], rgba[o + 1], rgba[o], rgba[o + 3]))
    row_bytes = ((size + 31) // 32) * 4
    and_mask = bytearray()
    for y in range(size - 1, -1, -1):
        base = y * size * 4
        row = bytearray(row_bytes)
        for x in range(size):
            if rgba[base + x * 4 + 3] == 0:
                row[x >> 3] |= 0x80 >> (x & 7)
        and_mask += row
    return bytes(hdr) + bytes(xor) + bytes(and_mask)


def build_ico(path: str, sizes=SIZES) -> str:
    master = _render_master(SS)
    images = []
    for s in sizes:
        px = master if s == SS else _box_downscale(master, SS, s)
        images.append((s, _dib(s, px)))
    out = bytearray()
    out += struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for (s, data) in images:
        dim = 0 if s >= 256 else s
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for (_, data) in images:
        out += data
    with open(path, "wb") as f:
        f.write(bytes(out))
    return path


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = argv[0] if argv else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "app.ico")
    build_ico(out)
    print(f"icon written: {out} ({os.path.getsize(out)} bytes, "
          f"sizes={','.join(str(s) for s in SIZES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
