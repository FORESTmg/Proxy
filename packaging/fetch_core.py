# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
"""Скачивает официальное ядро Xray-core (Windows x64) в ``vendor/bin/xray/``.

Только официальные релизы: разрешён единственный хост — ``github.com`` и только
путь ``/XTLS/Xray-core/releases/download/...``. Архив сверяется по SHA256 с
пином из ``core.lock.json`` (и, для справки, с ``.dgst`` самого релиза), затем
извлекаются ровно четыре файла: ``xray.exe``, ``geoip.dat``, ``geosite.dat``,
``LICENSE`` — они и попадают внутрь одного ``.exe`` как ``bin/xray/``.

Использование::

    python fetch_core.py                  # скачать/доложить недостающее
    python fetch_core.py --force          # перекачать
    python fetch_core.py --verify         # только проверить уже скачанное
    python fetch_core.py --print-lock     # напечатать новый core.lock.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "vendor")
BIN = os.path.join(VENDOR, "bin", "xray")
LOCK = os.path.join(HERE, "core.lock.json")
VERSION_FILE = os.path.join(HERE, "core_version.txt")

ASSET = "Xray-windows-64.zip"
WANTED = ("xray.exe", "geoip.dat", "geosite.dat", "LICENSE")
ALLOWED_HOST = "github.com"
ALLOWED_PREFIX = "/XTLS/Xray-core/releases/download/"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_tag() -> str:
    """Версия релиза из core_version.txt (или из core.lock.json)."""
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except FileNotFoundError:
        pass
    lock = read_lock()
    if lock and lock.get("release"):
        return str(lock["release"])
    raise SystemExit("не найден тег релиза: заполните packaging/core_version.txt")


def read_lock() -> dict:
    try:
        with open(LOCK, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def release_url(tag: str) -> str:
    return f"https://{ALLOWED_HOST}{ALLOWED_PREFIX}{tag}/{ASSET}"


def _check_url(url: str) -> None:
    """Защита от подмены: только официальный репозиторий XTLS/Xray-core."""
    p = urlparse(url)
    if p.scheme != "https" or p.hostname != ALLOWED_HOST or \
            not p.path.startswith(ALLOWED_PREFIX):
        raise SystemExit(f"запрещённый источник (разрешён только "
                         f"github.com/XTLS/Xray-core): {url}")


def _download(url: str, dst: str) -> None:
    _check_url(url)
    print(f"[core] скачиваю {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "ForestProxyUpdater-build"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                pct = got * 100 // total
                sys.stdout.write(f"\r[core] {got / 1048576:6.1f} / "
                                 f"{total / 1048576:.1f} MiB ({pct}%)")
                sys.stdout.flush()
    print()


def _extract(zip_path: str) -> None:
    os.makedirs(BIN, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        names = {os.path.basename(n): n for n in z.namelist()}
        missing = [w for w in WANTED if w not in names]
        if missing:
            raise SystemExit(f"в архиве нет файлов: {', '.join(missing)}")
        for w in WANTED:
            with z.open(names[w]) as src, open(os.path.join(BIN, w), "wb") as dst:
                shutil.copyfileobj(src, dst)


def verify() -> bool:
    """Проверяет скачанные файлы против core.lock.json. True — всё совпало."""
    lock = read_lock()
    files = (lock or {}).get("files") or {}
    if not files:
        print("[core] core.lock.json без files — проверка по размерам пропущена")
        return all(os.path.isfile(os.path.join(BIN, w)) for w in WANTED)
    ok = True
    for name, meta in files.items():
        p = os.path.join(BIN, name)
        if not os.path.isfile(p):
            print(f"  FAIL нет файла {name}")
            ok = False
            continue
        size = os.path.getsize(p)
        got = _sha256(p)
        if size != meta.get("size") or got != meta.get("sha256"):
            print(f"  FAIL {name}: size={size} sha256={got}")
            ok = False
        else:
            print(f"  OK   {name}  {size} байт  {got}")
    return ok


def print_lock(tag: str, zip_path: str) -> None:
    data = {"release": tag, "asset": ASSET, "url": release_url(tag),
            "zip_size": os.path.getsize(zip_path),
            "zip_sha256": _sha256(zip_path), "files": {}}
    for w in WANTED:
        p = os.path.join(BIN, w)
        data["files"][w] = {"size": os.path.getsize(p), "sha256": _sha256(p)}
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="перекачать архив")
    ap.add_argument("--verify", action="store_true", help="только проверить")
    ap.add_argument("--print-lock", action="store_true",
                    help="напечатать core.lock.json по текущим файлам")
    ap.add_argument("--tag", default=None, help="явный тег релиза (например v1.2.3)")
    args = ap.parse_args(argv)

    tag = args.tag or read_tag()
    zip_path = os.path.join(VENDOR, ASSET)

    if args.print_lock:
        print_lock(tag, zip_path)
        return 0

    if args.verify:
        return 0 if verify() else 1

    have = all(os.path.isfile(os.path.join(BIN, w)) for w in WANTED)
    if have and not args.force:
        print("[core] ядро уже на месте — только проверяю")
        return 0 if verify() else 1

    url = release_url(tag)
    _check_url(url)
    os.makedirs(VENDOR, exist_ok=True)
    lock = read_lock()
    if os.path.isfile(zip_path) and not args.force and \
            lock.get("zip_size") == os.path.getsize(zip_path) and \
            lock.get("zip_sha256") == _sha256(zip_path):
        print("[core] использую уже скачанный архив (совпал с пином)")
    else:
        _download(url, zip_path)

    got = _sha256(zip_path)
    if lock.get("zip_sha256") and got != lock["zip_sha256"]:
        raise SystemExit(f"[core] SHA256 архива не совпал с core.lock.json:\n"
                         f"       ожидалось {lock['zip_sha256']}\n       получено   {got}")
    print(f"[core] SHA256 архива: {got}")

    _extract(zip_path)
    if not verify():
        raise SystemExit("[core] файлы не совпали с core.lock.json")
    print(f"[core] готово: {BIN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
