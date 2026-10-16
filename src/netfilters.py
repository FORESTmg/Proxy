# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Сетевые фильтры отбора серверов: подсети, разнообразие, Cloudflare.

Зачем:
  1. РАЗНООБРАЗИЕ. У бесплатных списков топ по RTT часто занимает один релей
     (одна подсеть /24), раскиданный по десяткам IP. Тест скорости при этом
     бьёт по одному провайдеру параллельно — он гасит всплеск, и все узлы
     показывают ноль, хотя поодиночке дают мегабайты. Кап «не больше N узлов
     с одной /24» разводит отбор по разным провайдерам.
  2. CLOUDFLARE. Узлы, чей адрес сам находится в сетях Cloudflare, ходят через
     заграничные края CF — у российских провайдеров они давятся сильнее всего
     (в замерах такой узел дал 0.6 КБ/с). Их исключаем ИЗ СПИСКА СЕРВЕРОВ;
     на маршрутизацию и доступность сайтов это не влияет.
"""
import ipaddress
import json
import os
import socket
import time

# Официальный список https://www.cloudflare.com/ips-v4 (проверен 12.10.2026).
# Служит резервом, если обновить по сети не удалось.
BUNDLED_CF_V4 = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
]
CF_URL = "https://www.cloudflare.com/ips-v4"
CF_REFRESH_S = 7 * 24 * 3600      # список меняется редко — обновляем раз в неделю

_NETS = None            # list[ipaddress.IPv4Network]
_DNS_CACHE = {}         # hostname -> bool (адрес в сетях Cloudflare)


# --------------------------------------------------------------------- подсети

def sub24(addr: str) -> str:
    """Ключ подсети для группировки. IPv4 — первые три октета, иначе сам адрес."""
    a = str(addr or "").strip()
    if a.count(".") == 3:
        return ".".join(a.split(".")[:3])
    return a.lower()


def pick_diverse(servers: list, limit: int, cap: int = 1, key=None,
                 backfill: bool = False) -> list:
    """Берёт до limit серверов, но не больше cap с одной подсети.

    Порядок входа сохраняется (вызывающий сортирует по RTT/скорости заранее).
    backfill=False (по умолчанию) — кап строгий: лучше меньше серверов, но
    каждый со своего провайдера. backfill=True добирает остатком, если кап
    не дал набрать limit.
    """
    if limit <= 0:
        return []
    if cap <= 0:
        return list(servers)[:limit]
    keyf = key or (lambda s: sub24(getattr(s, "address", "")))
    taken, per, skipped = [], {}, []
    for s in servers:
        if len(taken) >= limit:
            break
        k = keyf(s)
        if per.get(k, 0) >= cap:
            skipped.append(s)
            continue
        per[k] = per.get(k, 0) + 1
        taken.append(s)
    if backfill and len(taken) < limit:
        have = {id(s) for s in taken}
        for s in skipped:
            if len(taken) >= limit:
                break
            if id(s) not in have:
                taken.append(s)
    return taken


def pick_diverse_floor(servers: list, limit: int, cap: int = 1, floor: int = 0,
                       max_cap: int = 4) -> tuple:
    """pick_diverse + страховка от слишком маленького пула.

    Правило: не больше `cap` узлов с одной подсети. Но если так пул выходит
    меньше `floor` (мало для переключения при обрыве), кап ослабляется
    постепенно (cap+1, cap+2, ... до max_cap) — ровно настолько, чтобы дотянуть
    до floor. Возвращает (список, фактически_использованный_кап).
    """
    strict = pick_diverse(servers, limit, cap=cap)
    if not floor or len(strict) >= floor or max_cap <= cap:
        return strict, cap
    # если размер ограничен ЛИМИТОМ, а не капом, ослаблять кап бессмысленно:
    # больше узлов всё равно не возьмём, зато потеряем разнообразие
    if len(strict) >= limit or len(strict) >= len(servers):
        return strict, cap
    best, best_cap = strict, cap
    for c in range(cap + 1, max_cap + 1):
        cand = pick_diverse(servers, limit, cap=c)
        best, best_cap = cand, c
        if len(cand) >= floor:
            break
    return best, best_cap


def subnet_stats(servers: list) -> dict:
    """Сколько узлов в каждой подсети (для логов)."""
    out = {}
    for s in servers:
        k = sub24(getattr(s, "address", ""))
        out[k] = out.get(k, 0) + 1
    return out


# ------------------------------------------------------------------ cloudflare

def _state_path(cfg: dict = None) -> str:
    """Кэш диапазонов: state_dir из конфига, иначе state/ рядом с проектом."""
    try:
        sd = (cfg or {}).get("paths", {}).get("state_dir")
        if sd:
            return os.path.join(sd, "cf_ranges.json")
    except Exception:
        pass
    return os.path.join("state", "cf_ranges.json")


def _parse_nets(items) -> list:
    nets = []
    for it in items or []:
        try:
            nets.append(ipaddress.ip_network(str(it).strip(), strict=False))
        except Exception:
            continue
    return nets


def cf_ranges(cfg: dict = None, refresh: bool = True) -> list:
    """Диапазоны Cloudflare: из кэша state/cf_ranges.json, иначе из сети,
    иначе встроенный список. Никогда не бросает исключений."""
    global _NETS
    if _NETS is not None:
        return _NETS
    path = _state_path(cfg)
    nets, saved = None, 0
    try:
        if os.path.isfile(path):
            d = json.load(open(path, encoding="utf-8"))
            saved = float(d.get("ts", 0) or 0)
            nets = _parse_nets(d.get("v4"))
    except Exception:
        nets, saved = None, 0
    fresh = nets and (time.time() - saved) < CF_REFRESH_S
    if not fresh and refresh:
        try:
            import urllib.request
            req = urllib.request.Request(CF_URL, headers={"User-Agent": "curl/8"})
            body = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
            got = [ln.strip() for ln in body.splitlines() if "/" in ln]
            if len(got) >= 5:
                nets = _parse_nets(got)
                try:
                    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
                    json.dump({"ts": time.time(), "v4": got}, open(path, "w", encoding="utf-8"))
                except Exception:
                    pass
        except Exception:
            pass
    if not nets:
        nets = _parse_nets(BUNDLED_CF_V4)
    _NETS = nets
    return _NETS


def is_cloudflare(addr: str, cfg: dict = None, extra_nets: list = None) -> bool:
    """Адрес узла принадлежит сетям Cloudflare? Хостнеймы резолвим (с кэшем)."""
    a = str(addr or "").strip()
    if not a:
        return False
    nets = list(extra_nets) if extra_nets else cf_ranges(cfg)
    try:
        ip = ipaddress.ip_address(a)
        return any(ip in n for n in nets)
    except ValueError:
        pass
    if a in _DNS_CACHE:
        return _DNS_CACHE[a]
    verdict = False
    try:
        infos = socket.getaddrinfo(a, None)
        addrs = {i[4][0] for i in infos}
        for s in addrs:
            try:
                ip = ipaddress.ip_address(s)
            except ValueError:
                continue
            if any(ip in n for n in nets):
                verdict = True
                break
    except Exception:
        verdict = False
    _DNS_CACHE[a] = verdict
    return verdict


def drop_cloudflare(servers: list, cfg: dict = None) -> tuple:
    """Убирает узлы, чей адрес в сетях Cloudflare. Возвращает (оставшиеся, отброшенные)."""
    if not (cfg or {}).get("blacklist", {}).get("cloudflare_nodes", True):
        return list(servers), []
    nets = cf_ranges(cfg)
    kept, dropped = [], []
    for s in servers:
        if is_cloudflare(getattr(s, "address", ""), cfg, extra_nets=nets):
            dropped.append(s)
        else:
            kept.append(s)
    return kept, dropped
