import asyncio, json, unittest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import server


async def connect(port, name):
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write((json.dumps({"type": "join", "username": name}) + "\n").encode())
    await w.drain()
    return r, w


async def recv(r):
    return json.loads(await asyncio.wait_for(r.readline(), 2))


async def send(w, obj):
    w.write((json.dumps(obj) + "\n").encode()); await w.drain()


class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        server.clients.clear()
        self.srv = await server.start_server("127.0.0.1", 0)
        self.port = self.srv.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.srv.close(); await self.srv.wait_closed()

    async def test_group_and_private(self):
        ar, aw = await connect(self.port, "alice"); await recv(ar)
        br, bw = await connect(self.port, "bob"); await recv(br)
        self.assertEqual((await recv(ar))["text"], "bob joined the chat")
        await send(aw, {"type": "msg", "text": "hi all"})
        self.assertEqual((await recv(br))["text"], "hi all")
        self.assertEqual((await recv(ar))["from"], "alice")
        await send(bw, {"type": "private", "to": "alice", "text": "psst"})
        m = await recv(ar); self.assertEqual((m["type"], m["text"]), ("private", "psst"))
        aw.close(); bw.close()

    async def test_duplicate_username_rejected(self):
        _, aw = await connect(self.port, "alice")
        r2, w2 = await connect(self.port, "alice")
        self.assertEqual((await recv(r2))["type"], "error")
        aw.close(); w2.close()

    async def test_disconnect_notifies_and_cleans_up(self):
        ar, aw = await connect(self.port, "alice"); await recv(ar)
        br, bw = await connect(self.port, "bob"); await recv(br); await recv(ar)
        bw.close()
        self.assertEqual((await recv(ar))["text"], "bob left the chat")
        self.assertNotIn("bob", server.clients)
        aw.close()

    async def test_bad_json_does_not_crash(self):
        ar, aw = await connect(self.port, "alice"); await recv(ar)
        aw.write(b"not json\n"); await aw.drain()
        self.assertEqual((await recv(ar))["type"], "error")
        await send(aw, {"type": "users"})
        self.assertEqual((await recv(ar))["users"], ["alice"])
        aw.close()


if __name__ == "__main__":
    unittest.main()
