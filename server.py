"""Multi-user TCP chat server (asyncio). Protocol: newline-delimited JSON over TCP."""
import asyncio, json, logging, os, re, socket, time

HOST = os.getenv("CHAT_HOST", "0.0.0.0")
PORT = int(os.getenv("CHAT_PORT", "5000"))
MAX_LINE = 4096                      # max bytes per message (frame)
JOIN_TIMEOUT = 30                    # seconds to send a join message
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")

log = logging.getLogger("chat")
clients: dict[str, asyncio.StreamWriter] = {}   # username -> writer


def encode(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode()     # "\n" is the frame delimiter


async def send(writer, obj):
    try:
        writer.write(encode(obj))
        await writer.drain()
    except (ConnectionError, OSError):
        pass                                     # reader loop will clean up


async def broadcast(obj, exclude=None):
    for name, w in list(clients.items()):
        if name != exclude:
            await send(w, obj)


def system(text):
    return {"type": "system", "text": text, "ts": time.time()}


async def read_msg(reader, timeout=None):
    """Return one decoded JSON object, or None on EOF. Raises ValueError on bad data."""
    line = await asyncio.wait_for(reader.readline(), timeout)
    if not line:
        return None                              # EOF: peer closed (TCP FIN)
    return json.loads(line.decode("utf-8"))


async def handle(reader, writer):
    peer = writer.get_extra_info("peername")
    sock = writer.get_extra_info("socket")
    if sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)  # detect dead peers
    username = None
    try:
        # 1. Identification: first message must be a join
        try:
            msg = await read_msg(reader, JOIN_TIMEOUT)
        except (ValueError, asyncio.TimeoutError, asyncio.LimitOverrunError):
            await send(writer, {"type": "error", "text": "Expected a JSON join message."})
            return
        if not msg or msg.get("type") != "join":
            await send(writer, {"type": "error", "text": "First message must be a join."})
            return
        name = str(msg.get("username", "")).strip()
        if not NAME_RE.match(name):
            await send(writer, {"type": "error", "text": "Username must be 2-20 chars: letters, digits, _ or -."})
            return
        if name in clients:
            await send(writer, {"type": "error", "text": f"Username '{name}' is taken."})
            return
        username = name
        clients[username] = writer
        log.info("%s joined from %s (online=%d)", username, peer, len(clients))
        await send(writer, {"type": "joined", "username": username, "users": sorted(clients)})
        await broadcast(system(f"{username} joined the chat"), exclude=username)

        # 2. Main loop
        while True:
            try:
                msg = await read_msg(reader)
            except ValueError:                   # bad JSON / bad UTF-8 / line too long
                await send(writer, {"type": "error", "text": "Invalid or oversized message."})
                continue
            if msg is None:
                break                            # client disconnected
            kind = msg.get("type")
            text = str(msg.get("text", "")).strip()
            if kind == "msg" and text:
                await broadcast({"type": "msg", "from": username, "text": text, "ts": time.time()})
            elif kind == "private" and text:
                target = msg.get("to")
                if target in clients:
                    out = {"type": "private", "from": username, "to": target, "text": text, "ts": time.time()}
                    await send(clients[target], out)
                    if target != username:
                        await send(writer, out)  # echo to sender
                else:
                    await send(writer, {"type": "error", "text": f"User '{target}' not found."})
            elif kind == "users":
                await send(writer, {"type": "users", "users": sorted(clients)})
            elif kind == "quit":
                break
            else:
                await send(writer, {"type": "error", "text": "Unknown or empty message."})
    except (ConnectionError, asyncio.IncompleteReadError, OSError) as e:
        log.info("connection error for %s: %s", username or peer, e)
    finally:
        if username and clients.get(username) is writer:
            del clients[username]
            await broadcast(system(f"{username} left the chat"))
            log.info("%s left (online=%d)", username, len(clients))
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def start_server(host=HOST, port=PORT):
    return await asyncio.start_server(handle, host, port, limit=MAX_LINE)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    server = await start_server()
    log.info("Chat server listening on %s", [s.getsockname() for s in server.sockets])
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
