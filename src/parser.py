"""Разбор share-ссылок (vless/vmess/trojan/ss) в унифицированный Server.

Расстановка полей повторяет логику v2rayN (ServiceLib/Handler/Fmt):
  - security  -> StreamSecurity
  - sni/fp/pbk/sid/spx/alpn ...  -> одноимённые поля
  - type      -> Network ('tcp' -> 'raw')
  - host/path -> транспорт (ws: Host/Path; raw: RawHeaderType/Host/Path)
"""
import base64
import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass, field, asdict

PROTO_VLESS = "vless"
PROTO_VMESS = "vmess"
PROTO_TROJAN = "trojan"
PROTO_SS = "ss"

SUPPORTED = (PROTO_VLESS, PROTO_VMESS, PROTO_TROJAN, PROTO_SS)


@dataclass
class Server:
    protocol: str
    address: str
    port: int
    password: str = ""
    method: str = ""            # ss method / vmess security
    alter_id: str = "0"         # vmess
    network: str = "raw"
    stream_security: str = ""   # '', tls, reality
    sni: str = ""
    alpn: str = ""
    fingerprint: str = ""
    public_key: str = ""
    short_id: str = ""
    spider_x: str = ""
    flow: str = ""
    host: str = ""              # ws host header / raw host
    path: str = ""              # ws path / raw path
    header_type: str = ""       # raw (http) / kcp
    kcp_seed: str = ""
    allow_insecure: bool = False
    remark: str = ""
    source: str = ""
    # результаты теста
    rtt_ms: float = 0.0
    speed_kbps: float = 0.0
    ok: bool = False
    fail_reason: str = ""

    @property
    def identity(self) -> str:
        """Каноническая строка для дедупликации и стабильного IndexId."""
        parts = [self.protocol, self.address, str(self.port), self.password,
                 self.method, self.network, self.stream_security, self.sni,
                 self.flow, self.host, self.path, self.header_type,
                 self.public_key, self.short_id, self.alter_id]
        return "|".join(parts)

    @property
    def index_id(self) -> str:
        h = hashlib.sha1(self.identity.encode("utf-8")).hexdigest()[:15]
        return str(int(h, 16))

    def summary(self) -> str:
        return f"{self.protocol} {self.address}:{self.port} {self.remark}".strip()


# ---------------------------------------------------------------------------

def _q(query: dict, key: str, default: str = "") -> str:
    v = query.get(key)
    return v if v is not None else default


def _un(url: str) -> str:
    try:
        return urllib.parse.unquote(url)
    except Exception:
        return url


def _parse_query(query: str) -> dict:
    if not query:
        return {}
    q = query[1:] if query.startswith("?") else query
    out = {}
    for pair in q.split("&"):
        if not pair:
            continue
        k, _, v = pair.partition("=")
        out[k] = _un(v)
    return out


def _b64dec(s: str) -> str:
    s = s.strip().replace("\n", "").replace("\r", "")
    pad = "=" * (-len(s) % 4)
    raw = s + pad
    try:
        return base64.b64decode(raw).decode("utf-8")
    except Exception:
        try:
            return base64.urlsafe_b64decode(raw).decode("utf-8")
        except Exception:
            return ""


def _host_port(netloc: str, default_port: int = 443):
    if not netloc:
        return "", 0
    host = netloc
    port = default_port
    if netloc.startswith("["):
        # [ipv6]:port
        m = re.match(r"\[([^\]]+)\](?::(\d+))?", netloc)
        if m:
            host = m.group(1)
            if m.group(2):
                port = int(m.group(2))
            return host, port
    if ":" in netloc:
        h, _, p = netloc.rpartition(":")
        if h and p.isdigit():
            host, port = h, int(p)
    return host, port


def parse_vless(url: str) -> Server:
    u = urllib.parse.urlsplit(url)
    host, port = _host_port(u.netloc.rsplit("@", 1)[-1] if "@" in u.netloc else u.netloc)
    if not host or port <= 0:
        return None
    s = Server(protocol=PROTO_VLESS, address=host, port=port)
    s.password = _un(u.username or "")
    s.remark = _un(u.fragment or "")
    q = _parse_query(u.query)
    s.flow = _q(q, "flow")
    s.stream_security = _q(q, "security")
    s.sni = _q(q, "sni")
    s.alpn = _q(q, "alpn")
    s.fingerprint = _q(q, "fp")
    s.public_key = _q(q, "pbk")
    s.short_id = _q(q, "sid")
    s.spider_x = _q(q, "spx")
    s.allow_insecure = _q(q, "allowInsecure") == "1" or _q(q, "insecure") == "1"
    _apply_transport(s, q)
    return s


