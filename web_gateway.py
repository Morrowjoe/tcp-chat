"""Browser gateway: serves the chat web page and bridges WebSocket <-> the TCP chat server.

Browsers cannot open raw TCP sockets, so each browser opens a WebSocket (which itself runs on a
TCP connection), and this gateway opens an ordinary TCP connection to server.py for it and relays
messages both ways. Standard library only (RFC 6455 handshake + framing implemented below).
"""
import asyncio, base64, functools, hashlib, json, logging, os, struct
from urllib.parse import urlparse

WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
CHAT_HOST = os.getenv("CHAT_SERVER_HOST", "127.0.0.1")
CHAT_PORT = int(os.getenv("CHAT_PORT", "5000"))
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"          # fixed value from RFC 6455
MAX_FRAME = 4096
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")
log = logging.getLogger("web")


def ws_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Build an unmasked server->client frame (servers must not mask)."""
    n = len(payload)
    head = bytes([0x80 | opcode])                      # FIN=1 + opcode
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    return head + payload


async def read_frame(reader):
    """Read one client->server frame. Returns (fin, opcode, payload)."""
    b1, b2 = await reader.readexactly(2)
    fin, opcode = bool(b1 & 0x80), b1 & 0x0F
    masked, length = bool(b2 & 0x80), b2 & 0x7F
    if length == 126:
        length = struct.unpack(">H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", await reader.readexactly(8))[0]
    if length > MAX_FRAME:
        raise ValueError("frame too large")
    if not masked:
        raise ValueError("client frames must be masked")
    mask = await reader.readexactly(4)
    data = bytearray(await reader.readexactly(length))
    for i in range(length):
        data[i] ^= mask[i % 4]
    return fin, opcode, bytes(data)


async def http_reply(writer, status, body, ctype="text/plain; charset=utf-8"):
    head = (f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n")
    writer.write(head.encode() + body)
    await writer.drain()


async def websocket_session(reader, writer, headers, chat_host, chat_port):
    origin = headers.get("origin")
    if origin and urlparse(origin).netloc != headers.get("host"):
        await http_reply(writer, "403 Forbidden", b"Cross-origin WebSocket refused")
        return
    key = headers.get("sec-websocket-key")
    if not key or headers.get("sec-websocket-version") != "13":
        await http_reply(writer, "400 Bad Request", b"Bad WebSocket handshake")
        return
    accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
    writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                  f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
    await writer.drain()

    try:                                               # one TCP connection to the chat server per browser
        t_reader, t_writer = await asyncio.open_connection(chat_host, chat_port)
    except OSError:
        writer.write(ws_frame(8, struct.pack(">H", 1011)))
        return
    log.info("browser connected, bridged to %s:%s", chat_host, chat_port)

    async def ws_to_tcp():
        while True:
            fin, opcode, payload = await read_frame(reader)
            if opcode == 8:                            # close
                writer.write(ws_frame(8, payload[:2]))
                return
            if opcode == 9:                            # ping -> pong
                writer.write(ws_frame(10, payload))
            elif opcode == 1 and fin:                  # text frame = one JSON chat message
                try:
                    line = json.dumps(json.loads(payload.decode("utf-8"))) + "\n"
                except ValueError:
                    err = {"type": "error", "text": "Invalid message."}
                    writer.write(ws_frame(1, json.dumps(err).encode()))
                    continue
                t_writer.write(line.encode())
                await t_writer.drain()
            elif opcode in (0, 1, 2):                  # fragments / binary unsupported
                writer.write(ws_frame(8, struct.pack(">H", 1003)))
                return

    async def tcp_to_ws():
        while True:
            line = await t_reader.readline()
            if not line:                               # chat server closed the connection
                writer.write(ws_frame(8, struct.pack(">H", 1000)))
                return
            writer.write(ws_frame(1, line.rstrip(b"\n")))
            await writer.drain()

    tasks = [asyncio.ensure_future(ws_to_tcp()), asyncio.ensure_future(tcp_to_ws())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        t_writer.close()                               # TCP FIN -> chat server announces "left"
        log.info("browser disconnected")


async def handle(reader, writer, chat_host, chat_port):
    try:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            return
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, path, _ = lines[0].split(" ", 2)
        except ValueError:
            await http_reply(writer, "400 Bad Request", b"Bad request")
            return
        headers = {}
        for l in lines[1:]:
            if ":" in l:
                k, v = l.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        path = path.split("?")[0]
        if method != "GET":
            await http_reply(writer, "405 Method Not Allowed", b"GET only")
        elif path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
            await websocket_session(reader, writer, headers, chat_host, chat_port)
        elif path in ("/", "/index.html"):
            try:
                with open(INDEX, "rb") as f:
                    body = f.read()
                await http_reply(writer, "200 OK", body, "text/html; charset=utf-8")
            except OSError:
                await http_reply(writer, "500 Internal Server Error", b"index.html missing")
        else:
            await http_reply(writer, "404 Not Found", b"Not found")
    except (ConnectionError, OSError, ValueError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def start_gateway(host=WEB_HOST, port=WEB_PORT, chat_host=CHAT_HOST, chat_port=CHAT_PORT):
    return await asyncio.start_server(
        functools.partial(handle, chat_host=chat_host, chat_port=chat_port), host, port)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    server = await start_gateway()
    log.info("Web gateway on %s -> chat server %s:%s", [s.getsockname() for s in server.sockets], CHAT_HOST, CHAT_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
