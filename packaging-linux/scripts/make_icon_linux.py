#!/usr/bin/env python3
# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
"""make_icon_linux.py — рисует иконку (PNG) для AppImage без внешних библиотек.

Продукт без окон, но AppImage требует .desktop рядом с иконкой. Чтобы не тащить
в сборку ImageMagick/Pillow, PNG собирается вручную: zlib + struct из стандартной
библиотеки (формат PNG простой, а картинка — геометрическая).

    python3 make_icon_linux.py out.png [размер]

Рисунок: тёмно-зелёный квадрат, светлый «еловый» треугольник, ствол и
горизонтальная линия связи (прокси).
"""
import struct
import sys
import zlib

BG = (18, 46, 32, 255)        # тёмно-зелёный фон
FG = (86, 196, 118, 255)      # светлая зелень (крона)
TRUNK = (156, 118, 76, 255)   # ствол
LINK = (232, 240, 236, 255)   # линия связи
EDGE = (12, 32, 22, 255)      # рамка


def make_canvas(n):
    px = [[BG for _ in range(n)] for _ in range(n)]
    return px


def put(px, x, y, color):
    n = len(px)
    if 0 <= x < n and 0 <= y < n:
        px[y][x] = color


def fill_rect(px, x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(len(px), y1 + 1)):
        for x in range(max(0, x0), min(len(px), x1 + 1)):
            px[y][x] = color


def fill_triangle(px, cx, y_top, y_bottom, half_width_bottom, color):
    """Равнобедренный треугольник вершиной вверх."""
    height = y_bottom - y_top
    if height <= 0:
        return
    for y in range(y_top, y_bottom + 1):
        t = (y - y_top) / height
        half = max(1, int(round(half_width_bottom * t)))
        for x in range(cx - half, cx + half + 1):
            put(px, x, y, color)


def draw(n):
    px = make_canvas(n)
    u = n / 256.0                      # масштаб от макета 256x256

    def s(v):
        return int(round(v * u))

    # рамка
    fill_rect(px, 0, 0, n - 1, s(3), EDGE)
    fill_rect(px, 0, n - 1 - s(3), n - 1, n - 1, EDGE)
    fill_rect(px, 0, 0, s(3), n - 1, EDGE)
    fill_rect(px, n - 1 - s(3), 0, n - 1, n - 1, EDGE)

    cx = n // 2
    # крона: три яруса
    fill_triangle(px, cx, s(38), s(120), s(74), FG)
    fill_triangle(px, cx, s(84), s(158), s(60), FG)
    fill_triangle(px, cx, s(124), s(186), s(44), FG)
    # ствол
    fill_rect(px, cx - s(11), s(180), cx + s(11), s(226), TRUNK)
    # линия связи поверх ствола (символ прокси-канала)
    fill_rect(px, s(20), s(206), s(236), s(214), LINK)
    return px


def write_png(path, px):
    n = len(px)
    raw = bytearray()
    for row in px:
        raw.append(0)                                   # фильтр None
        for (r, g, b, a) in row:
            raw += bytes((r, g, b, a))
    ihdr = struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0)  # 8 бит, RGBA
    chunks = [(b"IHDR", ihdr),
              (b"IDAT", zlib.compress(bytes(raw), 9)),
              (b"IEND", b"")]
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        for tag, data in chunks:
            f.write(struct.pack(">I", len(data)))
            f.write(tag)
            f.write(data)
            f.write(struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def main(argv):
    if len(argv) < 2:
        print("использование: make_icon_linux.py <файл.png> [размер]", file=sys.stderr)
        return 2
    path = argv[1]
    size = int(argv[2]) if len(argv) > 2 else 256
    write_png(path, draw(size))
    print(f"иконка: {path} ({size}x{size})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
