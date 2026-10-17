#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# testproxy.py — a throwaway HTTP forward proxy used to self-test wsl-matrix.sh
# before the real ForestProxyUpdater packages exist.
#
# It implements just enough of HTTP proxying for the bench's traffic probe:
#   curl -x http://127.0.0.1:<port> https://www.gstatic.com/generate_204
# which is a CONNECT tunnel; plain absolute-URI GETs are handled too.
#
# It is NOT a product component — it exists only so the bench can prove it is
# alive (installs, starts a unit, carries real traffic, uninstalls cleanly).
#
# Env: FP_TEST_PORT (default 11808), FP_TEST_BIND (default 127.0.0.1)

import os
import select
import socket
import threading
from urllib.parse import urlparse

PORT = int(os.environ.get("FP_TEST_PORT", "11808"))
BIND = os.environ.get("FP_TEST_BIND", "127.0.0.1")
BUF = 65536


def tunnel(a: socket.socket, b: socket.socket) -> None:
    """Pump bytes both ways until either side closes."""
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], 30)
            if not r:
                break
            for s in r:
                data = s.recv(BUF)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        pass


def handle(conn: socket.socket) -> None:
    conn.settimeout(30)
    try:
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
        head, _, _rest = buf.partition(b"\r\n\r\n")
        first = head.split(b"\r\n")[0]
        parts = first.split(b" ")
        if len(parts) < 2:
            return
        method, target = parts[0].upper(), parts[1].decode("latin-1")

        if method == b"CONNECT":
            host, _, port = target.partition(":")
            upstream = socket.create_connection((host, int(port or 443)), timeout=20)
            conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            tunnel(conn, upstream)
            upstream.close()
        else:  # absolute-URI request
            u = urlparse(target)
            path = u.path or "/"
            if u.query:
                path += "?" + u.query
            upstream = socket.create_connection((u.hostname, u.port or 80), timeout=20)
            upstream.sendall(
                f"{method.decode()} {path} HTTP/1.1\r\n"
                f"Host: {u.hostname}\r\nConnection: close\r\n\r\n".encode()
            )
            while True:
                data = upstream.recv(BUF)
                if not data:
                    break
                conn.sendall(data)
            upstream.close()
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((BIND, PORT))
    srv.listen(64)
    print(f"testproxy listening on {BIND}:{PORT}", flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
