#!/usr/bin/env python3
# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
"""PNG для Linux-пакетов из пользовательской иконки packaging/app.ico.

Иконка приложения — ОДНА (рисунок пользователя). Windows-сборка берёт app.ico,
Linux-пакеты — эту PNG, полученную из того же файла, поэтому расхождений нет.

    python3 packaging-linux/scripts/ico_to_png.py [--size 256] [--out PATH]

Чистый stdlib: .ico разбирается вручную, PNG пишется zlib'ом.
"""
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ICO = os.path.join(REPO, "packaging", "app.ico")
OUT = os.path.join(REPO, "packaging-linux", "icons", "forest-proxy-updater.png")
BMIH = struct.Struct("<IiiHHIIiiII")
ENTRY = struct.Struct("<BBBBHHII")


def read_ico_images(data):
    if len(data) < 6:
        return []
    _r, _t, n = struct.unpack_from("<HHH", data, 0)
    out = []
    for i in range(n):
        off = 6 + 16 * i
        if off + 16 > len(data):
            break
        bw, bh, _c, _res, _pl, bpp, size, data_off = ENTRY.unpack_from(data, off)
        out.append({"w": bw or 256, "h": bh or 256, "bpp": bpp,
                    "off": data_off, "size": size})
    return out


def dib_pixels(data, img):
    """BGRA (снизу вверх) -> RGBA (сверху вниз)."""
    payload = data[img["off"]:img["off"] + img["size"]]
    if len(payload) < 40:
        return None
    _sz, w, h2, _pl, bpp, _cmp, _isz, _x, _y, _cu, _ci = BMIH.unpack_from(payload, 0)
    h = h2 // 2
    if bpp != 32 or w <= 0 or h <= 0:
        return None
    raw = payload[40:40 + w * h * 4]
    if len(raw) < w * h * 4:
        return None
    out = bytearray(w * h * 4)
    stride = w * 4
    for y in range(h):
        src = (h - 1 - y) * stride
        row = raw[src:src + stride]
        for x in range(w):
            b, g, r, a = row[x * 4:x * 4 + 4]
            i = (y * w + x) * 4
            out[i], out[i + 1], out[i + 2], out[i + 3] = r, g, b, a
    return w, h, bytes(out)


def write_png(path, w, h, rgba):
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


def main(argv):
    size, out = 256, OUT
    i = 0
    while i < len(argv):
        if argv[i] == "--size":
            size = int(argv[i + 1]); i += 2
        elif argv[i] == "--out":
            out = argv[i + 1]; i += 2
        else:
            i += 1
    data = open(ICO, "rb").read()
    imgs = read_ico_images(data)
    if not imgs:
        print(f"НЕ .ico или битый файл: {ICO}")
        return 2
    pick = None
    for im in imgs:
        if im["w"] == size:
            pick = im
            break
    if pick is None:
        pick = max(imgs, key=lambda m: m["w"])
    pay = data[pick["off"]:pick["off"] + pick["size"]]
    if pay[:8] == b"\x89PNG\r\n\x1a\n":
        # изображение уже PNG-потоком — используем как есть (без перекодирования)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "wb") as f:
            f.write(pay)
        print(f"источник: {ICO} ({len(data)} байт, размеры {[i['w'] for i in imgs]})")
        print(f"PNG (как есть из .ico): {out} ({len(pay)} байт)")
        return 0
    px = dib_pixels(data, pick)
    if not px:
        print(f"нет 32-битного изображения {size} в {ICO} "
              f"(есть {[i['w'] for i in imgs]})")
        return 3
    w, h, rgba = px
    n = write_png(out, w, h, rgba)
    print(f"источник: {ICO} ({len(data)} байт, размеры {[i['w'] for i in imgs]})")
    print(f"PNG: {out} ({n} байт, {w}x{h})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
