# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
"""Скачивает официальное ядро Xray-core (Linux x64) в ``vendor-linux/bin/xray/``.

Linux-аналог ``fetch_core.py``. Разрешён единственный хост — ``github.com`` и
только путь ``/XTLS/Xray-core/releases/download/...``. Архив сверяется по
SHA256 с пином из ``core.lock.linux.json``, затем извлекаются ровно четыре
файла: ``xray``, ``geoip.dat``, ``geosite.dat``, ``LICENSE`` — они и попадают
внутрь ELF-бинарника как ``bin/xray/``.

Использование::

    python3 fetch_core_linux.py                  # скачать/доложить недостающее
    python3 fetch_core_linux.py --force          # перекачать
    python3 fetch_core_linux.py --verify         # только проверить скачанное
    python3 fetch_core_linux.py --print-lock     # напечатать новый lock-файл

Гео-базы и версия совпадают с Windows-сборкой (тот же тег релиза), поэтому
конфиги ядра переносимы между платформами.
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
VENDOR = os.path.join(HERE, "vendor-linux")
BIN = os.path.join(VENDOR, "bin", "xray")
LOCK = os.path.join(HERE, "core.lock.linux.json")
VERSION_FILE = os.path.join(HERE, "core_version.txt")

ASSET = "Xray-linux-64.zip"
WANTED = ("xray", "geoip.dat", "geosite.dat", "LICENSE")
ALLOWED_HOST = "github.com"
ALLOWED_PREFIX = "/XTLS/Xray-core/releases/download/"
_UA = "forest-proxy-updater-build/1.0 (+https://github.com/)"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_tag() -> str:
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except FileNotFoundError:
        pass
    try:
        with open(LOCK, encoding="utf-8") as f:
            return str(json.load(f).get("release") or "")
    except Exception:
        return ""


def read_lock() -> dict:
    try:
        with open(LOCK, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def release_url(tag: str) -> str:
    return f"https://{ALLOWED_HOST}{ALLOWED_PREFIX}{tag}/{ASSET}"


def _check_url(url: str) -> None:
    """Скачиваем только официальные релизы XTLS/Xray-core."""
    p = urlparse(url)
    if p.scheme != "https" or p.netloc != ALLOWED_HOST or not p.path.startswith(ALLOWED_PREFIX):
        raise SystemExit(f"Разрешены только официальные релизы: {url}")


def _download(url: str, dst: str) -> None:
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    tmp = dst + ".part"
    with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dst)


def _extract(zip_path: str) -> None:
    os.makedirs(BIN, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        names = {os.path.basename(n): n for n in z.namelist() if not n.endswith("/")}
        for want in WANTED:
            if want not in names:
                raise SystemExit(f"в архиве нет {want}")
            with z.open(names[want]) as src, open(os.path.join(BIN, want), "wb") as dst:
                shutil.copyfileobj(src, dst)
    os.chmod(os.path.join(BIN, "xray"), 0o755)


def verify() -> bool:
    """Сверяет скачанное с пином lock-файла. Печатает результат."""
    lock = read_lock()
    files = lock.get("files") or {}
    ok = True
    for name in WANTED:
        p = os.path.join(BIN, name)
        want = files.get(name, {})
        if not os.path.isfile(p):
            print(f"  НЕТ     {name}")
            ok = False
            continue
        got_sz, got_sha = os.path.getsize(p), _sha256(p)
        exp_sz, exp_sha = want.get("size"), want.get("sha256")
        if exp_sha and (got_sha != exp_sha or (exp_sz and got_sz != exp_sz)):
            print(f"  РАЗНОЕ  {name}: {got_sha[:12]} != {exp_sha[:12]}")
            ok = False
        else:
            print(f"  OK      {name} ({got_sz} байт)")
    print("Проверка ядра: " + ("пройдена" if ok else "НЕ пройдена"))
    return ok


def print_lock(tag: str, zip_path: str) -> None:
    data = {"release": tag, "asset": ASSET, "url": release_url(tag),
            "zip_size": os.path.getsize(zip_path), "zip_sha256": _sha256(zip_path),
            "files": {n: {"size": os.path.getsize(os.path.join(BIN, n)),
                          "sha256": _sha256(os.path.join(BIN, n))} for n in WANTED}}
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Скачать ядро Xray-core (Linux x64)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--print-lock", action="store_true")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args(argv)

    tag = args.tag or read_tag()
    if not tag:
        print("Не задан тег релиза (core_version.txt / core.lock.linux.json)")
        return 2
    zip_path = os.path.join(VENDOR, ASSET)

    if args.verify:
        return 0 if verify() else 1

    have = all(os.path.isfile(os.path.join(BIN, n)) for n in WANTED)
    if args.print_lock:
        if not have:
            print("нет распакованных файлов — сначала скачайте")
            return 1
        print_lock(tag, zip_path)
        return 0

    if have and not args.force:
        if verify():
            print(f"Ядро уже на месте: {BIN} ({tag})")
            return 0

    os.makedirs(VENDOR, exist_ok=True)
    if not os.path.isfile(zip_path) or args.force:
        print(f"Скачиваю {release_url(tag)}")
        try:
            _download(release_url(tag), zip_path)
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}: релиз {tag} недоступен?")
            return 1
    lock = read_lock()
    exp = lock.get("zip_sha256")
    got = _sha256(zip_path)
    if exp and got != exp and not args.force:
        print(f"SHA256 архива не совпал с пином!\n  ждали {exp}\n  получили {got}")
        return 1
    print(f"Распаковываю в {BIN}")
    _extract(zip_path)
    if lock:
        return 0 if verify() else 1
    print("Пин-файла нет — напечатаю lock для фиксации:")
    print_lock(tag, zip_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
