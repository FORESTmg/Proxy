"""Проверка: побайтово ли совпадают ядро/гео внутри собранного .exe с пином core.lock.json."""
import hashlib
import json
import os
import sys

from PyInstaller.archive.readers import CArchiveReader

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "dist", "ForestProxyUpdater.exe")
LOCK = os.path.join(HERE, "core.lock.json")

BS = chr(92)
a = CArchiveReader(EXE)
lock = json.load(open(LOCK, encoding="utf-8"))
print("записей в onefile-архиве:", len(a.toc))

ok = True
for name, meta in lock["files"].items():
    key = "bin" + BS + "xray" + BS + name
    data = a.extract(key)
    h = hashlib.sha256(data).hexdigest()
    same = (h == meta["sha256"] and len(data) == meta["size"])
    ok &= same
    print("  %-5s %-26s %9d байт  %s…" % ("MATCH" if same else "DIFF", key, len(data), h[:24]))

cfg = a.extract("config.example.json")
print("  %-5s %-26s %9d байт" % ("ok" if cfg else "FAIL", "config.example.json", len(cfg)))
print("ИТОГ:", "вшитые ядро и гео-базы побайтово совпадают с официальным релизом"
      if ok else "РАСХОЖДЕНИЕ!")
sys.exit(0 if ok else 1)