def parse_vmess(url: str) -> Server:
    rest = url[len("vmess://"):]
    s = None
    if "@" in rest:
        s = _vmess_std(rest)
    if s is None:
        s = _vmess_json(rest)
    if s is None:
        return None
    return s


def _vmess_std(rest: str) -> Server:
    u = urllib.parse.urlsplit("vmess://" + rest)
    host, port = _host_port(u.netloc.rsplit("@", 1)[-1] if "@" in u.netloc else u.netloc)
    if not host or port <= 0:
        return None
    s = Server(protocol=PROTO_VMESS, address=host, port=port)
    s.password = _un(u.username or "")
    s.remark = _un(u.fragment or "")
    s.method = "auto"
    q = _parse_query(u.query)
    s.alter_id = _q(q, "aid", "0")
    s.stream_security = _q(q, "security")
    s.sni = _q(q, "sni")
    s.alpn = _q(q, "alpn")
    s.fingerprint = _q(q, "fp")
    s.allow_insecure = _q(q, "allowInsecure") == "1" or _q(q, "insecure") == "1"
    _apply_transport(s, q)
    return s


def _vmess_json(rest: str) -> Server:
    raw = _b64dec(rest)
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except Exception:
        return None
    host = str(d.get("add") or "")
    port = int(d.get("port") or 0)
    if not host or port <= 0:
        return None
    s = Server(protocol=PROTO_VMESS, address=host, port=port)
    s.password = str(d.get("id") or "")
    s.remark = str(d.get("ps") or "")
    s.alter_id = str(d.get("aid") or "0")
    s.method = str(d.get("scy") or "auto")
    net = str(d.get("net") or "")
    s.network = "raw" if net in ("", "tcp") else net
    s.stream_security = str(d.get("tls") or "")
    s.sni = str(d.get("sni") or "")
    s.alpn = str(d.get("alpn") or "")
    s.fingerprint = str(d.get("fp") or "")
    s.allow_insecure = str(d.get("insecure")) == "1"
    s.header_type = str(d.get("type") or "")
    s.host = str(d.get("host") or "")
    s.path = str(d.get("path") or "")
    if s.network == "grpc":
        s.host, s.path = s.path, s.host  # host=serviceName-ish; keep raw
    return s


def parse_trojan(url: str) -> Server:
    u = urllib.parse.urlsplit(url)
    host, port = _host_port(u.netloc.rsplit("@", 1)[-1] if "@" in u.netloc else u.netloc)
    if not host or port <= 0:
        return None
    s = Server(protocol=PROTO_TROJAN, address=host, port=port)
    s.password = _un(u.username or "")
    s.remark = _un(u.fragment or "")
    q = _parse_query(u.query)
    s.flow = _q(q, "flow")
    s.stream_security = _q(q, "security", "tls")
    s.sni = _q(q, "sni")
    s.alpn = _q(q, "alpn")
    s.fingerprint = _q(q, "fp")
    s.allow_insecure = _q(q, "allowInsecure") == "1" or _q(q, "insecure") == "1"
    _apply_transport(s, q)
    return s


def parse_ss(url: str) -> Server:
    rest = url[len("ss://"):]
    if "@" not in rest:
        # legacy: ss://base64(method:password@host:port)#tag
        m = re.match(r"([A-Za-z0-9+/=_\-]+)(?:#(\S+))?", rest)
        if not m:
            return None
        decoded = _b64dec(m.group(1))
        tag = _un(m.group(2) or "") if m.group(2) else ""
        dm = re.match(r"^(.+?):(.*)@([^:]+):(\d+)$", decoded)
        if not dm:
            return None
        s = Server(protocol=PROTO_SS, address=dm.group(3), port=int(dm.group(4)),
                   method=dm.group(1), password=dm.group(2), remark=tag)
        return s
    # sip002: ss://[method:password@]host:port?plugin=...#tag
    u = urllib.parse.urlsplit(url)
    host, port = _host_port(u.netloc.rsplit("@", 1)[-1] if "@" in u.netloc else u.netloc)
    if not host or port <= 0:
        return None
    ui = u.username or ""
    if u.password is not None:
        ui = ui + ":" + u.password
    ui = _un(ui)
    if not ui:
        return None
    if ":" in ui:
        method, _, password = ui.partition(":")
        s = Server(protocol=PROTO_SS, address=host, port=port, method=method,
                   password=password, remark=_un(u.fragment or ""))
    else:
        decoded = _b64dec(ui)
        if ":" not in decoded:
            return None
        method, _, password = decoded.partition(":")
        s = Server(protocol=PROTO_SS, address=host, port=port, method=method,
                   password=password, remark=_un(u.fragment or ""))
    q = _parse_query(u.query)
    plugin = _q(q, "plugin")
    if plugin:
        # v2ray-plugin/obfs не тестируются нашим xray-ядром — пропускаем
        return None
    return s


