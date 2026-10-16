"""clientwrite_posix.py — POSIX-версия standalone-бэкенда (CachyOS / Linux).

FOREST's Proxy Auto-updater (GPL-3.0).

Здесь ядро xray — самостоятельный systemd-сервис, поэтому жизненный цикл
сводится к `write config -> systemctl --user restart xray-proxy -> probe`.
На Windows тот же standalone-подход реализован в clientwrite.py через
управление процессом xray.exe. Модуль сохранён для будущего порта на Linux.

Заменяет интеграцию с v2rayN на работу с ядром **xray как systemd-сервисом**.

Почему так проще, чем на Windows: там ядро поднимает GUI v2rayN, и скрипт
вынужден «бороться» с ним за порт 10808 (tasklist/kill/Reload/gui_restart_*).
На Linux ядро — самостоятельный сервис, поэтому вся эта логика исчезает:
пишем конфиг → `systemctl --user restart xray-proxy` → проверяем порт.

Совместимость: модуль предоставляет ТОТ ЖЕ API, что `clientwrite.py`
(AUTO_TAG, StateStore, probe_client, activate, guard_cycle, ensure_balancer,
read_db_rows, read_active_id, bl_filter, row_to_server, measure_speed_kbps…),
поэтому `v2ray_updater.py` и `watch.py` работают без правок — достаточно
переключить импорт (см. `switch_to_posix.sh`).

Что переиспользуется из `clientwrite.py` без изменений (переносимые части):
  probe_client, measure_speed_kbps, port_works, _curl_*, bl_add/bl_active/
  bl_filter, row_to_server, _json_safe, StateStore, update_hotcache.
"""
from __future__ import annotations

import json
import os
import shutil
import re
import subprocess
import time

import log

# переносимые части — из Windows-модуля (без побочных эффектов при импорте)
from clientwrite import (LOCAL_DIRECT_DOMAINS, AUTO_TAG, PROBE_URL, PROBE_DATA_URL, PROBE_DATA_MIN_BYTES,
                         _curl_metrics, _curl_speed, measure_speed_kbps, port_works,
                         probe_client, bl_add, bl_active, bl_filter, row_to_server,
                         bl_add_pool,
                         _json_safe, StateStore, update_hotcache,
                         RU_DIRECT_DOMAINS, RU_DIRECT_IPS, _build_dns)

# POSIX-конфиг (ядро xray, свой store серверов) — читаем каталог состояния из
# общего config.py, чтобы пути совпадали с остальной программой.
import config as CFG                                  # type: ignore

# ── соответствие протокол <-> ConfigType (как в v2rayN) ──
CONFIG_TYPE = {"vless": 5, "vmess": 1, "trojan": 6, "ss": 3}
CONFIG_TYPE_INV = {v: k for k, v in CONFIG_TYPE.items()}

DEFAULT_SOCKS_PORT = 10808


# ══════════════════════════════════════════ store серверов (JSON) ═══
def _store_load(path: str) -> dict:
    """Читает JSON-store серверов. Формат: {next_index, active_id, servers:[]}."""
    if not os.path.isfile(path):
        return {"next_index": 1, "active_id": "", "servers": []}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and "servers" in d:
            return d
        if isinstance(d, list):                       # допустим просто список
            return {"next_index": len(d) + 1, "active_id": "", "servers": d}
    except Exception:
        pass
    return {"next_index": 1, "active_id": "", "servers": []}


