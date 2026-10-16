# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE or <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Проверки модулей трея и i18n (GPL-3.0).

Запуск:  python src/tray_check.py     (живой значок — ``python src/tray.py --test``)

Здесь проверяется то, что НЕ трогает живую систему: полнота двуязычного
каталога, валидность сгенерированных .ico, переключение фильтров в тестовом
config.json и отклик генератора конфига ядра на `watch.ru_direct`. Системный
прокси НЕ меняется, боевые порты НЕ занимаются, чужие процессы НЕ трогаются.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="forest_tray_check_")
os.environ["FOREST_ROOT"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clientwrite as CW          # noqa: E402
import config as CFG              # noqa: E402
import i18n as I                  # noqa: E402
import parser as P               # noqa: E402
import tray_icon as TI           # noqa: E402
import tray_menu as TM           # noqa: E402

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def _px(buf: bytes, size: int, x: int, y: int) -> tuple:
    """Пиксель BGRA буфера render_state."""
    i = (y * size + x) * 4
    return (buf[i], buf[i + 1], buf[i + 2], buf[i + 3])


def _t_header() -> None:
    print("=" * 64)


def main() -> int:
    # ─────────────────────────────────────────── 1. i18n ───
    _t_header()
    print("1. i18n: полный каталог RU+EN, переключение языка")
    _t_header()
    cc = I.check_complete()
    check("нет пустых переводов ru", not cc["ru"], str(cc["ru"]))
    check("нет пустых переводов en", not cc["en"], str(cc["en"]))
    check("нет ключей-дырок", not cc["missing"], str(cc["missing"]))
    keys = I.all_keys()
    check("каталог непустой (>= 60 строк)", len(keys) >= 60, f"={len(keys)}")
    # переключение даёт РАЗНЫЕ строки
    I.set_lang("ru")
    ru_title, ru_menu = I.t("status.title"), I.t("tray.menu.filters")
    I.set_lang("en")
    en_title, en_menu = I.t("status.title"), I.t("tray.menu.filters")
    check("ru/en дают разные строки (status.title)", ru_title != en_title,
          f"{ru_title!r} vs {en_title!r}")
    check("ru/en дают разные строки (tray.menu.filters)", ru_menu != en_menu,
          f"{ru_menu!r} vs {en_menu!r}")
    # все ключи меню/трея непусты в обоих языках
    menu_keys = [k for k in keys if k.startswith("tray.")]
    ok_both = True
    for k in menu_keys:
        I.set_lang("ru"); a = I.t(k)
        I.set_lang("en"); b = I.t(k)
        if not a.strip() or not b.strip():
            ok_both = False
            print(f"    пусто: {k}")
    check(f"все {len(menu_keys)} ключей tray.* непусты в ru и en", ok_both)
    # отсутствующий ключ возвращается как есть (не падает)
    check("неизвестный ключ -> сам ключ", I.t("nonexistent.key") == "nonexistent.key")
    check("tr() с подстановкой", I.tr("error.generic", err="X") == "Error: X"
          or I.tr("error.generic", err="X").startswith("Error"))
    I.set_lang("ru")

    # ─────────────────────────────────────────── 2. значки .ico ───
    _t_header()
    print("2. Значки: валидные .ico из пикселей (16x16 и 32x32)")
    _t_header()
    centres = {}
    for state in ("ok", "off", "error"):
        data = TI.state_ico(state)
        imgs = TI.ico_images(data)
        sizes = [w for w, _h, _o, _s in imgs]
        # проверяем сам заголовок ICO
        reserved, typ, count = TI._HEADER.unpack_from(data, 0)
        valid = (reserved == 0 and typ == 1 and count == 2 and sizes == [16, 32]
                 and all(o + s <= len(data) for _w, _h, o, s in imgs))
        check(f"[{state}] .ico валиден (header+2 записи 16/32)", valid,
              f"res={reserved} type={typ} n={count} sizes={sizes}")
        # пиксели: центр = цвет точки состояния, угол = прозрачный
        buf = TI.render_state(16, *TI.STATES[state])
        cpx = _px(buf, 16, 8, 8)
        corner = _px(buf, 16, 0, 0)
        centres[state] = cpx[:3]
        check(f"[{state}] центр значка — цвет состояния (BGR={cpx[:3]}, A={cpx[3]})",
              cpx[3] > 200, f"A={cpx[3]}")
        check(f"[{state}] угол прозрачный (A={corner[3]})", corner[3] == 0)
        # HICON из байтов (в памяти) — если Windows
        if sys.platform == "win32":
            h, err = TI.make_hicon(data, 16)
            check(f"[{state}] HICON из байтов .ico", bool(h), err)
            TI.destroy_hicon(h)
    check("три состояния значка визуально РАЗНЫЕ",
          len({centres["ok"], centres["off"], centres["error"]}) == 3,
          str(centres))

    # ─────────────────────────────────────────── 3. фильтры ───
    _t_header()
    print("3. Фильтры меню: переключение меняет ключи в config.json")
    _t_header()
    cfg_path = os.path.join(_TMP, "config.json")
    dummy_core = os.path.join(_TMP, "xray.exe")
    open(dummy_core, "wb").close()
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"ui": {"lang": "ru"},
                   "client": {"mode": "standalone", "socks_port": 11808,
                              "core": dummy_core},
                   "watch": {"ru_direct": False},
                   "blacklist": {"cloudflare_nodes": True}}, f, ensure_ascii=False)
    cfg = CFG.load_config(cfg_path)

    # ensure_balancer НЕ зовём по-настоящему (не трогаем ядро/прокси) —
    # подменяем и фиксируем, что он ВЫЗВАН штатным путём с force=True
    calls = []
    orig_eb = CW.ensure_balancer
    CW.ensure_balancer = lambda client, c, **kw: (calls.append(kw), True)[1]
    try:
        actions = TM.TrayActions(cfg)
        check("ru_direct исходно False", actions.ru_direct() is False)
        actions.toggle_ru_direct()
        after = json.load(open(cfg_path, encoding="utf-8"))
        check("config.json: watch.ru_direct -> True", after["watch"]["ru_direct"] is True)
        check("ядро применено штатным путём (ensure_balancer force=True)",
              bool(calls) and calls[0].get("force") is True, str(calls))
        actions.toggle_ru_direct()      # обратно False
        after = json.load(open(cfg_path, encoding="utf-8"))
        check("config.json: watch.ru_direct -> False (обратно)", after["watch"]["ru_direct"] is False)

        check("cloudflare_nodes исходно True", actions.cloudflare() is True)
        actions.toggle_cloudflare()
        after = json.load(open(cfg_path, encoding="utf-8"))
        check("config.json: blacklist.cloudflare_nodes -> False",
              after["blacklist"]["cloudflare_nodes"] is False)
        # подсказка/меню отражают состояние
        labels = actions.menu_labels()
        check("пункт меню фильтра показывает состояние",
              "(" in labels["filter_cf"] or "—" in labels["filter_cf"]
              or labels["filter_cf"].strip() != I.t("tray.menu.filter_cf"))
    finally:
        CW.ensure_balancer = orig_eb

    # триггер «обновить серверы сейчас» (тот же протокол, что stop.flag)
    actions.request_refresh()
    check("refresh.flag создан", os.path.isfile(TM.refresh_trigger_path(cfg)))
    check("consume_refresh_trigger читает и снимает флаг",
          TM.consume_refresh_trigger(cfg) is True
          and not os.path.isfile(TM.refresh_trigger_path(cfg)))
    check("повторное чтение -> False", TM.consume_refresh_trigger(cfg) is False)

    # ─────────────────────────────────────────── 4. ru_direct -> конфиг ядра ───
    _t_header()
    print("4. Генератор конфига ядра отзывается на watch.ru_direct")
    _t_header()
    geo = os.path.join(_TMP, "geo")
    os.makedirs(geo, exist_ok=True)
    open(os.path.join(geo, "geosite.dat"), "wb").close()
    open(os.path.join(geo, "geoip.dat"), "wb").close()
    old_env = os.environ.get("XRAY_LOCATION_ASSET")
    os.environ["XRAY_LOCATION_ASSET"] = geo
    try:
        core_cfg = os.path.join(_TMP, "forest_xray.json")
        client = {"cfg": core_cfg, "socks_port": 11808, "torrent_port": 11820,
                  "mode": "standalone", "core": dummy_core}
        srv = P.Server(protocol="vless", address="1.2.3.4", port=443)
        srv.password = "11111111-1111-1111-1111-111111111111"
        srv.remark = "node"
        pool = [srv]
        CW.write_balancer_config(client, pool, {"client": {}, "watch": {"ru_direct": False}})
        off = json.load(open(core_cfg, encoding="utf-8"))
        CW.write_balancer_config(client, pool, {"client": {}, "watch": {"ru_direct": True}})
        on = json.load(open(core_cfg, encoding="utf-8"))
        on_txt = json.dumps(on.get("routing", {}), ensure_ascii=False) + json.dumps(on.get("dns", {}), ensure_ascii=False)
        off_txt = json.dumps(off.get("routing", {}), ensure_ascii=False)
        check("ru_direct=True: есть правила по РФ-доменам",
              "geosite:category-ru" in on_txt)
        check("ru_direct=True: есть правило geoip:ru",
              "geoip:ru" in on_txt)
        check("ru_direct=True: DNS согласован (expectIPs)",
              "expectIPs" in json.dumps(on.get("dns", {}), ensure_ascii=False))
        check("ru_direct=False: правила РФ отсутствуют",
              "geoip:ru" not in off_txt and "geosite:category-ru" not in off_txt)
    finally:
        if old_env is None:
            os.environ.pop("XRAY_LOCATION_ASSET", None)
        else:
            os.environ["XRAY_LOCATION_ASSET"] = old_env

    # ─────────────────────────────── 5. канал состояния -> значок ───
    _t_header()
    print("5. Канал состояния (state/tray_status.json) -> значок/подсказка")
    _t_header()
    import time as _time
    sd = cfg["paths"]["state_dir"]
    stf = os.path.join(sd, "tray_status.json")
    off_flag = TM.proxy_off_flag_path(cfg)
    act = TM.TrayActions(cfg)

    def _write_state(state, tip="t", ts=None):
        with open(stf, "w", encoding="utf-8") as f:
            json.dump({"ts": _time.time() if ts is None else ts,
                       "state": state, "tip": tip}, f, ensure_ascii=False)

    _write_state("ok")
    check("state=ok -> значок ok", act.icon_state() == "ok", act.icon_state())
    _write_state("switch")
    check("state=switch -> ok (работает)", act.icon_state() == "ok")
    _write_state("restoring")
    check("state=restoring -> ok (работает)", act.icon_state() == "ok")
    _write_state("down")
    check("state=down -> error (обрыв)", act.icon_state() == "error", act.icon_state())
    _write_state("error")
    check("state=error -> error", act.icon_state() == "error")
    _write_state("off")
    check("state=off -> off", act.icon_state() == "off")
    _write_state("ok", ts=0)
    check("устаревший статус (>90 с) -> error", act.icon_state() == "error", act.icon_state())
    # флаг ручного выключения — источник истины (важнее файла состояния)
    _write_state("ok")
    open(off_flag, "w", encoding="utf-8").write("test")
    check("proxy_off.flag -> off даже при state=ok", act.icon_state() == "off", act.icon_state())
    check("подсказка значка <= 63 символов (лимит Windows)", len(act.tip()) <= 63,
          str(len(act.tip())))
    os.remove(off_flag)
    _write_state("ok")
    check("флаг снят -> снова ok", act.icon_state() == "ok")
    check("подсказка содержит состояние (tray.tip.ok)", act.tip().startswith(I.t("tray.tip.ok")),
          act.tip())

    # ─────────────────────────────────────────── итог ───
    print()
    _t_header()
    if FAILED:
        print(f"{I.t('selftest.failed')}: {len(FAILED)}")
        for f in FAILED:
            print(f"  - {f}")
        _t_header()
        return 1
    print("TRAY+I18N: " + I.t("selftest.passed"))
    _t_header()
    return 0


if __name__ == "__main__":
    sys.exit(main())
