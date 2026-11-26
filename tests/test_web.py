import asyncio, base64, hashlib, json, os, struct, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import server, web_gateway


def client_frame(text):
    payload = text.encode(); mask = os.urandom(4)
    head = bytes([0x81, 0x80 | len(payload)]) + mask          # payload < 126 bytes in tests
    return head + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


async def ws_connect(port, origin=None):
    r, w = await asyncio.open_connection("127.0.0.1", port)
    key = base64.b64encode(os.urandom(16)).decode()
    extra = f"Origin: {origin}\r\n" if origin else ""
    w.write((f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{extra}Upgrade: websocket\r\n"
             f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    head = (await r.readuntil(b"\r\n\r\n")).decode()
    return r, w, head, key


async def ws_recv(r):
    b1, b2 = await asyncio.wait_for(r.readexactly(2), 2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", await r.readexactly(2))[0]
    return json.loads(await r.readexactly(n))


async def ws_send(w, obj):
    w.write(client_frame(json.dumps(obj))); await w.drain()


async def tcp_next(r, kind, sender=None):
    while True:
        m = json.loads(await asyncio.wait_for(r.readline(), 2))
        if m["type"] == kind and (sender is None or m.get("from") == sender):
            return m


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        server.clients.clear()
        self.chat = await server.start_server("127.0.0.1", 0)
        self.cport = self.chat.sockets[0].getsockname()[1]
        self.gw = await web_gateway.start_gateway("127.0.0.1", 0, "127.0.0.1", self.cport)
        self.wport = self.gw.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        for s in (self.gw, self.chat):
            s.close(); await s.wait_closed()

    async def test_handshake_accept_key(self):
        r, w, head, key = await ws_connect(self.wport)
        expected = base64.b64encode(hashlib.sha1((key + web_gateway.GUID).encode()).digest()).decode()
        self.assertIn("101 Switching Protocols", head)
        self.assertIn(expected, head)
        w.close()

    async def test_browser_and_tcp_users_chat(self):
        wr, ww, _, _ = await ws_connect(self.wport)
        await ws_send(ww, {"type": "join", "username": "webby"})
        self.assertEqual((await ws_recv(wr))["type"], "joined")
        tr, tw = await asyncio.open_connection("127.0.0.1", self.cport)
        tw.write(b'{"type":"join","username":"tcpy"}\n'); await tw.drain(); await tcp_next(tr, "joined")
        self.assertEqual((await ws_recv(wr))["text"], "tcpy joined the chat")
        tw.write(b'{"type":"msg","text":"hello web"}\n'); await tw.drain()
        m = await ws_recv(wr); self.assertEqual((m["from"], m["text"]), ("tcpy", "hello web"))
        await ws_send(ww, {"type": "msg", "text": "hello tcp"})
        m = await tcp_next(tr, "msg", "webby"); self.assertEqual((m["from"], m["text"]), ("webby", "hello tcp"))
        ww.close(); tw.close()

    async def test_browser_disconnect_notifies_tcp_user(self):
        tr, tw = await asyncio.open_connection("127.0.0.1", self.cport)
        tw.write(b'{"type":"join","username":"tcpy"}\n'); await tw.drain(); await tcp_next(tr, "joined")
        wr, ww, _, _ = await ws_connect(self.wport)
        await ws_send(ww, {"type": "join", "username": "webby"}); await ws_recv(wr)
        self.assertEqual((await tcp_next(tr, "system"))["text"], "webby joined the chat")
        ww.close()
        self.assertEqual((await tcp_next(tr, "system"))["text"], "webby left the chat")
        tw.close()

    async def test_serves_page_and_rejects_foreign_origin(self):
        r, w = await asyncio.open_connection("127.0.0.1", self.wport)
        w.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n"); await w.drain()
        data = await r.read(); self.assertIn(b"200 OK", data); self.assertIn(b"<title>TCP Chat</title>", data)
        _, _, head, _ = await ws_connect(self.wport, origin="http://evil.example")
        self.assertIn("403", head)


if __name__ == "__main__":
    unittest.main()
