"""Mini UDP chat for comparison with the TCP app (optional/supplementary).
Server:  python udp_chat.py server [port] [loss%]     e.g. python udp_chat.py server 5001 30
Client:  python udp_chat.py client <host> <port> <name>
UDP has no connections: the server just remembers the address of each datagram's sender.
Every message carries a sequence number so receivers can SEE loss and reordering (UDP won't fix it)."""
import json, random, socket, sys, threading


def server(port=5001, loss=0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", port))
    members = {}                                   # address -> name (no real "connection" exists)
    print(f"UDP chat server on :{port}, simulated loss {loss}%")
    while True:
        data, addr = s.recvfrom(2048)
        try:
            m = json.loads(data)
        except ValueError:
            continue                               # ignore garbage; nothing to disconnect
        if m.get("type") == "join":
            members[addr] = m["name"]
            print(f"{m['name']} joined from {addr}")
        elif m.get("type") == "msg" and addr in members:
            out = json.dumps({"from": members[addr], "seq": m["seq"], "text": m["text"]}).encode()
            for a in members:
                if a != addr:
                    if random.random() * 100 < loss:
                        print(f"  (dropped seq {m['seq']} for {members[a]})")
                    else:
                        s.sendto(out, a)
        elif m.get("type") == "leave":
            print(f"{members.pop(addr, '?')} left")


def client(host, port, name):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = (host, port)
    s.sendto(json.dumps({"type": "join", "name": name}).encode(), dest)
    last = {}                                      # sender -> highest seq seen

    def recv():
        while True:
            m = json.loads(s.recvfrom(2048)[0])
            prev = last.get(m["from"], 0)
            note = ""
            if m["seq"] < prev:
                note = "  [OUT OF ORDER / late]"
            elif m["seq"] > prev + 1:
                note = f"  [LOST {m['seq'] - prev - 1} message(s) before this]"
            last[m["from"]] = max(prev, m["seq"])
            print(f"\r[{m['from']} #{m['seq']}] {m['text']}{note}")
    threading.Thread(target=recv, daemon=True).start()
    seq = 0
    for line in sys.stdin:
        if line.strip() == "/quit":
            s.sendto(json.dumps({"type": "leave"}).encode(), dest)
            break
        seq += 1
        s.sendto(json.dumps({"type": "msg", "seq": seq, "text": line.strip()}).encode(), dest)


if __name__ == "__main__":
    if sys.argv[1] == "server":
        server(int(sys.argv[2]) if len(sys.argv) > 2 else 5001, float(sys.argv[3]) if len(sys.argv) > 3 else 0)
    else:
        client(sys.argv[2], int(sys.argv[3]), sys.argv[4])
