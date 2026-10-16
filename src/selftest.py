# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Автотесты FOREST's Proxy Auto-updater (GPL-3.0).

Запуск:  python v2ray_updater.py --selftest   (или  python selftest.py)

Проверяет то, что не требует сети и живого ядра: API-поверхность, стор
серверов, генерацию конфигов ядра и балансировщика, диспетчер режимов,
i18n, первый запуск конфига, поиск ядра. Системный прокси НЕ трогается,
боевые порты НЕ занимаются — всё пишется в отдельный временный каталог.
"""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="forest_selftest_")
os.environ["FOREST_ROOT"] = _TMP          # не трогаем реальный %LOCALAPPDATA%
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json  # noqa: E402

import clientwrite as CW  # noqa: E402
import config as CFG  # noqa: E402
import i18n  # noqa: E402
import log  # noqa: E402
import parser as P  # noqa: E402

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def main() -> int:
    log.reset_logger(os.path.join(_TMP, "logs"))
    print("=" * 64)
    print("1. API-поверхность (имена, которые зовут v2ray_updater/watch)")
    print("=" * 64)
    needed = ["AUTO_TAG", "StateStore", "probe_client", "measure_speed_kbps",
              "ensure_port_free", "ensure_balancer", "update_hotcache",
              "row_to_server", "read_db_rows", "read_active_id", "write_active_id",
              "guard_cycle", "bl_filter", "activate", "kill_kernels",
              "write_core_config", "write_balancer_config", "restart_core",
              "wait_and_probe", "balancer_pool", "server_to_row", "port_busy",
              "build_balancer_config", "geo_asset_dir", "ru_direct_enabled",
              "proxy_off", "set_proxy_off", "save_proxy_orig", "restore_system_proxy",
              "start_core", "stop_core", "ensure_system_proxy", "write_bin_config"]
    for n in needed:
        check(f"есть {n}", hasattr(CW, n))

    print()
    print("=" * 64)
    print("2. server_to_row -> row_to_server (round-trip по протоколам)")
    print("=" * 64)
    cases = [("vless", "1.2.3.4", 443, "ws"),
             ("vmess", "5.6.7.8", 8443, "raw"),
             ("trojan", "9.9.9.9", 2053, "grpc"),
             ("ss", "10.0.0.1", 8388, "raw")]
    for proto, addr, port, net in cases:
        s = P.Server(protocol=proto, address=addr, port=port)
        s.password = "SECRET"
        s.remark = f"{proto}-node"
        s.network = net
        s.host = "example.com"
        s.path = "/path"
        s.sni = "sni.example.com"
        s.stream_security = "tls"
        s._row_index_id = "42"
        if proto == "ss":
            s.method = "aes-256-gcm"
        if proto == "vmess":
            s.method = "auto"
        row = CW.server_to_row(s)
        s2 = CW.row_to_server(row)
        ok = (s2 is not None and s2.address == addr and s2.port == port
              and s2.protocol == proto and s2.host == s.host and s2.path == s.path
              and s2.sni == s.sni and s2.password == "SECRET")
        check(f"{proto}: адрес/порт/протокол/транспорт", ok,
              f"got {s2.protocol if s2 else None} {s2.address if s2 else None}")

    print()
    print("=" * 64)
    print("3. Стор серверов (запись/чтение, [AUTO]-тег)")
    print("=" * 64)
    store = os.path.join(_TMP, "servers.json")
    s = P.Server(protocol="vless", address="1.1.1.1", port=443)
    s.password = "uuid-1"
    s.remark = "node A"
    s._row_index_id = "1"
    n = CW.write_auto_group(store, [s], update_stats=False)
    check("write_auto_group вернул 1", n == 1, f"n={n}")
    rows = CW.read_db_rows(store)
    check("store прочитан (1 строка)", len(rows) == 1, f"len={len(rows)}")
    check("[AUTO]-тег выставлен", (rows[0].get("Remarks") or "").startswith(CW.AUTO_TAG),
          rows[0].get("Remarks") if rows else "—")
    with open(store, encoding="utf-8") as f:
        data = json.load(f)
    check("формат store {servers,active_id,next_index}",
          all(k in data for k in ("servers", "active_id", "next_index")))
    CW.write_active_id(os.path.join(_TMP, "forest_xray.json"), "1")
    check("write/read_active_id (standalone)", CW.read_active_id(os.path.join(_TMP, "forest_xray.json")) == "1")

    print()
    print("=" * 64)
    print("4. Генерация конфига ядра (один сервер)")
    print("=" * 64)
    cfg_path = os.path.join(_TMP, "xray_config.json")
    client = {"cfg": cfg_path, "socks_port": 11808, "torrent_port": 11820, "mode": "standalone"}
    srv = P.Server(protocol="vless", address="1.2.3.4", port=443)
    srv.password = "uuid-x"
    srv.network = "ws"
    srv.host = "h.com"
    srv.path = "/p"
    ok = CW.write_core_config(client, srv, {"client": {}})
    check("write_core_config вернул True", ok)
    with open(cfg_path, encoding="utf-8") as f:
        conf = json.load(f)
    check("есть inbounds (mixed socks на 11808)", any(
        i.get("protocol") == "mixed" and i.get("port") == 11808
        for i in conf.get("inbounds", [])))
    check("есть outbound с тегом proxy", any(
        o.get("tag") == "proxy" for o in conf.get("outbounds", [])))
    check("есть outbound direct (freedom)", any(
        o.get("protocol") == "freedom" for o in conf.get("outbounds", [])))
    ob = [o for o in conf["outbounds"] if o.get("tag") == "proxy"][0]
    check("outbound vless использует settings.vnext", "vnext" in ob.get("settings", {}))

    print()
    print("=" * 64)
    print("5. Генерация конфига балансировщика (пул + observatory)")
    print("=" * 64)
    pool = []
    for i in range(3):
        x = P.Server(protocol="vless", address=f"10.0.0.{i+1}", port=443)
        x.password = f"uuid-{i}"
        pool.append(x)
    ok = CW.write_balancer_config(client, pool, {"client": {}})
    check("write_balancer_config вернул True", ok)
    with open(cfg_path, encoding="utf-8") as f:
        bconf = json.load(f)
    tags = [o.get("tag") for o in bconf.get("outbounds", [])]
    check("пул из 3 outbound с префиксом proxy-out-",
          sum(1 for t in tags if t and t.startswith("proxy-out-")) == 3, f"tags={tags}")
    check("есть routing.balancers с selector ['proxy-out']",
          any(b.get("selector") == ["proxy-out"]
              for b in bconf.get("routing", {}).get("balancers", [])))
    check("есть observatory (нативный health-check)",
          "observatory" in bconf and
          bconf["observatory"].get("subjectSelector") == ["proxy-out"])
    check("есть правило маршрутизации на балансировщик",
          any(r.get("balancerTag") == "bal" for r in bconf.get("routing", {}).get("rules", [])))
    tin = [i for i in bconf.get("inbounds", []) if i.get("tag") == "torrent-in"]
    check("есть вход torrent-in (порт 11820, socks, только 127.0.0.1)",
          bool(tin) and tin[0].get("port") == 11820
          and tin[0].get("listen") == "127.0.0.1" and tin[0].get("protocol") == "socks")
    check("torrent-in: UDP включён", bool(tin) and tin[0].get("settings", {}).get("udp") is True)
    rules_b = bconf.get("routing", {}).get("rules", [])
    check("ПЕРВОЕ правило — локальные имена напрямую",
          bool(rules_b) and rules_b[0].get("outboundTag") == "direct"
          and "full:retracker.local" in (rules_b[0].get("domain") or []))
    check("ВТОРОЕ правило — torrent-in через балансировщик",
          len(rules_b) > 1 and rules_b[1].get("inboundTag") == ["torrent-in"]
          and rules_b[1].get("balancerTag") == "bal")

    print()
    print("=" * 64)
    print("6. РФ-маршрутизация включается только при наличии гео-баз")
    print("=" * 64)
    geo_tmp = os.path.join(_TMP, "geo")
    os.makedirs(geo_tmp, exist_ok=True)
    open(os.path.join(geo_tmp, "geosite.dat"), "wb").close()
    open(os.path.join(geo_tmp, "geoip.dat"), "wb").close()
    old_env = os.environ.get("XRAY_LOCATION_ASSET")
    os.environ["XRAY_LOCATION_ASSET"] = geo_tmp
    try:
        check("geo_asset_dir находит базы по XRAY_LOCATION_ASSET",
              CW.geo_asset_dir() == geo_tmp)
        check("ru_direct_enabled=True при наличии баз",
              CW.ru_direct_enabled({"watch": {"ru_direct": True}}) is True)
        check("ru_direct_enabled=False по умолчанию (в конфиге выключено)",
              CW.ru_direct_enabled({"watch": {"ru_direct": False}}) is False)
        CW.write_balancer_config(client, pool, {"client": {}, "watch": {"ru_direct": True}})
        with open(cfg_path, encoding="utf-8") as f:
            ruconf = json.load(f)
        rrules = ruconf["routing"]["rules"]
        check("при ru_direct есть правило direct по доменам",
              any(r.get("outboundTag") == "direct" and r.get("domain") for r in rrules))
        check("при ru_direct есть правило direct по IP",
              any(r.get("outboundTag") == "direct" and r.get("ip") for r in rrules))
        check("порядок правил: local -> torrent -> RU",
              rrules[0].get("outboundTag") == "direct"
              and rrules[1].get("inboundTag") == ["torrent-in"])
        check("DNS согласован (expectIPs при ru_direct)",
              "expectIPs" in json.dumps(ruconf.get("dns", {}), ensure_ascii=False))
        check("domainStrategy=IPIfNonMatch",
              ruconf["routing"].get("domainStrategy") == "IPIfNonMatch")
    finally:
        if old_env is None:
            os.environ.pop("XRAY_LOCATION_ASSET", None)
        else:
            os.environ["XRAY_LOCATION_ASSET"] = old_env

    print()
    print("=" * 64)
    print("7. Диспетчер режимов (standalone / v2rayn)")
    print("=" * 64)
    check("_mode_of по client.mode=v2rayn", CW._mode_of({"mode": "v2rayn"}) == "v2rayn")
    check("_mode_of по cfg.client.mode=standalone",
          CW._mode_of(None, {"client": {"mode": "standalone"}}) == "standalone")
    check("_mode_of по умолчанию standalone", CW._mode_of({}) == "standalone")
    check("_is_v2rayn_path: guiNConfig.json", CW._is_v2rayn_path("X/guiNConfig.json") is True)
    check("_is_v2rayn_path: servers.json -> False", CW._is_v2rayn_path("X/servers.json") is False)
    check("read_db_rows(.json) читает наш стор", isinstance(CW.read_db_rows(store), list))
    try:
        import clientwrite_v2rayn as V2
        check("бэкенд v2rayN импортируется", hasattr(V2, "activate") and hasattr(V2, "ensure_balancer"))
    except Exception as e:
        check("бэкенд v2rayN импортируется", False, str(e))
    try:
        import clientwrite_posix as POS
        check("POSIX-бэкенд импортируется", hasattr(POS, "write_balancer_config"))
    except Exception as e:
        check("POSIX-бэкенд импортируется", False, str(e))

    print()
    print("=" * 64)
    print("8. Конфиг: первый запуск создаёт файл из config.example.json")
    print("=" * 64)
    ex = CFG.example_config_path()
    check("config.example.json доступен", bool(ex), str(ex))
    fresh = os.path.join(_TMP, "fresh_root", "config.json")
    cfg2 = CFG.load_config(fresh)
    check("config.json создан при первом запуске", os.path.isfile(fresh))
    check("дефолт client.mode=standalone", cfg2["client"]["mode"] == "standalone")
    check("дефолт diversity.per_subnet_cap=1", cfg2["diversity"]["per_subnet_cap"] == 1)
    check("дефолт diversity.min_pool_after_cap=12", cfg2["diversity"]["min_pool_after_cap"] == 12)
    check("дефолт watch.ru_direct выключен", cfg2["watch"]["ru_direct"] is False)
    check("дефолт test.min_speed_kbps=1000", int(cfg2["test"]["min_speed_kbps"]) == 1000)
    check("дефолт test.gate_urls пуст (без шлюза Cloudflare)", not cfg2["test"].get("gate_urls"))
    check("порты по умолчанию 10808/10820",
          cfg2["client"]["socks_port"] == 10808 and cfg2["client"]["torrent_port"] == 10820)
    check("paths развёрнуты (state_dir/log_dir)", "state_dir" in cfg2["paths"] and "log_dir" in cfg2["paths"])

    print()
    print("=" * 64)
    print("9. Поиск ядра и прочее")
    print("=" * 64)
    dummy = os.path.join(_TMP, "xray.exe")
    open(dummy, "wb").close()
    check("find_core берёт явный путь из конфига",
          CFG.find_core({"client": {"core": dummy}}) == dummy)
    check("find_client standalone отдаёт стор и конфиг",
          "servers.json" in CFG.find_client({"client": {"mode": "standalone"},
                                             "paths": cfg2["paths"]})["db"])
    sig1 = CW._pool_sig(pool)
    check("_pool_sig стабилен", sig1 == CW._pool_sig(pool))
    check("port_busy(свободный порт 59999)=False", CW.port_busy(59999) is False)
    check("read_active_id без стора -> None/''",
          not CW._sa_read_active_id(os.path.join(_TMP, "nostore", "nope.json")))
    i18n.set_lang("en")
    check("i18n переключается на en", i18n.t("status.title") == "Status")
    i18n.set_lang("ru")
    check("i18n переключается на ru", i18n.t("status.title") == "Статус")
    # системный прокси только ЧИТАЕМ (не меняем)
    en, srv_p = CW._sys_proxy_state()
    check("системный прокси читается (не изменяется)", isinstance(en, bool))

    print()
    print("=" * 64)
    if FAILED:
        print(f"{i18n.t('selftest.failed')}: {len(FAILED)}")
        for f in FAILED:
            print(f"  - {f}")
        _cleanup()
        return 1
    print(i18n.t("selftest.passed"))
    print("=" * 64)
    _cleanup()
    return 0


def _cleanup():
    try:
        import shutil
        shutil.rmtree(_TMP, ignore_errors=True)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
