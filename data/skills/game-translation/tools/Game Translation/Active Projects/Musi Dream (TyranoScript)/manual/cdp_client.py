"""Small standard-library CDP client for an already-running local game.

Examples:
    python cdp_client.py status --port 9222
    python cdp_client.py eval 'document.title' --port 9222
    python cdp_client.py screenshot screenshot.png --port 9222

Import:
    with CDPClient(port=9222) as cdp:
        value = cdp.evaluate('({title: document.title, url: location.href})')
        cdp.screenshot('screenshot.png')

Only 127.0.0.1 is contacted. This module never launches a process or changes
the game automatically. evaluate() executes exactly the supplied expression.
"""
from __future__ import annotations

import argparse
import base64
from collections import deque
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import struct
import sys
import time
from urllib.parse import urlsplit


def list_targets(port: int = 9222, timeout: float = 10.0) -> list[dict]:
    if not 1 <= int(port) <= 65535:
        raise ValueError("Invalid debugging port")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/json/list")
        response = conn.getresponse()
        if response.status != 200:
            raise RuntimeError(f"CDP target list returned HTTP {response.status}")
        targets = json.loads(response.read())
        if not isinstance(targets, list):
            raise RuntimeError("CDP target list is not an array")
        return targets
    finally:
        conn.close()