def _apply_transport(s: Server, q: dict):
    net = _q(q, "type", "tcp")
    s.network = "raw" if net in ("", "tcp") else net
    if s.network in ("ws", "httpupgrade", "xhttp"):
        s.host = _q(q, "host")
        s.path = _q(q, "path", "/")
    elif s.network == "raw":
        s.header_type = _q(q, "headerType", "none")
        s.host = _q(q, "host")
        s.path = _q(q, "path")
    elif s.network == "kcp":
        s.header_type = _q(q, "headerType", "none")
        s.kcp_seed = _q(q, "seed")
    elif s.network == "grpc":
        s.host = _q(q, "authority")
        s.path = _q(q, "serviceName")
        s.header_type = _q(q, "mode", "gun")
    else:
        s.network = "raw"


def parse_link(url: str, source: str = "") -> Server:
    """Парсит одну ссылку. Неподдерживаемое -> None."""
    url = url.strip()
    if not url:
        return None
    low = url.lower()
    try:
        if low.startswith("vless://"):
            s = parse_vless(url)
        elif low.startswith("vmess://"):
            s = parse_vmess(url)
        elif low.startswith("trojan://"):
            s = parse_trojan(url)
        elif low.startswith("ss://"):
            s = parse_ss(url)
        else:
            return None
    except Exception:
        return None
    if s is None:
        return None
    if not s.address or s.port <= 0 or not s.password:
        return None
    if s.network not in ("raw", "ws", "httpupgrade", "xhttp", "kcp", "grpc"):
        return None
    s.source = source
    if s.stream_security == "reality" and not (s.public_key and s.short_id):
        return None  # reality без ключа нерабочий
    return s


def parse_batch(text: str, source: str = "") -> list:
    """Разбирает содержимое подписки (base64/plain), возвращает Server[]."""
    servers = []
    seen = set()
    # попытка декода как base64, если похоже на base64-блоб
    candidates = [text]
    stripped = text.strip()
    if stripped and not stripped.startswith(("vless://", "vmess://", "trojan://", "ss://")):
        decoded = _b64dec(stripped)
        if decoded:
            candidates.append(decoded)
    for cand in candidates:
        for line in cand.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "//")):
                continue
            s = parse_link(line, source)
            if s is None:
                continue
            if s.identity in seen:
                continue
            seen.add(s.identity)
            servers.append(s)
        if servers:
            break
    return servers


def dedupe(servers: list) -> list:
    """Дедупликация по identity; у дублей оставляем лучший remark."""
    best = {}
    for s in servers:
        cur = best.get(s.identity)
        if cur is None:
            best[s.identity] = s
            continue
        if len(s.remark) > len(cur.remark):
            cur.remark = s.remark
            cur.source = s.source
    return list(best.values())