def _store_save(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_db_rows(db_path: str) -> list:
    """Аналог чтения guiNDB.db — на Linux читает наш JSON-store серверов."""
    return list(_store_load(db_path).get("servers") or [])


def server_to_row(s) -> dict:
    """Server -> строка в формате, понятном row_to_server (обратная функция)."""
    proto = getattr(s, "protocol", "") or ""
    pe, te = {}, {}
    if proto == "ss":
        pe["SsMethod"] = getattr(s, "method", "") or ""
    elif proto == "vmess":
        pe["VmessSecurity"] = getattr(s, "method", "auto") or "auto"
        pe["AlterId"] = str(getattr(s, "alter_id", "0") or "0")
    pe["Flow"] = getattr(s, "flow", "") or ""
    net = getattr(s, "network", "raw") or "raw"
    if net == "raw":
        te["RawHeaderType"] = getattr(s, "header_type", "none") or "none"
        te["Host"] = getattr(s, "host", "") or ""
        te["Path"] = getattr(s, "path", "") or ""
    elif net in ("ws", "httpupgrade", "xhttp"):
        te["Host"] = getattr(s, "host", "") or ""
        te["Path"] = getattr(s, "path", "/") or "/"
    elif net == "kcp":
        te["KcpHeaderType"] = getattr(s, "header_type", "none") or "none"
        te["KcpSeed"] = getattr(s, "kcp_seed", "") or ""
    elif net == "grpc":
        te["GrpcAuthority"] = getattr(s, "host", "") or ""
        te["GrpcServiceName"] = getattr(s, "path", "") or ""
        te["GrpcMode"] = getattr(s, "header_type", "gun") or "gun"
    return {
        "IndexId": str(getattr(s, "_row_index_id", None) or getattr(s, "index_id", "") or ""),
        "Remarks": (AUTO_TAG + (getattr(s, "remark", "") or "")) if not (
            getattr(s, "remark", "") or "").startswith(AUTO_TAG) else getattr(s, "remark", ""),
        "Address": getattr(s, "address", "") or "",
        "Port": int(getattr(s, "port", 0) or 0),
        "ConfigType": CONFIG_TYPE.get(proto, 5),
        "Password": getattr(s, "password", "") or "",
        "Network": net,
        "StreamSecurity": getattr(s, "stream_security", "") or "",
        "Sni": getattr(s, "sni", "") or "",
        "Alpn": getattr(s, "alpn", "") or "",
        "Fingerprint": getattr(s, "fingerprint", "") or "",
        "PublicKey": getattr(s, "public_key", "") or "",
        "ShortId": getattr(s, "short_id", "") or "",
        "SpiderX": getattr(s, "spider_x", "") or "",
        "AllowInsecure": "1" if getattr(s, "allow_insecure", False) else "",
        # Speed — МБ/с, Delay — мс: тот же формат, что в ProfileExItem у v2rayN,
        # чтобы row_to_server вернул их обратно. Без этого фильтр по скорости в
        # пуле был пустышкой и в пул попадали CF-заглушки.
        "Speed": round(float(getattr(s, "speed_kbps", 0) or 0) / 1024.0, 2),
        "Delay": int(getattr(s, "rtt_ms", 0) or 0),
        "ProtoExtra": pe,
        "TransportExtra": te,
    }


def write_auto_group(db_path: str, servers: list, update_stats: bool = True) -> int:
    """Пишет [AUTO]-серверы в store. Возвращает число записанных."""
    data = _store_load(db_path)
    existing = {str(r.get("IndexId")): r for r in (data.get("servers") or [])
                if not (r.get("Remarks") or "").startswith(AUTO_TAG)}
    rows = list(existing.values())
    nxt = int(data.get("next_index", 1))
    written = 0
    for s in servers:
        row = server_to_row(s)
        if not row.get("IndexId"):
            row["IndexId"] = str(nxt)
            nxt += 1
        rows.append(row)
        written += 1
    data["servers"] = rows
    data["next_index"] = nxt
    _store_save(db_path, data)
    return written


def read_active_id(cfg_path: str):
    """Активный сервер: читаем из store рядом с конфигом ядра."""
    store = os.path.join(os.path.dirname(cfg_path) or ".", "..", "state", "servers.json")
    store = os.path.normpath(store)
    for cand in (store, os.path.join(os.path.dirname(cfg_path) or ".", "servers.json")):
        if os.path.isfile(cand):
            return _store_load(cand).get("active_id") or None
    return None


def write_active_id(cfg_path: str, index_id: str) -> None:
    """Записывает активный сервер в store (совместимо с read_active_id)."""
    store = os.path.normpath(os.path.join(os.path.dirname(cfg_path) or ".",
                                          "..", "state", "servers.json"))
    if not os.path.isfile(store):
        alt = os.path.join(os.path.dirname(cfg_path) or ".", "servers.json")
        store = alt if os.path.isfile(alt) else store
    data = _store_load(store)
    data["active_id"] = str(index_id)
    _store_save(store, data)


# ══════════════════════════════════════════ процессы / порт (POSIX) ═══
def _port_pid(port: int):
    """PID процесса, слушающего порт (ss, fallback lsof)."""
    try:
        r = subprocess.run(["ss", "-lptnH", f"sport = :{port}"],
                           capture_output=True, text=True, timeout=10)
        import re
        m = re.search(r"pid=(\d+)", r.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    try:
        r = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True,
                           text=True, timeout=10)
        out = (r.stdout or "").strip().splitlines()
        if out:
            return out[0].strip()
    except Exception:
        pass
    return None


def _pid_alive(pid: int) -> bool:
    """Жив ли процесс (POSIX: signal 0). Зеркало clientwrite._pid_alive."""
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True


def port_listening(port: int, timeout: float = 0.5) -> bool:
    """Алиас port_busy: общий watch.py использует имя из clientwrite.py.

    Без него пульс сторожа молча не работал бы на Linux (AttributeError глотался
    бы в except), и восстановление осталось бы медленным.
    """
    return port_busy(port, timeout=timeout)


def port_busy(port: int, timeout: float = 0.4) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def kill_kernels(cfg: dict = None, why: str = "") -> None:
    """Снимает процессы ядра xray/v2ray (pkill). GUI на Linux нет."""
    lg = log.get_logger()
    for name in ("xray", "v2ray"):
        try:
            r = subprocess.run(["pkill", "-f", name], capture_output=True, timeout=15)
            if r.returncode == 0:
                lg.warn(f"kill_kernels{'(' + why + ')' if why else ''}: снят процесс {name}")
        except Exception as e:
            lg.warn(f"kill_kernels({name}): {e}")
    port = DEFAULT_SOCKS_PORT
    try:
        port = int((cfg or {}).get("client", {}).get("socks_port", port)) or port
    except Exception:
        pass
    for _ in range(12):
        if not port_busy(port):
            return
        time.sleep(0.5)
    lg.warn(f"kill_kernels: порт {port} всё ещё занят")


def ensure_port_free(client: dict, cfg: dict) -> bool:
    """На Linux порт принадлежит нашему сервису — просто проверяем занятость."""
    port = int(client.get("socks_port", DEFAULT_SOCKS_PORT))
    if not port_busy(port):
        return True
    # занят — значит ядро уже работает; это нормально (не «чужая» программа)
    return True


# ══════════════════════════════════════════ конфиг ядра xray ═══
def _inbound(port: int, listen: str = "127.0.0.1") -> dict:
    return {"tag": "socks-in", "port": int(port), "listen": listen,
            "protocol": "mixed", "settings": {"udp": True, "auth": "noauth"}}


# Второй вход — СТРОГО для торрент-клиента (qBittorrent). Трекер-анонсы всегда
# идут через пул прокси, без RU-исключений (иначе трекер с российским доменом
# ушёл бы напрямую и остался заблокированным). Слушает только локально.
# P2P-обмен через него не идёт: клиент не проксирует peer-соединения.
TORRENT_PORT = 10820


def _inbound_torrent(port: int = TORRENT_PORT) -> dict:
    return {"tag": "torrent-in", "port": int(port), "listen": "127.0.0.1",
            "protocol": "socks", "settings": {"udp": True, "auth": "noauth"}}


# где ищем базы geosite.dat / geoip.dat (нужны для правил geosite:/geoip:)
GEO_CANDIDATES = ("/usr/share/xray", "/usr/local/share/xray", "/usr/share/v2ray",
                  "/opt/xray/share", "/opt/xray")


def geo_asset_dir() -> str | None:
    """Каталог с geosite.dat и geoip.dat или None.

    xray ищет базы рядом со своим бинарём либо в XRAY_LOCATION_ASSET; пакеты
    дистрибутива кладут их в /usr/share/xray.
    """
    cands = []
    env = os.environ.get("XRAY_LOCATION_ASSET")
    if env:
        cands.append(env)
    core = shutil.which("xray") or shutil.which("v2ray")
    if core:
        cands.append(os.path.dirname(os.path.realpath(core)))
    cands.extend(GEO_CANDIDATES)
    for d in cands:
        if d and os.path.isfile(os.path.join(d, "geosite.dat")) \
             and os.path.isfile(os.path.join(d, "geoip.dat")):
            return d
    return None


def ru_direct_enabled(cfg: dict) -> bool:
    """Нужна ли маршрутизация «РФ → напрямую».

    Включаем ТОЛЬКО если базы geosite/geoip реально найдены: без них ядро
    падает с `failed to open geosite.dat` и связи не будет вообще. Если баз нет —
    работаем как раньше (всё через пул прокси) и пишем предупреждение.
    """
    want = bool((cfg or {}).get("watch", {}).get("ru_direct", True))
    if not want:
        return False
    if geo_asset_dir():
        return True
    log.get_logger().warn(
        "ru_direct включён, но geosite.dat/geoip.dat не найдены — "
        "правила РФ→direct отключены (весь трафик через прокси)")
    return False


def _routing_posix(ru_direct: bool, target: dict, balancer: bool = False) -> dict:
    """Правила маршрутизации. Порядок КРИТИЧЕН.

    1. торрент-вход — ПЕРВЫМ и всегда в пул прокси (иначе правила РФ→direct
       перехватят российские трекеры и анонсы уйдут мимо прокси);
    2. российские домены → direct;
    3. российские IP → direct;
    4. всё остальное → target (outboundTag одиночного ядра либо balancerTag).
    """
    rules = [{"type": "field", "outboundTag": "direct",
              "domain": LOCAL_DIRECT_DOMAINS},   # ПЕРВЫМ: локальные имена — напрямую
             {"type": "field", "inboundTag": ["torrent-in"], **target}]
    if ru_direct:
        rules.append({"type": "field", "outboundTag": "direct",
                      "domain": RU_DIRECT_DOMAINS})
        rules.append({"type": "field", "outboundTag": "direct",
                      "ip": RU_DIRECT_IPS})
    rules.append({"type": "field", "network": "tcp,udp", **target})
    out: dict = {"domainStrategy": "IPIfNonMatch", "rules": rules}
    if balancer:
        out["balancers"] = [{"tag": "auto-bal", "selector": ["proxy"],
                             "strategy": {"type": "leastPing"}}]
    return out


def write_core_config(client: dict, server, cfg: dict, listen: str = "127.0.0.1") -> bool:
    """Пишет конфиг ядра с ОДНИМ сервером (аналог write_bin_config)."""
    import xraytest as XT
    ob = XT.outbound_json(server)
    if ob is None:
        log.get_logger().error("write_core_config: outbound не собрался")
        return False
    ob = dict(ob)
    ob["tag"] = "proxy"
    port = int(client.get("socks_port", DEFAULT_SOCKS_PORT))
    ru = ru_direct_enabled(cfg)
    conf = {
        "log": {"loglevel": "warning"},
        "inbounds": [_inbound(port, listen), _inbound_torrent()],
        "outbounds": [ob, {"tag": "direct", "protocol": "freedom"}],
        "dns": _build_dns(ru),
        "routing": _routing_posix(ru, {"outboundTag": "proxy"}),
    }
    return _write_json(client.get("cfg"), conf)


def write_balancer_config(client: dict, servers: list, cfg: dict,
                          listen: str = "127.0.0.1") -> bool:
    """Пишет конфиг ядра с ПУЛОМ серверов и нативным балансировщиком xray.

    Это Linux-замена «balancer_mode» v2rayN: xray сам распределяет трафик по
    пулу и сам следит за здоровьем узлов через `observatory`.
    """
    import xraytest as XT
    port = int(client.get("socks_port", DEFAULT_SOCKS_PORT))
    outbounds = []
    for i, s in enumerate(servers):
        ob = XT.outbound_json(s)
        if ob is None:
            continue
        ob = dict(ob)
        ob["tag"] = f"proxy-{i}"          # префикс "proxy" ловит selector
        outbounds.append(ob)
    if not outbounds:
        log.get_logger().error("write_balancer_config: пул пуст")
        return False
    outbounds.append({"tag": "direct", "protocol": "freedom"})
    ru = ru_direct_enabled(cfg)
    conf = {
        "log": {"loglevel": "warning"},
        "inbounds": [_inbound(port, listen), _inbound_torrent()],
        "outbounds": outbounds,
        "dns": _build_dns(ru),
        "routing": _routing_posix(ru, {"balancerTag": "auto-bal"}, balancer=True),
        "observatory": {
            "subjectSelector": ["proxy"],
            "probeUrl": PROBE_URL,
            "probeInterval": "10s",
        },
    }
    return _write_json(client.get("cfg"), conf)


def _write_json(path: str, data: dict) -> bool:
    if not path:
        return False
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        log.get_logger().error(f"_write_json({path}): {e}")
        return False


def _systemctl(args: list, timeout: int = 30) -> bool:
    """Обёртка над systemctl --user (POSIX-аналог управления процессом ядра)."""
    try:
        r = subprocess.run(["systemctl", "--user"] + args, capture_output=True,
                           timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def restart_core(cfg: dict) -> bool:
    """Перезапуск ядра через systemd --user."""
    svc = cfg.get("client", {}).get("service", "xray-proxy")
    return _systemctl(["restart", svc])


def wait_and_probe(client: dict, attempts: int = 6, gap: float = 3.0) -> tuple:
    """Ждёт подъёма порта и проверяет связь."""
    lg = log.get_logger()
    for i in range(attempts):
        if port_busy(int(client.get("socks_port", DEFAULT_SOCKS_PORT))):
            ok, rtt = probe_client(client, timeout=8)
            if ok:
                return True, rtt
        if i < attempts - 1:
            time.sleep(gap)
    return False, 0.0


# ══════════════════════════════════════════ балансировщик ═══
def balancer_pool(client: dict, cfg: dict, n: int = 10,
                  min_speed_kbps: float = 0) -> list:
    """Топ-N серверов для пула: из hotcache, иначе из [AUTO] в store."""
    st = StateStore(cfg)
    cache = st.data.get("hotcache") or []
    pool = []
    for e in cache:
        # скорость 0 = трафик через сервер не шёл (CF-заглушка): в пул нельзя
        if not e.get("speed_kbps"):
            continue
        if min_speed_kbps and e["speed_kbps"] < min_speed_kbps:
            continue
        s = _row_to_server_from_cache(e)
        if s is not None:
            pool.append(s)
        if len(pool) >= n:
            return pool
    if len(pool) >= n:
        return pool
    # добираем из store
    for r in read_db_rows(client.get("db", "")):
        if not (r.get("Remarks") or "").startswith(AUTO_TAG):
            continue
        s = row_to_server(r)
        if s is None:
            continue
        # без подтверждённой скорости сервер в пул не берём (заглушки)
        if (getattr(s, "speed_kbps", 0) or 0) <= 0:
            continue
        if min_speed_kbps and (s.speed_kbps or 0) < min_speed_kbps:
            continue
        pool.append(s)
        if len(pool) >= n:
            break
    return pool[:n]


def _row_to_server_from_cache(e: dict):
    """Собирает Server из записи hotcache (адрес/порт/протокол)."""
    import parser as P
    try:
        s = P.Server(protocol=e.get("protocol", "vless"),
                     address=e.get("address", ""), port=int(e.get("port", 0)))
        s.remark = e.get("remark", "")
        s.rtt_ms = e.get("rtt_ms", 0)
        s.speed_kbps = e.get("speed_kbps", 0)
        return s if s.address and s.port > 0 else None
    except Exception:
        return None



def _lock(cfg: dict, name: str, ttl: float = 240.0, wait: float = 0.0) -> bool:
    """Файловый lock: ядром управляет только один процесс (watch/guard/auto)."""
    p = os.path.join(cfg["paths"]["state_dir"], f"{name}.lock")
    deadline = time.time() + wait
    while True:
        try:
            if os.path.isfile(p) and time.time() - os.path.getmtime(p) > ttl:
                os.unlink(p)
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            if time.time() >= deadline:
                return False
            time.sleep(0.5)
        except Exception:
            return False


def _unlock(cfg: dict, name: str) -> None:
    try:
        os.unlink(os.path.join(cfg["paths"]["state_dir"], f"{name}.lock"))
    except Exception:
        pass


def _validate_config(client: dict, cfg: dict) -> tuple:
    """Проверка конфига ядра ДО перезапуска сервиса: запуск на свободных портах.

    Невалидный конфиг раньше означал: сервис упал, связи нет.
    """
    import shutil as _sh
    import socket
    import tempfile
    core = client.get("exe") or "xray"
    if not os.path.isabs(core):
        core = _sh.which(core) or core
    cfg_path = os.path.expanduser(client.get("core_cfg") or DEFAULT_CORE_CFG)
    try:
        conf = json.load(open(cfg_path, encoding="utf-8"))
    except Exception as e:
        return False, f"конфиг не читается: {e}"
    test = json.loads(json.dumps(conf))
    for ib in test.get("inbounds", []):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", 0))
            ib["port"] = s.getsockname()[1]
        finally:
            s.close()
        ib["listen"] = "127.0.0.1"
    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="xray-validate-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(test, f, ensure_ascii=False)
    log_p = os.path.join(cfg["paths"]["state_dir"], "xray_validate.log")
    env_v = dict(os.environ)
    try:
        adir = geo_asset_dir()
        if adir:
            env_v["XRAY_LOCATION_ASSET"] = adir
    except Exception:
        pass
    try:
        with open(log_p, "w", encoding="utf-8") as lf:
            pv = subprocess.Popen([core, "run", "-c", tmp], stdout=lf,
                                  stderr=subprocess.STDOUT, env=env_v)
            time.sleep(2.0)
            alive = pv.poll() is None
            if alive:
                pv.kill()
            pv.wait(timeout=10)
        if alive:
            return True, ""
        tail = open(log_p, encoding="utf-8", errors="replace").read()[-300:]
        m = re.search(r"(failed to[^\n]{0,180})", tail)
        return False, (m.group(1) if m else tail.strip()[-180:])
    except Exception as e:
        return False, f"validate error: {e}"
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass



def ensure_system_proxy(client: dict, cfg: dict) -> bool:
    """Системный прокси (GNOME) должен смотреть на наш балансировщик.

    На Linux нет GUI, который гасит прокси, но режим может быть сброшен вручную
    или после обновления системы — тогда браузер ходит напрямую, а сторожа
    честно пишут «связь есть» (они проверяют трафик ЧЕРЕЗ прокси).
    """
    lg = log.get_logger()
    if proxy_off(cfg):
        return False          # выключено вручную: прокси не возвращаем
    if cfg.get("client", {}).get("manage_system_proxy", True) is False:
        return True
    if not shutil.which("gsettings"):
        return True
    port = int(client.get("socks_port", DEFAULT_SOCKS_PORT))

    def gget(schema, key):
        return subprocess.run(["gsettings", "get", schema, key], capture_output=True,
                              text=True, timeout=10).stdout.strip().strip("'")

    try:
        mode = gget("org.gnome.system.proxy", "mode")
        host = gget("org.gnome.system.proxy.socks", "host")
        prt = gget("org.gnome.system.proxy.socks", "port")
        if mode == "manual" and host in ("127.0.0.1", "localhost") and prt == str(port):
            return True
        for schema, key, val in (("org.gnome.system.proxy.socks", "host", "127.0.0.1"),
                                 ("org.gnome.system.proxy.socks", "port", str(port)),
                                 ("org.gnome.system.proxy", "mode", "manual")):
            subprocess.run(["gsettings", "set", schema, key, val], timeout=10)
        lg.warn(f"Системный прокси (GNOME) был '{mode}' — включил на 127.0.0.1:{port}")
        return True
    except Exception as e:
        lg.warn(f"системный прокси (GNOME): {e}")
        return False



def _link_ok(cfg: dict, port: int, fresh_s: float = 45.0) -> bool:
    """Живость связи по отметкам сторожа (как в clientwrite.py).

    Свежий провал -> False сразу (пересборка не откладывается заморозкой);
    свежий успех  -> True без сетевой проверки; отметок нет -> probe.
    """
    now = time.time()
    try:
        st = StateStore(cfg)
        fail_ts = float(st.data.get("last_probe_fail_ts", 0) or 0)
        if fail_ts and now - fail_ts <= fresh_s:
            return False
        ok_ts = float(st.data.get("last_probe_ok_ts", 0) or 0)
        if ok_ts and now - ok_ts <= fresh_s:
            return True
    except Exception:
        pass
    try:
        ok, _rtt = probe_client({"socks_port": int(port)}, timeout=8)
        return bool(ok)
    except Exception:
        return False


def proxy_off_path(cfg: dict) -> str:
    """Флаг РУЧНОГО отключения прокси (ставится вручную/из индикатора)."""
    return os.path.join(cfg["paths"]["state_dir"], "proxy_off.flag")


def proxy_off(cfg: dict) -> bool:
    """Прокси выключен вручную: автоподъём запрещён во всех циклах."""
    try:
        return os.path.isfile(proxy_off_path(cfg))
    except Exception:
        return False


def lastgood_path(cfg: dict) -> str:
    return os.path.join(cfg["paths"]["state_dir"], "lastgood_servers.json")


def save_lastgood(cfg: dict, servers: list) -> None:
    """Запомнить последний РАБОЧИЙ состав пула (аварийный конфиг)."""
    try:
        import dataclasses
        _write_json(lastgood_path(cfg),
                    {"ts": time.time(), "servers": [dataclasses.asdict(s) for s in servers]})
    except Exception:
        pass


def load_lastgood(cfg: dict) -> list:
    """Восстановить последний рабочий состав пула."""
    try:
        import dataclasses
        import json as _json
        import parser as P
        d = _json.load(open(lastgood_path(cfg), encoding="utf-8"))
        fields = {f.name for f in dataclasses.fields(P.Server)}
        out = []
        for row in (d.get("servers") or []):
            try:
                out.append(P.Server(**{k: v for k, v in row.items() if k in fields}))
            except Exception:
                pass
        return out
    except Exception:
        return []


def _emergency_restore(client: dict, cfg: dict, port: int) -> bool:
    """Аварийный подъём последнего рабочего состава (POSIX)."""
    lg = log.get_logger()
    st = StateStore(cfg)
    if time.time() - float(st.data.get("emergency_ts", 0) or 0) < 120:
        return False
    servers = load_lastgood(cfg)
    if not servers:
        lg.warn("аварийный конфиг: сохранённого рабочего состава нет")
        return False
    st.data["emergency_ts"] = time.time()
    st.save()
    lg.warn(f"АВАРИЙНЫЙ КОНФИГ: живых серверов нет — поднимаю последний рабочий "
            f"состав ({len(servers)} серверов)")
    if not _lock(cfg, "balancer", ttl=240, wait=8):
        return False
    try:
        if not write_balancer_config(client, servers, cfg):
            return False
        ok_v, err_v = _validate_config(client, cfg)
        if not ok_v:
            lg.error(f"аварийный конфиг невалиден ({err_v})")
            return False
        if not restart_core(cfg):
            return False
    finally:
        _unlock(cfg, "balancer")
    ok, rtt = wait_and_probe(client, attempts=6, gap=2.0)
    if ok:
        save_lastgood(cfg, servers)
        lg.info(f"аварийный конфиг: связь поднята (rtt={rtt} мс)")
    return ok


def ensure_balancer(client: dict, cfg: dict, n: int = 10,
                    force: bool = False) -> bool:
    """Поднимает пул серверов с балансировщиком xray. True — связь есть."""
    lg = log.get_logger()
    socks_port = int(client.get("socks_port", DEFAULT_SOCKS_PORT))
    if proxy_off(cfg):
        # РУЧНОЕ отключение: ядро и системный прокси не трогаем
        return True
    pool = balancer_pool(client, cfg, n=n,
                         min_speed_kbps=float(cfg.get("watch", {}).get(
                             "speed_min_kbps", 0) or 0))
    if not pool:
        lg.warn("ensure_balancer: пул пуст")
        # СТРАХОВКА: живых серверов нет и связи нет — последний рабочий состав
        if not _link_ok(cfg, socks_port) and _emergency_restore(client, cfg, socks_port):
            return True
        return False
    # до всех ранних return: иначе при замороженном пуле прокси не проверялся бы
    ensure_system_proxy(client, cfg)
    sig = _pool_sig(pool)
    st = StateStore(cfg)
    if not force and st.data.get("balancer_sig") == sig and _link_ok(cfg, socks_port):
        return True
    # ЗАМОРОЗКА ПУЛА: ядро живо и связь есть — состав не перетасовываем,
    # иначе каждый пересчёт скоростей = перезапуск сервиса = разрыв связи.
    freeze_s = float(cfg.get("watch", {}).get("pool_freeze_s", 10800))
    age = time.time() - float(st.data.get("balancer_ts", 0) or 0)
    if st.data.get("balancer_sig") and age < freeze_s and _link_ok(cfg, socks_port):
        if st.data.get("balancer_sig") != sig:
            lg.info("ensure_balancer: состав пула изменился, но ядро работает — "
                    f"пул заморожен ещё на {int((freeze_s - age) / 60)} мин")
        return True
    # один управляющий: без lock watch/guard/auto рвали сервис друг за другом
    if not _lock(cfg, "balancer", ttl=240, wait=8):
        lg.warn("ensure_balancer: другое управление ядром уже идёт — пропускаю цикл")
        return True
    try:
        if not write_balancer_config(client, pool, cfg):
            return False
        ok_v, err_v = _validate_config(client, cfg)
        if not ok_v:
            lg.error(f"ensure_balancer: конфиг невалиден ({err_v}) — ядро не трогаю")
            return False
        if not restart_core(cfg):
            lg.error("ensure_balancer: systemctl restart не удался")
            return False
    finally:
        _unlock(cfg, "balancer")
    ok, rtt = wait_and_probe(client, attempts=6, gap=2.0)
    if ok:
        st.data["balancer_sig"] = sig
        st.data["balancer_n"] = len(pool)
        st.data["emergency_ts"] = 0        # нормальный пул — аварийный режим снят
        st.save()
        save_lastgood(cfg, pool)           # страховка: запомнить рабочий состав
        lg.info(f"Балансировщик поднят: {len(pool)} серверов (rtt={rtt} мс)")
    else:
        lg.warn("ensure_balancer: связь не появилась")
    return ok


def _pool_sig(pool: list) -> str:
    import hashlib
    key = "|".join(f"{getattr(s, 'address', '')}:{getattr(s, 'port', 0)}" for s in pool)
    return hashlib.sha1(key.encode()).hexdigest()[:16]


# ══════════════════════════════════════════ активация ═══
def activate(client: dict, servers: list, active_id: str, cfg: dict,
             active_server=None, update_stats: bool = True, existing: list = None,
             restart_client: bool = True) -> dict:
    """Полный цикл активации на Linux: запись store -> конфиг -> restart -> проверка.

    Возвращает {"ok":, "switched":, "rtt":, "msg":} — как Windows-версия.
    """
    lg = log.get_logger()
    switched = str(read_active_id(client["cfg"])) != str(active_id)

    # 1. сохраняем [AUTO]-серверы и активный id
    try:
        n = write_auto_group(client["db"], servers, update_stats)
        write_active_id(client["cfg"], active_id)
        lg.info(f"Store обновлён: {n} [AUTO]-серверов, активный: {active_id}")
    except Exception as e:
        lg.error(f"Запись store не удалась: {e}")
        return {"ok": False, "switched": switched, "rtt": 0, "msg": f"write_error: {e}"}

    # 2. режим балансировщика — пул вместо одного сервера
    if bool(cfg.get("watch", {}).get("balancer_mode", False)):
        if ensure_balancer(client, cfg,
                           n=int(cfg["watch"].get("balancer_pool_n", 10)),
                           force=switched):
            ok2, rtt2 = probe_client(client, timeout=8)
            if ok2:
                return {"ok": True, "switched": switched, "rtt": rtt2,
                        "msg": "balancer_ok"}
        lg.warn("Балансировщик не дал связи — пробую одиночный сервер")

    # 3. одиночный сервер
    srv = active_server
    if srv is None:
        for r in read_db_rows(client["db"]):
            if str(r.get("IndexId")) == str(active_id):
                srv = row_to_server(r)
                break
    if srv is None:
        return {"ok": False, "switched": switched, "rtt": 0, "msg": "server_not_found"}

    if not write_core_config(client, srv, cfg):
        return {"ok": False, "switched": switched, "rtt": 0, "msg": "config_write_failed"}

    ok, rtt = wait_and_probe(client, attempts=1, gap=0)   # после рестарта — с нуля
    if restart_core(cfg):
        ok, rtt = wait_and_probe(client, attempts=6, gap=2.0)
    if ok:
        lg.info(f"Активация OK: {active_id} (rtt={rtt} мс)")
        return {"ok": True, "switched": switched, "rtt": rtt, "msg": "activated"}

    # 4. откат на last_good
    lg.warn("Связи нет — пробую откат на last-good")
    st = StateStore(cfg)
    lg_ = st.data.get("last_good") or {}
    src = lg_.get("cfg")
    if src and os.path.isfile(src):
        try:
            shutil.copy2(src, client["cfg"])
            restart_core(cfg)
            ok2, rtt2 = wait_and_probe(client, attempts=4, gap=2.0)
            if ok2:
                lg.info("Откат на last-good удался")
                return {"ok": True, "switched": switched, "rtt": rtt2,
                        "msg": "rollback_ok"}
        except Exception as e:
            lg.error(f"Откат не удался: {e}")
    return {"ok": False, "switched": switched, "rtt": 0, "msg": "activate_failed"}


# ══════════════════════════════════════════ сторож ═══
def guard_cycle(client: dict, cfg: dict, probe_timeout: float = 6.0) -> bool:
    """Быстрый самоконтроль: порт жив? иначе failover по [AUTO]-серверам."""
    lg = log.get_logger()
    ok, rtt = probe_client(client, timeout=probe_timeout)
    if ok:
        return True
    st = StateStore(cfg)
    port = client.get("socks_port", DEFAULT_SOCKS_PORT)
    lg.warn(f"Порт {port} не отвечает ({rtt} мс); запускаю failover…")

    # 1. кандидаты: [AUTO]-серверы из store, минус чёрный список
    cands = []
    for r in read_db_rows(client.get("db", "")):
        if not (r.get("Remarks") or "").startswith(AUTO_TAG):
            continue
        s = row_to_server(r)
        if s is not None:
            cands.append(s)
    try:
        cands = bl_filter(cfg, cands)
    except Exception:
        pass
    lg.info(f"Failover: [AUTO]-кандидатов: {len(cands)}")

    if cands:
        import xraytest as XT
        pool = XT.PortPool(int(cfg["test"].get("port_start", 10810)),
                           int(cfg["test"].get("workers", 20)) * 2 + 4)
        try:
            cands = XT.tcp_prefilter(cands, cfg)
        except Exception:
            pass
        for s in cands:
            try:
                XT.test_rtt(pool, client["core"], s, 6)
            except Exception:
                pass
        alive = [s for s in cands if getattr(s, "ok", False)]
        alive.sort(key=lambda s: (s.rtt_ms or 9999,
                                  -(s.speed_kbps or 0)))
        lg.info(f"Failover: живых [AUTO]: {len(alive)}")
        for s in alive[:8]:
            if not write_core_config(client, s, cfg):
                continue
            restart_core(cfg)
            ok2, rtt2 = wait_and_probe(client, attempts=5, gap=2.0)
            if ok2:
                sid = getattr(s, "_row_index_id", None) or getattr(s, "index_id", None)
                if sid:
                    write_active_id(client["cfg"], sid)
                lg.info(f"Failover OK: переключились на {s.address}:{s.port} "
                        f"(rtt={rtt2} мс)")
                return True
            try:
                bl_add(cfg, getattr(s, "_row_index_id", None) or getattr(s, "index_id", ""),
                       60, "failover_no_connect")
            except Exception:
                pass
    else:
        lg.warn("Failover: нет [AUTO]-серверов в store")

    # 2. fallback: last_good
    lg.info("Failover: пробую last-good…")
    lg_ = st.data.get("last_good") or {}
    src = lg_.get("cfg")
    if src and os.path.isfile(src):
        try:
            shutil.copy2(src, client["cfg"])
            restart_core(cfg)
            ok2, rtt2 = wait_and_probe(client, attempts=5, gap=2.0)
            if ok2:
                lg.info(f"Guard OK: восстановлен last-good (rtt={rtt2} мс)")
                return True
        except Exception as e:
            lg.error(f"guard restore: {e}")

    # 3. последняя попытка: активный сервер напрямую
    act = read_active_id(client["cfg"])
    for r in read_db_rows(client.get("db", "")):
        if str(r.get("IndexId")) == str(act):
            srv = row_to_server(r)
            if srv is not None and write_core_config(client, srv, cfg):
                restart_core(cfg)
                ok2, rtt2 = wait_and_probe(client, attempts=5, gap=2.0)
                if ok2:
                    lg.info(f"Guard OK: связь восстановлена (rtt={rtt2} мс)")
                    return True
            break

    lg.error("Guard: восстановить связь не удалось")
    return False


# ── совместимость: имена, которые могут звать вызывающие ──
def stop_client(client: dict, wait: float = 20.0):
    """Остановка ядра (аналог stop_client)."""
    try:
        subprocess.run(["systemctl", "--user", "stop",
                        client.get("service", "xray-proxy")],
                       capture_output=True, timeout=int(wait) + 10)
    except Exception:
        pass


def start_client(client: dict):
    """Запуск ядра (аналог start_client)."""
    try:
        r = subprocess.run(["systemctl", "--user", "start",
                            client.get("service", "xray-proxy")],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False