class CDPClient:
    def __init__(self, port: int = 9222, target_id: str | None = None,
                 timeout: float = 15.0, url_contains: str | None = None):
        self.timeout = timeout
        self.events: deque[dict] = deque(maxlen=1000)
        self._pending: dict[int, dict] = {}
        self._next_id = 1
        self._buffer = bytearray()
        self._socket: socket.socket | None = None
        targets = list_targets(port, timeout)
        candidates = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        if target_id is not None:
            candidates = [t for t in candidates if t.get("id") == target_id]
        if url_contains is not None:
            candidates = [t for t in candidates if url_contains in t.get("url", "")]
        if not candidates:
            raise RuntimeError("No matching page target; use status to inspect the local debugger")
        candidates.sort(key=lambda t: (t.get("url", "").startswith("devtools:"), t.get("url") == "about:blank"))
        self.target = candidates[0]
        self._connect(self.target["webSocketDebuggerUrl"], int(port))

    def _connect(self, url: str, expected_port: int) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.port != expected_port:
            raise ValueError("Refusing a debugger WebSocket outside the requested loopback port")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Unexpected debugger WebSocket URL")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        if "\r" in path or "\n" in path:
            raise ValueError("Invalid debugger path")
        self._socket = socket.create_connection(("127.0.0.1", expected_port), self.timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{expected_port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self._socket.sendall(request.encode("ascii"))
        while b"\r\n\r\n" not in self._buffer:
            data = self._socket.recv(4096)
            if not data:
                raise ConnectionError("Debugger closed during WebSocket handshake")
            self._buffer.extend(data)
            if len(self._buffer) > 65536:
                raise ConnectionError("Oversized WebSocket handshake")
        end = self._buffer.index(b"\r\n\r\n") + 4
        header = bytes(self._buffer[:end]).decode("iso-8859-1")
        del self._buffer[:end]
        lines = header.split("\r\n")
        if len(lines[0].split()) < 2 or lines[0].split()[1] != "101":
            self.close()
            raise ConnectionError("WebSocket upgrade rejected: " + lines[0])
        headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
        headers = {k.lower().strip(): v.strip() for k, v in headers.items()}
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            self.close()
            raise ConnectionError("Invalid WebSocket acceptance key")

    def _read(self, size: int) -> bytes:
        while len(self._buffer) < size:
            data = self._socket.recv(max(4096, size - len(self._buffer)))
            if not data:
                raise ConnectionError("Debugger WebSocket closed")
            self._buffer.extend(data)
        result = bytes(self._buffer[:size])
        del self._buffer[:size]
        return result

    def _send_frame(self, payload: bytes, opcode: int = 1) -> None:
        if self._socket is None:
            raise ConnectionError("Debugger client is closed")
        size = len(payload)
        header = bytearray([0x80 | opcode])
        if size < 126:
            header.append(0x80 | size)
        elif size <= 65535:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", size))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", size))
        mask = os.urandom(4)
        header.extend(mask)
        self._socket.sendall(header + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _receive_message(self, deadline: float) -> dict:
        fragments = bytearray()
        message_opcode = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for debugger response")
            self._socket.settimeout(remaining)
            first, second = self._read(2)
            final, opcode = bool(first & 0x80), first & 0x0f
            size = second & 0x7f
            if size == 126:
                size = struct.unpack("!H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self._read(8))[0]
            if size > 256 * 1024 * 1024:
                raise ConnectionError("Debugger frame exceeds 256 MiB")
            mask = self._read(4) if second & 0x80 else None
            payload = self._read(size)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 8:
                raise ConnectionError("Debugger sent a close frame")
            if opcode == 9:
                self._send_frame(payload, 10)
                continue
            if opcode == 10:
                continue
            if opcode in (1, 2):
                if message_opcode is not None:
                    raise ConnectionError("Unexpected new fragmented debugger message")
                message_opcode = opcode
            elif opcode != 0 or message_opcode is None:
                raise ConnectionError("Unexpected debugger WebSocket opcode")
            fragments.extend(payload)
            if final:
                if message_opcode != 1:
                    raise ConnectionError("Expected a text debugger message")
                return json.loads(fragments.decode("utf-8"))

    def call(self, method: str, params: dict | None = None, timeout: float | None = None) -> dict:
        request_id = self._next_id
        self._next_id += 1
        request = {"id": request_id, "method": method, "params": params or {}}
        self._send_frame(json.dumps(request, ensure_ascii=False).encode("utf-8"))
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            message = self._pending.pop(request_id, None)
            if message is None:
                message = self._receive_message(deadline)
            if "id" not in message:
                self.events.append(message)
                continue
            if message["id"] != request_id:
                self._pending[message["id"]] = message
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method}: {json.dumps(message['error'], ensure_ascii=False)}")
            return message.get("result", {})

    def evaluate(self, expression: str, timeout: float | None = None):
        response = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}, timeout)
        if "exceptionDetails" in response:
            raise RuntimeError("JavaScript exception: " + json.dumps(response["exceptionDetails"], ensure_ascii=False))
        result = response.get("result", {})
        if "value" in result:
            return result["value"]
        if result.get("type") == "undefined":
            return None
        return result.get("unserializableValue", result.get("description", result))

    def screenshot(self, path: str | Path, full_page: bool = False) -> Path:
        params = {"format": "png", "fromSurface": True}
        if full_page:
            metrics = self.call("Page.getLayoutMetrics")
            size = metrics.get("cssContentSize", metrics.get("contentSize"))
            params["captureBeyondViewport"] = True
            params["clip"] = {"x": 0, "y": 0, "width": size["width"], "height": size["height"], "scale": 1}
        data = self.call("Page.captureScreenshot", params)
        output = Path(path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(base64.b64decode(data["data"], validate=True))
        return output

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._send_frame(struct.pack("!H", 1000), 8)
            except OSError:
                pass
            self._socket.close()
            self._socket = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "eval", "screenshot"):
        sub = subs.add_parser(name)
        sub.add_argument("--port", type=int, default=9222)
        sub.add_argument("--timeout", type=float, default=15.0)
        sub.add_argument("--target", help="Page target ID from status")
        sub.add_argument("--url-contains", help="Select a page by URL substring")
        if name == "eval":
            sub.add_argument("expression")
        elif name == "screenshot":
            sub.add_argument("path")
            sub.add_argument("--full-page", action="store_true")
    args = parser.parse_args()
    if args.command == "status":
        result = list_targets(args.port, args.timeout)
    else:
        with CDPClient(args.port, args.target, args.timeout, args.url_contains) as client:
            if args.command == "eval":
                result = client.evaluate(args.expression)
            else:
                result = {"path": str(client.screenshot(args.path, args.full_page))}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"CDP error: {exc}", file=sys.stderr)
        raise SystemExit(1)