def to_share_link(s: Server) -> str:
    """Server -> share-ссылка (для подписки/импорта). Формат как у v2rayN."""
    qu = urllib.parse.urlencode
    if s.protocol == PROTO_VLESS:
        q = {"encryption": "none"}
        if s.flow:
            q["flow"] = s.flow
        if s.stream_security:
            q["security"] = s.stream_security
        if s.sni:
            q["sni"] = s.sni
        if s.fingerprint:
            q["fp"] = s.fingerprint
        if s.public_key:
            q["pbk"] = s.public_key
        if s.short_id:
            q["sid"] = s.short_id
        if s.spider_x:
            q["spx"] = s.spider_x
        q["type"] = "tcp" if s.network == "raw" else s.network
        if s.network == "ws":
            if s.host:
                q["host"] = s.host
            q["path"] = s.path or "/"
        elif s.network == "raw":
            q["headerType"] = s.header_type or "none"
        elif s.network == "grpc":
            q["serviceName"] = s.path or ""
        net = f"{s.address}:{s.port}"
        return f"vless://{qu({'': ''})[''] if False else urllib.parse.quote(s.password, safe='')}@{net}?{urllib.parse.urlencode(q, doseq=True)}#{urllib.parse.quote(s.remark or '', safe='')}"
    if s.protocol == PROTO_VMESS:
        d = {"v": "2", "ps": s.remark or s.address, "add": s.address, "port": str(s.port),
             "id": s.password, "aid": s.alter_id or "0",
             "net": "tcp" if s.network == "raw" else s.network}
        if s.stream_security:
            d["tls"] = s.stream_security
        if s.sni:
            d["sni"] = s.sni
        if s.host:
            d["host"] = s.host
        if s.path:
            d["path"] = s.path
        d["type"] = s.header_type or "none"
        b = base64.b64encode(json.dumps(d, ensure_ascii=False).encode()).decode()
        return f"vmess://{b}#{urllib.parse.quote(s.remark or '', safe='')}"
    if s.protocol == PROTO_TROJAN:
        q = {}
        if s.stream_security:
            q["security"] = s.stream_security
        if s.sni:
            q["sni"] = s.sni
        if s.flow:
            q["flow"] = s.flow
        q["type"] = "tcp" if s.network == "raw" else s.network
        if s.network == "ws":
            if s.host:
                q["host"] = s.host
            q["path"] = s.path or "/"
        elif s.network == "raw":
            q["headerType"] = s.header_type or "none"
        return f"trojan://{urllib.parse.quote(s.password, safe='')}@{s.address}:{s.port}?{urllib.parse.urlencode(q, doseq=True)}#{urllib.parse.quote(s.remark or '', safe='')}"
    if s.protocol == PROTO_SS:
        raw = base64.b64encode(f"{s.method}:{s.password}".encode()).decode()
        return f"ss://{raw}@{s.address}:{s.port}#{urllib.parse.quote(s.remark or '', safe='')}"
    return ""


def to_row_dict(s: Server) -> dict:
    """Server -> строка ProfileItem v2rayN (см. ProfileItem.cs / Fmt)."""
    # TransportExtra: ключи строго как в реальной БД
    if s.network == "raw":
        te = {
            "RawHeaderType": s.header_type or "none",
            "Host": s.host or "",
            "Path": s.path or "",
        }
    elif s.network in ("ws", "httpupgrade", "xhttp"):
        te = {"Host": s.host or "", "Path": s.path or "/"}
    elif s.network == "kcp":
        te = {"KcpHeaderType": s.header_type or "none", "KcpSeed": s.kcp_seed or ""}
    elif s.network == "grpc":
        te = {"GrpcAuthority": s.host or "", "GrpcServiceName": s.path or "",
              "GrpcMode": s.header_type or "gun"}
    else:
        te = {"RawHeaderType": "none", "Host": "", "Path": ""}

    if s.protocol == PROTO_VLESS:
        pe = {"Flow": s.flow or "", "VlessEncryption": "none"}
    elif s.protocol == PROTO_VMESS:
        pe = {"AlterId": s.alter_id or "0", "VmessSecurity": s.method or "auto"}
    elif s.protocol == PROTO_TROJAN:
        pe = {"Flow": s.flow or ""}
    elif s.protocol == PROTO_SS:
        pe = {"SsMethod": s.method or ""}
    else:
        pe = {}

    from clientwrite import CONFIG_TYPE  # local import, avoid cycle
    row = {
        "IndexId": s.index_id,
        "ConfigType": CONFIG_TYPE[s.protocol],
        "CoreType": None,
        "ConfigVersion": 4,
        "Subid": None,
        "IsSub": 0,
        "PreSocksPort": None,
        "DisplayLog": 1,
        "Remarks": s.remark or s.summary(),
        "Address": s.address,
        "Port": s.port,
        "Password": s.password,
        "Username": "",
        "Network": s.network,
        "HeaderType": None,
        "RequestHost": None,
        "Path": None,
        "StreamSecurity": s.stream_security,
        "AllowInsecure": "1" if s.allow_insecure else "",
        "Sni": s.sni or "",
        "Alpn": s.alpn or "",
        "Fingerprint": s.fingerprint or "",
        "PublicKey": s.public_key or "",
        "ShortId": s.short_id or "",
        "SpiderX": s.spider_x or "",
        "Mldsa65Verify": "",
        "Extra": None,
        "MuxEnabled": None,
        "Cert": None,
        "CertSha": "",
        "EchConfigList": "",
        "VerifyPeerCertByName": "",
        "Finalmask": "",
        "ProtoExtra": json.dumps(pe, ensure_ascii=False, separators=(",", ":")),
        "TransportExtra": json.dumps(te, ensure_ascii=False, separators=(",", ":")),
        "Ports": None,
        "AlterId": 0,
        "Flow": None,
        "Id": None,
        "Security": None,
    }
    return row