# Transport-Layer Report — TCP Chat Application (CSC 423)

## 1. How the application uses the transport layer
The server calls `socket → bind → listen → accept` (via asyncio's `start_server`) on **TCP port 5000**. Each client calls `connect()` to `<server-ip>:5000`; the OS performs the three-way handshake (SYN, SYN-ACK, ACK). The server gets one dedicated connected socket per client, identified by the 4-tuple *(client IP, client port, server IP, 5000)*. All chat traffic is UTF-8 JSON lines sent over these connections. The server relays messages between sockets (group broadcast or private routing by username).

## 2. TCP vs UDP analysis

**Q1. Why is TCP suitable for chat?** Chat needs every message delivered, exactly once, in order ("yes" must not arrive before "are you coming?"). TCP gives this automatically, so the app does not need its own retransmission or ordering logic. Connection state also tells the server precisely when a user is online/offline.

**Q2. What guarantees does TCP provide?** Connection-oriented (handshake); reliable delivery (sequence numbers, ACKs, retransmission on timeout); in-order delivery; no duplicates; error detection (checksum); flow control (receiver window stops a fast sender overwhelming a slow receiver); congestion control. It does **not** guarantee message boundaries (it's a byte stream — hence our `\n` framing), nor encryption, nor bounded latency.

**Q3. TCP vs UDP**

| | TCP | UDP |
|---|---|---|
| Connection | Handshake, stateful | Connectionless |
| Reliability | Retransmits lost data | None |
| Ordering | Guaranteed | None |
| Boundaries | Byte stream | Preserves datagrams |
| Overhead/latency | Higher (20-byte+ header, ACKs) | Lower (8-byte header) |
| Flow/congestion control | Yes | No |
| Use cases | Chat text, web, email, file transfer | Voice/video calls, gaming, DNS |

**Q4. Chat features that could use UDP:** typing indicators, presence/"last seen" pings, live voice/video calls inside chat, network latency probes, LAN server discovery via broadcast. These are ephemeral: a stale or lost update is worthless or quickly replaced. (Message text itself should stay on TCP.)

**Q5. UDP loss and reordering:** UDP never retransmits or reorders; a lost datagram is gone and datagrams can arrive in a different order. The application must add its own sequence numbers, ACKs/retries (if it cares) or simply ignore stale/missing data. `udp_experiment.py` demonstrates this: out of 10 datagrams ~30% are dropped and the rest arrive shuffled; the receiver detects gaps and stale packets only because of the app-level `seq` field.

**Q6. Sockets and ports:** An IP address identifies a host; a **port** (16-bit) identifies a process/service on it; a **socket** is the OS endpoint (IP + port + protocol) a program reads/writes. The server listens on one well-known port (5000); clients get ephemeral ports. The OS uses the 4-tuple to deliver each incoming segment to the right socket, so one server port can serve thousands of simultaneous clients. In the cloud, the Security Group must also allow inbound TCP 5000.

**Q7. When a TCP client disconnects:**
- *Graceful:* client `close()` sends FIN; server's `readline()` returns empty bytes (EOF); server ACKs, closes its side (FIN/ACK), the socket passes through FIN_WAIT/TIME_WAIT, and resources are freed. Our server removes the user from `clients` and broadcasts "X left the chat".
- *Abrupt (crash, network drop, Wi-Fi lost):* no FIN. The server may see a RST/`ConnectionResetError`, or nothing until a write fails or TCP keepalive (enabled with `SO_KEEPALIVE`) times out. Our `finally:` block performs the same cleanup in all cases.

## 3. Design decisions
- **asyncio single-threaded server**: handles many idle connections cheaply, no locking on the shared `clients` dict.
- **Newline-delimited JSON**: human-readable, easy to debug with `nc`, solves TCP's missing message boundaries; 4 KB frame cap prevents memory abuse.
- **Join handshake with validation**: usernames validated and unique; 30 s join timeout stops idle connections.
- **Robustness**: bad JSON returns an error instead of crashing; one client's failure never affects others.
- **WebSockets (if a browser UI is added):** WebSocket starts as an HTTP request, upgrades (`101 Switching Protocols`), and then runs as a framed, bidirectional message protocol **on top of a TCP connection** — so it still relies on TCP's reliability and ordering; it only adds browser compatibility and message framing. This project uses plain TCP sockets directly.
- **UDP** is used only in the optional comparison experiment.

## 4. Cloud deployment explanation
See README. **EC2** runs the Python server process; the **Security Group** is a stateful firewall that opens only TCP 5000 (and SSH from my IP); the **Elastic IP** gives clients a fixed public address; **systemd** restarts the server on crash/reboot; CloudWatch/journald provide logs. No database is needed since chat history isn't persisted.

## 5. Reflection  *(rewrite in your own words and add your real experience)*
- Challenge: TCP has no message boundaries — I had to design framing (newline-delimited JSON) so messages never merged or split.
- Challenge: handling abrupt disconnects and duplicate usernames without leaving ghost users.
- Challenge: cloud networking — the app worked locally but was unreachable until the Security Group allowed TCP 5000 and the server bound to `0.0.0.0` rather than `127.0.0.1`.
- Learned: sockets/ports/4-tuples, three-way handshake and FIN teardown, reliability/ordering guarantees, flow control, and why UDP suits real-time, loss-tolerant data.
- Future: TLS, authentication, message history in a database, WebSocket web client.
